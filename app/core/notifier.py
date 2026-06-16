"""Multi-channel notification system.

Supports Telegram, Discord webhook, and console logging.
"""
import asyncio
from typing import Optional, List
from datetime import datetime
import structlog
import httpx
from app.config import settings
from app.models import SlotLockResult, Campaign

logger = structlog.get_logger()


class Notifier:
    """Sends notifications across multiple channels."""

    def __init__(self):
        self._telegram_token = settings.telegram_bot_token
        self._telegram_chat_id = settings.telegram_chat_id
        self._discord_webhook = settings.discord_webhook_url
        self._http = httpx.AsyncClient(timeout=10.0)

    async def notify_slot_locked(self, result: SlotLockResult) -> None:
        """Notify that a slot was successfully locked."""
        if not settings.notification_on_lock:
            return

        emoji = "🔒" if result.success else "❌"
        message = f"""
{emoji} <b>Slot Lock {'Successful' if result.success else 'Failed'}</b>

<b>Campaign:</b> {result.campaign_title}
<b>ID:</b> <code>{result.campaign_id}</code>
<b>Strategy:</b> {result.strategy_used}
<b>Response Time:</b> {result.response_time_ms:.0f}ms
<b>Time:</b> {result.timestamp.strftime("%H:%M:%S UTC")}

{result.message}
""".strip()

        await self._send_all(message)

    async def notify_near_miss(self, campaign: Campaign, response_time_ms: float) -> None:
        """Notify on near-miss lock attempts (slot taken by someone else)."""
        message = f"""
⚡ <b>Near Miss!</b>

<b>{campaign.title}</b>
💰 <b>Payout:</b> ${campaign.payout_amount}/{campaign.payout_unit}
⏱️ <b>Response time:</b> {response_time_ms:.0f}ms

Slot was taken between detection and lock.
Consider reducing poll interval or enabling faster locking.
""".strip()
        await self._send_all(message)

    async def notify_campaign_dropped(self, campaign: Campaign) -> None:
        """Notify when a new campaign with available slots appears."""
        if not settings.notification_on_campaign_drop:
            return

        message = f"""
🎯 <b>New Campaign Drop!</b>

<b>{campaign.title}</b>
💰 <b>Payout:</b> ${campaign.payout_amount}/{campaign.payout_unit}
🪑 <b>Slots:</b> {campaign.slots_remaining} remaining
⏰ <b>Ends:</b> {campaign.ends_at.strftime("%Y-%m-%d %H:%M") if campaign.ends_at else "N/A"}

<a href="{campaign.url}">Open Campaign →</a>
""".strip()

        await self._send_all(message)

    async def notify_error(self, error_message: str, context: Optional[dict] = None) -> None:
        """Notify on critical errors."""
        if not settings.notification_on_error:
            return

        ctx = f"\n<code>{str(context)}</code>" if context else ""
        message = f"""
⚠️ <b>Arcadia Bot Error</b>

{error_message}{ctx}

<i>Check logs for details.</i>
""".strip()

        await self._send_all(message)

    async def notify_session_expired(self) -> None:
        """Notify when session needs manual re-authentication."""
        message = """
🔐 <b>Session Expired</b>

Your Arcadia session has expired and could not be refreshed automatically.

Please run the setup script to re-authenticate:
<code>python scripts/setup_session.py</code>
""".strip()

        await self._send_all(message, priority=True)

    async def _send_all(self, message: str, priority: bool = False) -> None:
        """Send to all configured channels concurrently."""
        tasks = []

        if self._telegram_token and self._telegram_chat_id:
            tasks.append(self._send_telegram(message))

        if self._discord_webhook:
            tasks.append(self._send_discord(message))

        # Always log
        logger.info("notification.sent", message=message[:100])

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error("notification.channel_failed", index=i, error=str(result))

    async def _send_telegram(self, message: str) -> None:
        """Send message via Telegram Bot API."""
        url = f"https://api.telegram.org/bot{self._telegram_token}/sendMessage"
        payload = {
            "chat_id": self._telegram_chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }

        response = await self._http.post(url, json=payload)
        response.raise_for_status()

    async def _send_discord(self, message: str) -> None:
        """Send message via Discord webhook."""
        # Strip HTML tags for Discord
        import re
        clean_message = re.sub(r"<[^>]+>", "", message)

        payload = {
            "content": clean_message,
            "username": "Arcadia Slot Bot",
        }

        response = await self._http.post(self._discord_webhook, json=payload)
        response.raise_for_status()

    async def close(self) -> None:
        await self._http.aclose()