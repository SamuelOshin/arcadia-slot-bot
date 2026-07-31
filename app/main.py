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
    monitors = []
    # Single coordinator shared across all monitors:
    # prevents multiple accounts burning daily quota on the same single-slot campaign.
    from app.services.campaign_monitor import LockCoordinator
    coordinator = LockCoordinator()

    for i, account in enumerate(settings.accounts):
        logger.info("app.startup_account", name=account.name, account_index=i)
        monitor = CampaignMonitor(
            account=account,
            coordinator=coordinator,
            account_index=i,
        )

        # Try to verify and auto-login if token is available and session is missing/invalid
        if not monitor.session.is_valid or not monitor.session.get_session_token():
            logger.info("app.startup_session_invalid_or_missing_attempting_refresh", account=account.name)
            await monitor.session.refresh()
        monitors.append(monitor)

    scheduler = BotScheduler(monitors)
    scheduler.start()

    app.state.scheduler = scheduler
    app.state.monitors = monitors
    app.state.monitor = monitors[0] if monitors else None

    # Initialize and start Telegram bot
    tg_bot = None
    if settings.telegram_bot_token:
        try:
            logger.info("app.startup_telegram_bot")
            from app.services.telegram_bot import TelegramBotService
            tg_bot = TelegramBotService(monitors, [scheduler])
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

# Mount Static Frontend SPA if built
import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if not os.path.exists(frontend_dist):
    frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dist")

if os.path.exists(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="static_assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/") or full_path in ("docs", "redoc", "openapi.json"):
            return RedirectResponse(url="/docs")
        file_path = os.path.join(frontend_dist, full_path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(frontend_dist, "index.html"))
else:
    @app.get("/")
    async def root():
        """Root endpoint with basic info when frontend build is not mounted."""
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
    return RedirectResponse(url="/docs")