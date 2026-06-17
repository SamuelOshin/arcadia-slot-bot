"""Interactive Telegram Bot Service.

Provides remote control, configuration management, status monitoring,
and manual/auto slot locking directly from Telegram.
"""
import asyncio
import os
import random
import html
from collections import deque
from datetime import datetime
from typing import Optional, List

import structlog
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.models import CampaignFilter
from app.services.campaign_monitor import CampaignMonitor
from app.core.scheduler import BotScheduler

logger = structlog.get_logger()


# --- Memory Log Buffer for Log Tailing ---
class MemoryLogBuffer:
    """Stores a ring buffer of logs in memory for tailing via Telegram."""
    def __init__(self, maxlen: int = 50):
        self.buffer = deque(maxlen=maxlen)

    def append(self, log_line: str) -> None:
        self.buffer.append(log_line)

    def get_logs(self) -> List[str]:
        return list(self.buffer)


log_buffer = MemoryLogBuffer()


def structlog_memory_buffer_processor(logger_inst, name: str, event_dict: dict) -> dict:
    """Structlog processor to capture logs into the in-memory buffer."""
    try:
        timestamp = event_dict.get("timestamp", datetime.utcnow().isoformat())
        level = event_dict.get("level", "INFO").upper()
        event = event_dict.get("event", "")
        
        # Capture other keys as extra details
        extras = {k: v for k, v in event_dict.items() if k not in ("timestamp", "level", "event")}
        extras_str = f" {extras}" if extras else ""
        
        log_line = f"[{timestamp}] {level}: {event}{extras_str}"
        log_buffer.append(log_line)
    except Exception:
        pass
    return event_dict


# --- Telegram Bot Service class ---
class TelegramBotService:
    """Service to run and manage the interactive Telegram Bot."""
    
    def __init__(self, monitor: CampaignMonitor, scheduler: BotScheduler):
        self.monitor = monitor
        self.scheduler = scheduler
        self.app: Optional[Application] = None
        self.pairing_code: Optional[str] = None
        self.logger = logger.bind(component="telegram_bot")

    async def start(self) -> None:
        """Initialize and start the Telegram Bot polling task."""
        token = settings.telegram_bot_token
        if not token:
            self.logger.warning("telegram.missing_token_cannot_start")
            return

        # If chat ID is not configured, generate a pairing code
        if not settings.telegram_chat_id:
            self.pairing_code = str(random.randint(1000, 9999))
            self.logger.info("=" * 60)
            self.logger.info(f"🔑 TELEGRAM BOT PAIRING CODE: {self.pairing_code}")
            self.logger.info(f"Send '/start {self.pairing_code}' to your bot on Telegram to pair.")
            self.logger.info("=" * 60)

        # Build application
        self.app = Application.builder().token(token).build()

        # Command handlers
        self.app.add_handler(CommandHandler("start", self.handle_start))
        self.app.add_handler(CommandHandler("status", self.handle_status))
        self.app.add_handler(CommandHandler("campaigns", self.handle_campaigns))
        self.app.add_handler(CommandHandler("autolock", self.handle_autolock))
        self.app.add_handler(CommandHandler("refresh", self.handle_refresh))
        self.app.add_handler(CommandHandler("logs", self.handle_logs))
        self.app.add_handler(CommandHandler("pause", self.handle_pause))
        self.app.add_handler(CommandHandler("resume", self.handle_resume))
        self.app.add_handler(CommandHandler("set_cookie", self.handle_set_cookie))
        self.app.add_handler(CommandHandler("set_min_payout", self.handle_set_min_payout))
        self.app.add_handler(CommandHandler("set_interval", self.handle_set_interval))

        # Handle text menu choices
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))

        # Handle inline query callbacks
        self.app.add_handler(CallbackQueryHandler(self.handle_callback))

        # Start background polling
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        self.logger.info("telegram.bot_started")

    async def stop(self) -> None:
        """Stop the Telegram Bot polling task gracefully."""
        if self.app:
            self.logger.info("telegram.bot_stopping")
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            self.logger.info("telegram.bot_stopped")

    async def is_authorized(self, update: Update) -> bool:
        """Verify if the update is from the list of allowed chat IDs."""
        if not settings.telegram_chat_id:
            return False
        # Support a comma-separated list of allowed user IDs
        allowed_ids = [x.strip() for x in settings.telegram_chat_id.split(",") if x.strip()]
        return str(update.effective_chat.id) in allowed_ids

    def update_env_var(self, key: str, value: str) -> None:
        """Helper to write config variables back to the .env file."""
        env_path = ".env"
        try:
            lines = []
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            
            found = False
            for i, line in enumerate(lines):
                if line.startswith(f"{key}="):
                    lines[i] = f"{key}={value}\n"
                    found = True
                    break
            
            if not found:
                lines.append(f"\n{key}={value}\n")
                
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            self.logger.info("telegram.config_persisted_to_env", key=key)
        except Exception as e:
            self.logger.error("telegram.persist_env_failed", key=key, error=str(e))

    async def send_main_menu(self, update: Update) -> None:
        """Display the main persistent command menu/keyboard."""
        keyboard = [
            ["📊 Status", "🎯 Open Campaigns"],
            ["🔄 Force Check", "⚙️ Auto-Lock"],
            ["📜 View Logs", "🔧 Config Menu"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "🎮 <b>Arcadia Bot Control Console</b>\nUse the buttons below to control the bot.",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )

    # --- Command Handlers ---

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id

        # Pairing flow if chat ID is not set
        if not settings.telegram_chat_id:
            args = context.args
            if args and args[0] == self.pairing_code:
                settings.telegram_chat_id = str(chat_id)
                self.update_env_var("TELEGRAM_CHAT_ID", str(chat_id))
                self.pairing_code = None
                await update.message.reply_text(
                    "🎉 <b>Pairing Successful!</b>\n\nYou are now registered as the administrator of this bot.",
                    parse_mode="HTML"
                )
                await self.send_main_menu(update)
            else:
                await update.message.reply_text(
                    "⚠️ <b>Bot Not Paired</b>\n\nPlease check your server startup logs for the 4-digit pairing code and send:\n<code>/start &lt;code&gt;</code> to pair.",
                    parse_mode="HTML"
                )
            return

        if not await self.is_authorized(update):
            await update.message.reply_text("❌ Unauthorized. This is a private bot.")
            return

        await update.message.reply_text("👋 Welcome back to the Arcadia Control Panel!")
        await self.send_main_menu(update)

    async def show_status(self, update: Update) -> None:
        """Helper to generate and output status message."""
        scheduler_health = "🟢 Active" if self.scheduler._running else "🔴 Paused"
        session_valid = "✅ Valid" if self.monitor.session.is_valid else "❌ Invalid / Expired"
        
        last_check_str = "Never"
        if self.monitor._last_check:
            seconds_ago = int((datetime.utcnow() - self.monitor._last_check).total_seconds())
            last_check_str = f"{seconds_ago}s ago"

        stats = self.monitor.client.get_stats()
        
        message = f"""
📊 <b>Arcadia Bot Status</b>

🤖 <b>Scheduler:</b> {scheduler_health}
🔐 <b>Session Auth:</b> {session_valid}
⏰ <b>Last Check:</b> {last_check_str}

⚙️ <b>Current Config:</b>
• Poll Interval: <code>{settings.poll_interval_seconds}s</code> (Current: <code>{self.scheduler.current_interval}s</code>)
• Min Payout: <code>${settings.campaign_filter_min_payout}</code>
• Auto-Lock: <code>{'ENABLED' if settings.auto_lock_enabled else 'DISABLED'}</code>

📈 <b>Stats Today:</b>
• Slots Locked: <code>{stats.get('slots_locked_today', 0)}/{stats.get('daily_limit', 3)}</code>
• Remaining Quota: <code>{stats.get('quota_remaining', 0)}</code>
• Total Monitored: <code>{len(self.monitor._known_campaigns)}</code>
""".strip()
        
        keyboard = [
            [
                InlineKeyboardButton("🔄 Refresh Session", callback_data="session_refresh"),
                InlineKeyboardButton("⚡ Force Check", callback_data="force_check"),
            ],
            [
                InlineKeyboardButton("⏸️ Pause Scheduler" if self.scheduler._running else "▶️ Resume Scheduler", 
                                     callback_data="toggle_scheduler")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, parse_mode="HTML", reply_markup=reply_markup)

    async def show_campaigns(self, update: Update) -> None:
        """Fetch and list open campaigns with locking inline buttons."""
        await update.message.reply_text("🔍 Fetching available campaigns from Arcadia...")
        try:
            campaigns = await self.monitor.client.get_available_campaigns(
                filters=CampaignFilter(min_payout=0.0, auto_lock=False)
            )
            
            if not campaigns:
                await update.message.reply_text("🪹 No open campaigns currently available.")
                return

            for c in campaigns[:5]:
                slots = c.slots_remaining if c.slots_remaining is not None else "Unlimited"
                filter_check = "✅ Matches filter" if c.payout_amount >= settings.campaign_filter_min_payout else "⚠️ Below min payout"
                
                msg = f"""
🎯 <b>{c.title}</b>
🆔 <code>{c.id}</code> (Code: <code>{c.campaignCode}</code>)
💰 <b>Payout:</b> ${c.payout_amount}/{c.payout_unit}
🪑 <b>Slots:</b> {slots} remaining
📋 <b>Type:</b> {c.kind.upper()} | {filter_check}
""".strip()
                
                keyboard = [
                    [
                        InlineKeyboardButton("🔒 Lock Slot", callback_data=f"lock_{c.id}"),
                        InlineKeyboardButton("🌐 Open Link", url=c.url)
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(msg, parse_mode="HTML", reply_markup=reply_markup)
                
            if len(campaigns) > 5:
                await update.message.reply_text(f"<i>...and {len(campaigns) - 5} more campaigns.</i>", parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"❌ Failed to fetch campaigns: {str(e)}")

    async def trigger_force_check(self, update: Update) -> None:
        """Force the campaign monitor to check immediately."""
        await update.message.reply_text("🔄 Triggering immediate campaign check and autolock...")
        try:
            next_interval = await self.monitor.check_and_lock()
            await update.message.reply_text(f"✅ Check complete! Next scheduled check in {next_interval}s.")
        except Exception as e:
            await update.message.reply_text(f"❌ Force check failed: {str(e)}")

    async def show_autolock_menu(self, update: Update) -> None:
        """Display Auto-Lock settings and toggle buttons."""
        status = "ENABLED ✅" if settings.auto_lock_enabled else "DISABLED ❌"
        msg = f"""
⚙️ <b>Auto-Lock Settings</b>

Status: <b>{status}</b>
Max Concurrent: <code>{settings.auto_lock_max_concurrent}</code>
Daily Limit: <code>{settings.campaign_filter_max_slots_per_day}</code>

Auto-lock automatically claims slots for you as soon as they drop, matching your filters.
""".strip()
        
        keyboard = [
            [
                InlineKeyboardButton(
                    "❌ Disable Auto-Lock" if settings.auto_lock_enabled else "✅ Enable Auto-Lock",
                    callback_data="toggle_autolock"
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=reply_markup)

    async def show_logs(self, update: Update) -> None:
        """Display recent logs."""
        logs = log_buffer.get_logs()
        if not logs:
            await update.message.reply_text("📋 No logs recorded in memory yet.")
            return
            
        text = "\n".join(logs[-20:])
        escaped_text = html.escape(text)
        
        if len(escaped_text) > 4000:
            escaped_text = escaped_text[-4000:]
            
        await update.message.reply_text(
            f"📋 <b>Recent Activity Logs:</b>\n<pre>{escaped_text}</pre>",
            parse_mode="HTML"
        )

    async def show_config_menu(self, update: Update) -> None:
        """Show configuration details."""
        msg = f"""
🔧 <b>Bot Configuration Menu</b>

• <b>Min Payout:</b> ${settings.campaign_filter_min_payout}
• <b>Poll Interval:</b> {settings.poll_interval_seconds} seconds
• <b>Max Slots/Day:</b> {settings.campaign_filter_max_slots_per_day}

To edit these values or update your credentials, use the following commands:
• <code>/set_min_payout &lt;amount&gt;</code>
• <code>/set_interval &lt;seconds&gt;</code>
• <code>/set_cookie &lt;cookie_string&gt;</code>
""".strip()
        await update.message.reply_text(msg, parse_mode="HTML")

    # --- Command Handlers ---

    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.is_authorized(update):
            await update.message.reply_text("❌ Unauthorized.")
            return
        await self.show_status(update)

    async def handle_campaigns(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.is_authorized(update):
            await update.message.reply_text("❌ Unauthorized.")
            return
        await self.show_campaigns(update)

    async def handle_autolock(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.is_authorized(update):
            await update.message.reply_text("❌ Unauthorized.")
            return
        await self.show_autolock_menu(update)

    async def handle_refresh(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.is_authorized(update):
            await update.message.reply_text("❌ Unauthorized.")
            return
        await self.trigger_force_check(update)

    async def handle_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.is_authorized(update):
            await update.message.reply_text("❌ Unauthorized.")
            return
        await self.show_logs(update)

    async def handle_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.is_authorized(update):
            await update.message.reply_text("❌ Unauthorized.")
            return
        if self.scheduler._running:
            self.scheduler.stop()
            await update.message.reply_text("⏸️ Scheduler paused.")
        else:
            await update.message.reply_text("⚠️ Scheduler is already paused.")

    async def handle_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.is_authorized(update):
            await update.message.reply_text("❌ Unauthorized.")
            return
        if not self.scheduler._running:
            self.scheduler.start()
            await update.message.reply_text("▶️ Scheduler resumed.")
        else:
            await update.message.reply_text("⚠️ Scheduler is already running.")

    async def handle_set_cookie(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.is_authorized(update):
            await update.message.reply_text("❌ Unauthorized.")
            return

        if not context.args:
            await update.message.reply_text("⚠️ Please provide the cookie string. Example: `/set_cookie key=val; ...`")
            return

        cookie_val = " ".join(context.args)
        if "=" not in cookie_val:
            cookie_val = f"__Secure-next-auth.session-token={cookie_val}"

        try:
            self.update_env_var("ARCADIA_SESSION_COOKIE", cookie_val)
            settings.arcadia_session_cookie = cookie_val
            self.monitor.session._cookie = cookie_val
            self.monitor.session._load_session()
            
            await update.message.reply_text("✅ <b>Session cookie updated!</b> Connection test in progress...", parse_mode="HTML")
            
            strategy = self.monitor.client.router._get_strategy("api")
            try:
                campaigns = await strategy.list_campaigns()
                if campaigns is not None:
                    await update.message.reply_text(f"🎉 <b>Success!</b> Fetched {len(campaigns)} campaigns successfully.", parse_mode="HTML")
                else:
                    await update.message.reply_text("⚠️ Cookie updated, but API returned empty/invalid list.", parse_mode="HTML")
            except Exception as e:
                await update.message.reply_text(f"❌ API Connection test failed: {str(e)}")
        except Exception as e:
            await update.message.reply_text(f"❌ Failed to update cookie: {str(e)}")

    async def handle_set_min_payout(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.is_authorized(update):
            await update.message.reply_text("❌ Unauthorized.")
            return

        if not context.args:
            await update.message.reply_text("⚠️ Please specify an amount. Example: `/set_min_payout 5.0`")
            return

        try:
            amount = float(context.args[0])
            self.update_env_var("CAMPAIGN_FILTER_MIN_PAYOUT", str(amount))
            settings.campaign_filter_min_payout = amount
            await update.message.reply_text(f"✅ Minimum payout filter updated to <b>${amount}</b>.", parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("❌ Invalid float value.")

    async def handle_set_interval(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.is_authorized(update):
            await update.message.reply_text("❌ Unauthorized.")
            return

        if not context.args:
            await update.message.reply_text("⚠️ Please specify an interval in seconds. Example: `/set_interval 30`")
            return

        try:
            seconds = int(context.args[0])
            if seconds < 5:
                await update.message.reply_text("⚠️ Polling interval must be at least 5 seconds for safety.")
                return
                
            self.update_env_var("POLL_INTERVAL_SECONDS", str(seconds))
            settings.poll_interval_seconds = seconds
            
            if self.scheduler._running:
                self.scheduler.scheduler.reschedule_job(
                    "poll_campaigns",
                    trigger=IntervalTrigger(seconds=seconds)
                )
                self.scheduler.current_interval = seconds
                
            await update.message.reply_text(f"✅ Poll interval updated to <b>{seconds}s</b> and scheduler rescheduled.", parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("❌ Invalid integer value.")

    # --- Text menu buttons dispatcher ---

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.is_authorized(update):
            await update.message.reply_text("❌ Unauthorized.")
            return

        text = update.message.text
        if text == "📊 Status":
            await self.show_status(update)
        elif text == "🎯 Open Campaigns":
            await self.show_campaigns(update)
        elif text == "🔄 Force Check":
            await self.trigger_force_check(update)
        elif text == "⚙️ Auto-Lock":
            await self.show_autolock_menu(update)
        elif text == "📜 View Logs":
            await self.show_logs(update)
        elif text == "🔧 Config Menu":
            await self.show_config_menu(update)
        else:
            await update.message.reply_text("❓ Unknown option. Please use the menu below.")

    # --- Callback query handler ---

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        
        if not settings.telegram_chat_id or str(query.message.chat.id) != settings.telegram_chat_id:
            await query.message.reply_text("❌ Unauthorized callback.")
            return
            
        data = query.data
        
        if data == "session_refresh":
            await query.message.reply_text("🔄 Attempting to refresh session...")
            success = await self.monitor.session.refresh()
            if success:
                await query.message.reply_text("✅ Session refreshed successfully using KOL token.")
            else:
                await query.message.reply_text("❌ Session refresh failed. Paste a new cookie with `/set_cookie`.")
                
        elif data == "force_check":
            await query.message.reply_text("🔄 Running campaign check...")
            try:
                next_interval = await self.monitor.check_and_lock()
                await query.message.reply_text(f"✅ Check complete. Next in {next_interval}s.")
            except Exception as e:
                await query.message.reply_text(f"❌ Check failed: {str(e)}")
                
        elif data == "toggle_scheduler":
            if self.scheduler._running:
                self.scheduler.stop()
                await query.message.reply_text("⏸️ Scheduler paused.")
            else:
                self.scheduler.start()
                await query.message.reply_text("▶️ Scheduler resumed.")
                
        elif data == "toggle_autolock":
            settings.auto_lock_enabled = not settings.auto_lock_enabled
            self.update_env_var("AUTO_LOCK_ENABLED", str(settings.auto_lock_enabled).lower())
            status = "ENABLED ✅" if settings.auto_lock_enabled else "DISABLED ❌"
            await query.message.reply_text(f"⚙️ Auto-Lock is now <b>{status}</b>.", parse_mode="HTML")
            
        elif data.startswith("lock_"):
            campaign_id = data.split("lock_")[1]
            await query.message.reply_text(f"🔒 Attempting to lock campaign <code>{campaign_id}</code>...", parse_mode="HTML")
            try:
                # Force=True allows manual slot claiming override
                result = await self.monitor.client.lock_campaign(campaign_id, force=True)
                emoji = "✅" if result.success else "❌"
                await query.message.reply_text(
                    f"{emoji} <b>Lock {'Success' if result.success else 'Failed'}</b>\n\n{result.message}",
                    parse_mode="HTML"
                )
            except Exception as e:
                await query.message.reply_text(f"❌ Exception during lock attempt: {str(e)}")
