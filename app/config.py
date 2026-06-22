"""Application configuration with Pydantic Settings."""
from typing import List, Optional, Any
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class BotConfig(BaseSettings):
    """Central configuration for the Arcadia Slot Bot."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Arcadia Auth ──────────────────────────────────────
    arcadia_api_token: Optional[str] = Field(default=None, alias="ARCADIA_API_TOKEN")
    arcadia_csrf_token: Optional[str] = Field(default=None, alias="ARCADIA_CSRF_TOKEN")
    arcadia_session_cookie: Optional[str] = Field(default=None, alias="ARCADIA_SESSION_COOKIE")
    arcadia_storage_state_path: str = Field(default="./data/auth.json", alias="ARCADIA_STORAGE_STATE_PATH")

    # ── X OAuth ───────────────────────────────────────────
    x_client_id: Optional[str] = Field(default=None, alias="X_CLIENT_ID")
    x_client_secret: Optional[str] = Field(default=None, alias="X_CLIENT_SECRET")
    x_redirect_uri: str = Field(default="http://localhost:8000/auth/callback", alias="X_REDIRECT_URI")

    # ── Bot Behavior ──────────────────────────────────────
    poll_interval_seconds: int = Field(default=30, alias="POLL_INTERVAL_SECONDS")
    campaign_filter_min_payout: float = Field(default=5.0, alias="CAMPAIGN_FILTER_MIN_PAYOUT")
    campaign_filter_max_slots_per_day: int = Field(default=3, alias="CAMPAIGN_FILTER_MAX_SLOTS_PER_DAY")
    auto_lock_enabled: bool = Field(default=False, alias="AUTO_LOCK_ENABLED")
    auto_lock_max_concurrent: int = Field(default=2, alias="AUTO_LOCK_MAX_CONCURRENT")

    # ── Strategy Configuration ────────────────────────────
    strategy_priority: Any = Field(default=["api", "playwright", "ai_agent"], alias="STRATEGY_PRIORITY")

    @field_validator("strategy_priority", mode="before")
    @classmethod
    def parse_strategy_priority(cls, v):
        if isinstance(v, str):
            if v.startswith("[") and v.endswith("]"):
                try:
                    import json
                    return json.loads(v)
                except Exception:
                    pass
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    strategy_timeout_seconds: int = Field(default=10, alias="STRATEGY_TIMEOUT_SECONDS")
    playwright_channel: Optional[str] = Field(default=None, alias="PLAYWRIGHT_CHANNEL")
    circuit_breaker_failure_threshold: int = Field(default=5, alias="CIRCUIT_BREAKER_FAILURE_THRESHOLD")
    circuit_breaker_recovery_timeout: int = Field(default=300, alias="CIRCUIT_BREAKER_RECOVERY_TIMEOUT")

    # ── Notifications ─────────────────────────────────────
    telegram_bot_token: Optional[str] = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, alias="TELEGRAM_CHAT_ID")
    discord_webhook_url: Optional[str] = Field(default=None, alias="DISCORD_WEBHOOK_URL")
    notification_on_lock: bool = Field(default=True, alias="NOTIFICATION_ON_LOCK")
    notification_on_error: bool = Field(default=True, alias="NOTIFICATION_ON_ERROR")
    notification_on_campaign_drop: bool = Field(default=True, alias="NOTIFICATION_ON_CAMPAIGN_DROP")

    # ── AI Agent ──────────────────────────────────────────
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    ai_agent_model: str = Field(default="gpt-4o", alias="AI_AGENT_MODEL")
    ai_agent_max_steps: int = Field(default=20, alias="AI_AGENT_MAX_STEPS")

    # ── Redis ─────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # ── Server ────────────────────────────────────────────
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="text", alias="LOG_FORMAT")
    environment: str = Field(default="development", alias="ENVIRONMENT")

    # ── Monitoring ────────────────────────────────────────
    metrics_enabled: bool = Field(default=True, alias="METRICS_ENABLED")
    metrics_port: int = Field(default=9090, alias="METRICS_PORT")

    @property
    def arcadia_base_url(self) -> str:
        return "https://arcadia-roster.up.railway.app"

    @property
    def arcadia_api_base(self) -> str:
        return f"{self.arcadia_base_url}/api"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


# Singleton config instance
settings = BotConfig()