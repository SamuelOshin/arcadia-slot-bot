"""Utilities for browser automation, including robust browser launching."""
from typing import Optional, List
import structlog
from app.config import settings

logger = structlog.get_logger()


def _clean_error(e: Exception) -> str:
    """Sanitize exception message to avoid console encoding errors on Windows."""
    return str(e).encode("ascii", errors="replace").decode("ascii")


async def launch_playwright_browser(
    playwright_context,
    headless: bool = True,
    channel: Optional[str] = None,
    args: Optional[List[str]] = None,
):
    """Launch a Chromium browser with automatic fallbacks for missing binaries.

    Tries the following in order:
    1. Specified channel (if provided via settings/parameter)
    2. Default launch (using Playwright's downloaded browser)
    3. 'chrome' channel (uses installed Google Chrome)
    4. 'msedge' channel (uses installed Microsoft Edge)
    """
    if args is None:
        args = []

    # 1. Try specified channel first
    if channel:
        try:
            logger.info("browser.launching_with_explicit_channel", channel=channel)
            return await playwright_context.chromium.launch(
                headless=headless,
                channel=channel,
                args=args,
            )
        except Exception as e:
            logger.warning("browser.explicit_channel_failed", channel=channel, error=_clean_error(e))

    # 2. Try default launch (no channel)
    try:
        logger.info("browser.launching_default")
        return await playwright_context.chromium.launch(
            headless=headless,
            args=args,
        )
    except Exception as e:
        logger.warning("browser.default_launch_failed", error=_clean_error(e))

    # 3. Fallback to system Google Chrome
    try:
        logger.info("browser.launching_fallback_chrome")
        return await playwright_context.chromium.launch(
            headless=headless,
            channel="chrome",
            args=args,
        )
    except Exception as e:
        logger.warning("browser.fallback_chrome_failed", error=_clean_error(e))

    # 4. Fallback to system Microsoft Edge
    try:
        logger.info("browser.launching_fallback_msedge")
        return await playwright_context.chromium.launch(
            headless=headless,
            channel="msedge",
            args=args,
        )
    except Exception as e:
        logger.error("browser.all_launch_methods_failed", error=_clean_error(e))
        raise e
