"""FALLBACK STRATEGY: Browser automation via Playwright.

Used when API endpoints are unknown or auth fails.
Simulates real user behavior to avoid detection.
~2-5 seconds per operation.
"""
import time
import asyncio
from typing import List, Optional
from datetime import datetime, timedelta
from playwright.async_api import async_playwright, Page, BrowserContext
from playwright_stealth import stealth_async
import structlog
from app.config import settings
from app.models import Campaign, SlotLockResult
from app.strategies.base import BaseStrategy

logger = structlog.get_logger()


class PlaywrightStrategy(BaseStrategy):
    """Browser automation strategy using Playwright.

    This is the fallback when the API strategy fails.
    It uses a real browser with anti-detection measures.
    """

    name = "playwright"

    def __init__(self, session_manager):
        super().__init__(session_manager)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def _ensure_browser(self) -> Page:
        """Lazy-init the browser with anti-detection."""
        if self._page and not self._page.is_closed():
            return self._page

        self._playwright = await async_playwright().start()

        from app.core.browser_utils import launch_playwright_browser
        self._browser = await launch_playwright_browser(
            self._playwright,
            headless=True,
            channel=settings.playwright_channel,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--disable-gpu",
                "--window-size=1920,1080",
            ],
        )

        context_options = {
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "locale": "en-US",
            "timezone_id": "America/New_York",
        }

        # Load saved session if available
        if self.session.is_valid:
            ctx_opts = self.session.get_playwright_context_options()
            context_options.update(ctx_opts)

        self._context = await self._browser.new_context(**context_options)

        # Apply stealth
        await stealth_async(self._context)

        self._page = await self._context.new_page()

        # Additional anti-detection
        await self._page.evaluate("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        return self._page

    async def list_campaigns(self) -> List[Campaign]:
        """Navigate to campaigns page and extract campaign data."""
        page = await self._ensure_browser()

        try:
            await page.goto(
                "https://arcadia-roster.up.railway.app/clip/campaigns",
                wait_until="domcontentloaded",
                timeout=30000,
            )

            # Wait for campaign cards or links to load
            await page.wait_for_selector('a[href^="/clip/campaigns/"]', timeout=15000)

            # Extract campaign data from the DOM
            campaigns = await page.evaluate("""
                () => {
                    const cards = document.querySelectorAll('a[href^="/clip/campaigns/"]');
                    return Array.from(cards).map(card => {
                        const href = card.getAttribute('href') || '';
                        const parts = href.split('/');
                        const id = parts[parts.length - 1] || '';
                        
                        const headerEl = card.querySelector('h1, h2, h3, h4, [class*="title"], [class*="header"]');
                        let title = headerEl ? headerEl.textContent.trim() : '';
                        
                        const fullText = card.textContent.trim();
                        if (!title) {
                            title = fullText.split('\\n')[0].trim() || id;
                        }
                        
                        return { id, title, fullText };
                    });
                }
            """)

            self.logger.info("playwright.list_success", count=len(campaigns))

            # Convert to Campaign models (best effort)
            result = []
            import re
            for c in campaigns:
                if not c.get("id"):
                    continue
                
                full_text = c.get("fullText", "")
                full_text_lower = full_text.lower()
                
                # Parse slots remaining
                slots_remaining = 1
                if "full" in full_text_lower or "0 left" in full_text_lower or "0 slots" in full_text_lower:
                    slots_remaining = 0
                elif "posts" in full_text_lower:
                    match = re.search(r'(\d+)\s*/\s*(\d+)\s+posts', full_text_lower)
                    if match:
                        locked, total = int(match.group(1)), int(match.group(2))
                        if locked >= total:
                            slots_remaining = 0
                
                # Parse myLock and mySubmission
                my_lock = None
                my_submission = None
                if "submitted" in full_text_lower or "clip submitted" in full_text_lower:
                    my_submission = {"_id": "scraped", "status": "submitted"}
                if "locked" in full_text_lower or "slot locked" in full_text_lower:
                    my_lock = {"slotNumber": 1, "status": "locked"}
                
                # Parse endDate (best effort, e.g., "ends 6/9/2026" or "ends 2026-06-09")
                end_date = datetime.utcnow() + timedelta(days=7)
                date_match = re.search(r'ends\s+(\d{1,2})[/-](\d{1,2})[/-](\d{4})', full_text_lower)
                if date_match:
                    try:
                        month, day, year = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
                        end_date = datetime(year, month, day, 23, 59, 59)
                    except Exception:
                        pass
                else:
                    iso_match = re.search(r'ends\s+(\d{4})[/-](\d{1,2})[/-](\d{1,2})', full_text_lower)
                    if iso_match:
                        try:
                            year, month, day = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
                            end_date = datetime(year, month, day, 23, 59, 59)
                        except Exception:
                            pass
                
                # Determine status
                status = "active"
                if slots_remaining == 0 or end_date < datetime.utcnow():
                    status = "locked"
                
                # Clean up title: if the scraped title is too long or contains the full text, trim it
                title = c["title"]
                if len(title) > 100 or "\n" in title:
                    title = title.split("\n")[0].strip()
                if len(title) > 80:
                    title = title[:77] + "..."

                result.append(Campaign(
                    _id=c["id"],
                    campaignCode=c["id"],
                    title=title,
                    description="",
                    startDate=datetime.utcnow() - timedelta(days=1),
                    endDate=end_date,
                    maxSlots=100,
                    slotsLocked=100 - slots_remaining,
                    slotsRemaining=slots_remaining,
                    kind="ugc",
                    status=status,
                    postPrice=10.0,
                    myLock=my_lock,
                    mySubmission=my_submission,
                ))

            return result

        except Exception as e:
            self.logger.error("playwright.list_failed", error=str(e))
            return []

    async def lock_slot(self, campaign_id: str) -> SlotLockResult:
        """Navigate to campaign and click the lock button.

        NOTE: claim_slot campaigns (ugcSlotMode == 'claim_slot') are NOT
        supported by this strategy.  Clicking a random slot button risks
        selecting a gold-reserved slot, which wastes the opportunity.
        These campaigns are handled by APIStrategy.lock_slot_for_claim_campaign().
        """
        start_time = time.time()

        # --- Guard: refuse claim_slot campaigns ---
        # Use a lightweight API check before spinning up the browser.
        try:
            from app.strategies.api_strategy import APIStrategy
            api = APIStrategy(self.session)
            campaign = await api.get_campaign(campaign_id)
            await api.close()
            if campaign and campaign.needs_claim:
                elapsed = (time.time() - start_time) * 1000
                return SlotLockResult(
                    success=False,
                    campaign_id=campaign_id,
                    campaign_title=campaign.title,
                    message=(
                        "Playwright does not support claim_slot campaigns — "
                        "use APIStrategy.lock_slot_for_claim_campaign() instead"
                    ),
                    strategy_used=self.name,
                    response_time_ms=elapsed,
                    definitive=True,  # Don't try AI agent either; caller should give up
                )
        except Exception:
            # If the API check fails, fall through to original behaviour rather than
            # blocking Playwright from running at all.
            pass

        page = await self._ensure_browser()


        try:
            # Navigate to specific campaign
            await page.goto(
                f"https://arcadia-roster.up.railway.app/clip/campaigns/{campaign_id}",
                wait_until="domcontentloaded",
                timeout=30000,
            )

            # Look for lock button
            lock_selectors = [
                'button:has-text("Lock")',
                'button:has-text("Lock slot")',
                'button:has-text("Lock a slot")',
                '[data-action="lock"]',
                'button[class*="lock"]',
            ]

            lock_btn = None
            for selector in lock_selectors:
                try:
                    btn = page.locator(selector).first
                    if await btn.is_visible(timeout=2000):
                        lock_btn = btn
                        break
                except:
                    continue

            if not lock_btn:
                elapsed = (time.time() - start_time) * 1000
                return SlotLockResult(
                    success=False,
                    campaign_id=campaign_id,
                    campaign_title=campaign_id,
                    message="No lock button found — campaign may be full or closed",
                    strategy_used=self.name,
                    response_time_ms=elapsed,
                )

            # Click lock with human-like delay
            await asyncio.sleep(0.5)
            await lock_btn.click()

            # Wait for confirmation or success indicator
            await asyncio.sleep(1)

            # Check for success indicators
            success_indicators = [
                'text="Slot locked"',
                'text="Success"',
                'text="Locked"',
                '[class*="success"]',
                '[data-status="locked"]',
            ]

            success = False
            for indicator in success_indicators:
                try:
                    if await page.locator(indicator).first.is_visible(timeout=2000):
                        success = True
                        break
                except:
                    continue

            # Save updated session state
            storage = await self._context.storage_state()
            self.session.save_storage_state(storage)

            elapsed = (time.time() - start_time) * 1000

            return SlotLockResult(
                success=success,
                campaign_id=campaign_id,
                campaign_title=campaign_id,
                message="Slot locked via Playwright" if success else "Lock may have failed",
                strategy_used=self.name,
                response_time_ms=elapsed,
            )

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            self.logger.error("playwright.lock_failed", error=str(e))
            return SlotLockResult(
                success=False,
                campaign_id=campaign_id,
                campaign_title=campaign_id,
                message=f"Playwright error: {str(e)}",
                strategy_used=self.name,
                response_time_ms=elapsed,
            )

    async def health_check(self) -> bool:
        """Check if browser can load Arcadia."""
        try:
            page = await self._ensure_browser()
            await page.goto("https://arcadia-roster.up.railway.app", timeout=15000)
            return await page.title() != ""
        except Exception as e:
            self.logger.debug("playwright.health_check_failed", error=str(e))
            return False

    async def close(self):
        """Clean up browser resources."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()