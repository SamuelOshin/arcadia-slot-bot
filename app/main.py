"""Arcadia Slot Bot — FastAPI Application Entry Point.

Multi-strategy campaign slot automation with:
- API-first primary strategy
- Playwright browser automation fallback
- AI agent emergency fallback
- Circuit breaker pattern
- Real-time notifications
"""
import sys
import asyncio
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from app.config import settings
from app.api.routes import api_router
from app.core.scheduler import BotScheduler
from app.services.campaign_monitor import CampaignMonitor

# Configure structured logging
from app.services.telegram_bot import structlog_memory_buffer_processor

renderer = (
    structlog.processors.JSONRenderer()
    if settings.log_format.lower() == "json"
    else structlog.dev.ConsoleRenderer(colors=False)
)

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog_memory_buffer_processor,
        renderer,
    ],
    wrapper_class=structlog.make_filtering_bound_logger(settings.log_level),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager.

    Starts background scheduler on startup,
    gracefully shuts down on exit.
    """
    logger.info("app.startup", version="1.0.0", env=settings.environment)

    # Initialize and start background scheduler
    monitor = CampaignMonitor()
    
    # Try to verify and auto-login if token is available and session is missing/invalid
    if not monitor.session.is_valid or not monitor.session.get_session_token():
        logger.info("app.startup_session_invalid_or_missing_attempting_refresh")
        await monitor.session.refresh()

    scheduler = BotScheduler(monitor)
    scheduler.start()

    app.state.scheduler = scheduler
    app.state.monitor = monitor

    # Initialize and start Telegram bot
    tg_bot = None
    if settings.telegram_bot_token:
        try:
            logger.info("app.startup_telegram_bot")
            from app.services.telegram_bot import TelegramBotService
            tg_bot = TelegramBotService(monitor, scheduler)
            await tg_bot.start()
            app.state.tg_bot = tg_bot
        except Exception as tg_err:
            logger.error("app.telegram_bot_startup_failed", error=str(tg_err))

    logger.info("app.ready", port=settings.port)

    yield

    # Shutdown
    logger.info("app.shutdown")
    if hasattr(app.state, "tg_bot") and app.state.tg_bot:
        try:
            await app.state.tg_bot.stop()
        except Exception as tg_stop_err:
            logger.error("app.telegram_bot_shutdown_failed", error=str(tg_stop_err))
    scheduler.stop()


# Create FastAPI app
app = FastAPI(
    title="Arcadia Slot Bot",
    description="""
    Multi-strategy automation for Arcadia Roster campaign slots.

    ## Strategies
    - **API** (Primary): Direct HTTP calls — fastest (~50ms)
    - **Playwright** (Fallback): Browser automation — reliable (~2-5s)
    - **AI Agent** (Emergency): Vision-language model — resilient (~10-30s)

    ## Features
    - Automatic campaign monitoring
    - Slot locking with failover
    - Circuit breaker pattern
    - Telegram/Discord notifications
    - Configurable filters and quotas
    """,
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all API routes
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    """Root endpoint with basic info."""
    return {
        "name": "Arcadia Slot Bot",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/api/v1/health",
    }


@app.get("/docs-redirect")
async def docs_redirect():
    """Redirect to Swagger UI."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/docs")