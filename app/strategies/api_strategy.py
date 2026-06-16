"""PRIMARY STRATEGY: Direct API calls.

Fastest approach (~50-200ms). Requires reverse-engineered endpoints.
Falls back to Playwright if API returns 401/403 or unknown endpoints.
"""
import time
import socket
import asyncio
from typing import List, Optional, Tuple, Any
import aiohttp
import structlog
from app.config import settings
from app.models import Campaign, SlotLockResult, CampaignStatus
from app.strategies.base import BaseStrategy

logger = structlog.get_logger()


class APIStrategy(BaseStrategy):
    """Direct HTTP API strategy for Arcadia.

    Uses reverse-engineered endpoints. This is the primary strategy
    because it's the fastest and most reliable when endpoints are known.
    """

    name = "api"

    def __init__(self, session_manager):
        super().__init__(session_manager)
        connector = aiohttp.TCPConnector(
            family=socket.AF_INET,
            limit=10,
            limit_per_host=5,
            keepalive_timeout=30.0,
        )
        self.client = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=10.0, connect=3.0),
            headers={
                "Connection": "keep-alive",
                "Keep-Alive": "timeout=30, max=100",
            }
        )
        self.base_url = settings.arcadia_api_base

    async def _request(self, method: str, url: str, **kwargs) -> Tuple[int, Any, str, dict]:
        """Perform an HTTP request with immediate retries on connection failures (max 2 retries)."""
        max_retries = 2
        last_err = None

        # Inject default session headers and cookies if not explicitly overridden
        if "headers" not in kwargs:
            kwargs["headers"] = self.session.headers
        if "cookies" not in kwargs:
            kwargs["cookies"] = self.session.cookie_jar

        # Apply connection timeout budget of 5s total unless overridden
        if "timeout" not in kwargs:
            kwargs["timeout"] = aiohttp.ClientTimeout(total=5.0, connect=3.0)

        for attempt in range(max_retries + 1):
            try:
                async with self.client.request(method, url, **kwargs) as response:
                    text_data = await response.text()
                    json_data = None
                    if "application/json" in response.headers.get("Content-Type", "").lower():
                        try:
                            json_data = await response.json()
                        except Exception:
                            pass
                    if response.cookies:
                        self.session.update_cookies_from_response(response.cookies)
                    if response.status in (401, 403):
                        self.logger.warning("api.auth_failed_in_request", status=response.status)
                        if await self.session.refresh():
                            # Re-inject headers and cookies for retry
                            kwargs["headers"] = self.session.headers
                            kwargs["cookies"] = self.session.cookie_jar
                            continue
                    return response.status, json_data, text_data, dict(response.headers)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_err = e
                if attempt == max_retries:
                    break
                self.logger.warning("api.request_retry", url=url, attempt=attempt + 1, error=repr(e))
                # Immediate retry — no sleep delay on connection failures

        raise last_err

    async def list_campaigns(self) -> List[Campaign]:
        """Fetch campaigns via API.

        Targets the real /clip/campaigns endpoint directly.
        """
        url = f"{self.base_url}/clip/campaigns"
        try:
            status, data, _, _ = await self._request("GET", url)

            if status == 200:
                campaigns = self._parse_campaigns(data)
                self.logger.info("api.list_success", count=len(campaigns))

                # Filter out campaigns where status == "locked"
                active_campaigns = [c for c in campaigns if c.status != "locked"]

                # Sort by: active first, then slotsRemaining asc, then payout desc
                def sort_key(c: Campaign):
                    is_active_val = 0 if c.status == "active" else 1
                    slots = c.slotsRemaining if c.slotsRemaining is not None else float('inf')
                    payout_val = c.payout_amount
                    return (is_active_val, slots, -payout_val)

                active_campaigns.sort(key=sort_key)
                return active_campaigns

            elif status in (401, 403):
                self.logger.warning("api.auth_failed", status=status)
                raise AuthError("API authentication failed")
            else:
                self.logger.error("api.list_failed", status=status)

        except AuthError:
            raise
        except Exception as e:
            self.logger.error("api.list_campaigns_error", error=repr(e))

        return []

    async def get_campaign(self, campaign_id: str) -> Optional[Campaign]:
        """Fetch individual campaign details."""
        url = f"{self.base_url}/clip/campaigns/{campaign_id}"
        try:
            status, data, _, _ = await self._request("GET", url)
            if status == 200:
                item = data
                if isinstance(data, dict) and "campaign" in data:
                    item = data["campaign"]
                return Campaign.model_validate(item)

            elif status in (401, 403):
                self.logger.warning("api.auth_failed_get_campaign", campaign_id=campaign_id, status=status)
                raise AuthError("API authentication failed during campaign fetch")

        except AuthError:
            raise
        except Exception as e:
            self.logger.error("api.get_campaign_failed", campaign_id=campaign_id, error=str(e))

        return None

    async def lock_slot(self, campaign_id: str) -> SlotLockResult:
        """Lock a slot via API POST.

        Uses the REAL endpoint: POST /api/clip/campaigns/{campaign_id}/lock
        Request body: {}
        """
        start_time = time.time()
        url = f"{self.base_url}/clip/campaigns/{campaign_id}/lock"

        try:
            status, data, resp_text, headers = await self._request("POST", url, json={})
            elapsed_ms = (time.time() - start_time) * 1000

            # Log full response details for non-2xx statuses
            if status not in (200, 201):
                self.logger.debug("api.lock_response", 
                    status=status,
                    body=resp_text[:500],
                    headers=headers,
                    url=url
                )

            if status in (200, 201):
                title = campaign_id
                slot_num = None
                if isinstance(data, dict):
                    title = data.get("title") or (data.get("campaign") or {}).get("title") or campaign_id
                    slot_num = data.get("slotNumber")
                    if slot_num is None and "myLock" in data and isinstance(data["myLock"], dict):
                        slot_num = data["myLock"].get("slotNumber")
                    if slot_num is None and "lock" in data and isinstance(data["lock"], dict):
                        slot_num = data["lock"].get("slotNumber")
                    if slot_num is None:
                        slot_num = data.get("slot_number") or data.get("slotsLocked")

                return SlotLockResult(
                    success=True,
                    campaign_id=campaign_id,
                    campaign_title=title,
                    slot_number=slot_num,
                    message="Slot locked successfully via API",
                    strategy_used=self.name,
                    response_time_ms=elapsed_ms,
                    definitive=True,
                )

            elif status == 409:
                error_detail = self._parse_error(data, resp_text)
                return SlotLockResult(
                    success=False,
                    campaign_id=campaign_id,
                    campaign_title=campaign_id,
                    message=f"Slot already taken (conflict): {error_detail}",
                    strategy_used=self.name,
                    response_time_ms=elapsed_ms,
                    definitive=True,
                )

            elif status == 400:
                error_detail = self._parse_error(data, resp_text)
                return SlotLockResult(
                    success=False,
                    campaign_id=campaign_id,
                    campaign_title=campaign_id,
                    message=f"Bad Request: {error_detail}",
                    strategy_used=self.name,
                    response_time_ms=elapsed_ms,
                    definitive=True,
                )

            elif status in (401, 403):
                raise AuthError("API authentication failed during lock")

            elif status == 404:
                # Try fallback endpoints
                fallback_patterns = [
                    f"/clip/campaigns/{campaign_id}/claim",
                    f"/clip/campaigns/{campaign_id}/slots",
                    f"/clip/slots/{campaign_id}/claim",
                    f"/clip/campaigns/{campaign_id}/reserve",
                ]
                for pattern in fallback_patterns:
                    self.logger.info("api.lock_fallback_attempt", url=pattern)
                    fallback_url = f"{self.base_url}{pattern}"
                    try:
                        f_status, f_data, f_text, f_headers = await self._request("POST", fallback_url, json={})
                        f_elapsed = (time.time() - start_time) * 1000
                        if f_status in (200, 201):
                            self.logger.info("api.lock_fallback_success", url=pattern)
                            slot_num = None
                            if isinstance(f_data, dict):
                                slot_num = f_data.get("slotNumber") or (f_data.get("myLock") or {}).get("slotNumber")
                            return SlotLockResult(
                                success=True,
                                campaign_id=campaign_id,
                                campaign_title=campaign_id,
                                slot_number=slot_num,
                                message=f"Slot locked successfully via fallback: {pattern}",
                                strategy_used=self.name,
                                response_time_ms=f_elapsed,
                                definitive=True,
                            )
                    except Exception as fe:
                        self.logger.debug("api.lock_fallback_failed", url=pattern, error=str(fe))

                # All fallbacks failed
                return SlotLockResult(
                    success=False,
                    campaign_id=campaign_id,
                    campaign_title=campaign_id,
                    message="Campaign lock endpoint not found (404, fallback patterns exhausted)",
                    strategy_used=self.name,
                    response_time_ms=elapsed_ms,
                    definitive=True,
                )

            elif status == 429:
                retry_after_str = headers.get("Retry-After")
                retry_after = 1.0
                if retry_after_str:
                    try:
                        retry_after = float(retry_after_str)
                    except ValueError:
                        pass
                self.logger.warning("api.rate_limited", campaign_id=campaign_id, retry_after=retry_after)

                # Retry budget up to 3s
                if retry_after <= 3.0:
                    self.logger.info("api.rate_limited_retry", campaign_id=campaign_id, wait_seconds=retry_after)
                    await asyncio.sleep(retry_after)
                    status, data, resp_text, headers = await self._request("POST", url, json={})
                    elapsed_ms = (time.time() - start_time) * 1000

                    if status in (200, 201):
                        title = campaign_id
                        slot_num = None
                        if isinstance(data, dict):
                            title = data.get("title") or (data.get("campaign") or {}).get("title") or campaign_id
                            slot_num = data.get("slotNumber")
                            if slot_num is None and "myLock" in data and isinstance(data["myLock"], dict):
                                slot_num = data["myLock"].get("slotNumber")
                            if slot_num is None and "lock" in data and isinstance(data["lock"], dict):
                                slot_num = data["lock"].get("slotNumber")
                            if slot_num is None:
                                slot_num = data.get("slot_number") or data.get("slotsLocked")

                        return SlotLockResult(
                            success=True,
                            campaign_id=campaign_id,
                            campaign_title=title,
                            slot_number=slot_num,
                            message="Slot locked successfully via API after rate-limit retry",
                            strategy_used=self.name,
                            response_time_ms=elapsed_ms,
                            definitive=True,
                        )
                    elif status == 409:
                        error_detail = self._parse_error(data, resp_text)
                        return SlotLockResult(
                            success=False,
                            campaign_id=campaign_id,
                            campaign_title=campaign_id,
                            message=f"Slot already taken (conflict): {error_detail}",
                            strategy_used=self.name,
                            response_time_ms=elapsed_ms,
                            definitive=True,
                        )
                    elif status == 400:
                        error_detail = self._parse_error(data, resp_text)
                        return SlotLockResult(
                            success=False,
                            campaign_id=campaign_id,
                            campaign_title=campaign_id,
                            message=f"Bad Request: {error_detail}",
                            strategy_used=self.name,
                            response_time_ms=elapsed_ms,
                            definitive=True,
                        )
                    elif status in (401, 403):
                        raise AuthError("API authentication failed during lock retry")

                return SlotLockResult(
                    success=False,
                    campaign_id=campaign_id,
                    campaign_title=campaign_id,
                    message=f"Rate limited (Retry-After: {retry_after}s)",
                    strategy_used=self.name,
                    response_time_ms=elapsed_ms,
                    definitive=False,
                )

        except AuthError:
            raise
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            self.logger.error("api.lock_failed", campaign_id=campaign_id, error=str(e))
            return SlotLockResult(
                success=False,
                campaign_id=campaign_id,
                campaign_title=campaign_id,
                message=f"API lock failed: {str(e)}",
                strategy_used=self.name,
                response_time_ms=elapsed_ms,
            )

    async def fast_lock(self, campaign_id: str) -> SlotLockResult:
        """Direct, minimal overhead lock bypass for maximum speed."""
        start_time = time.time()
        url = f"{self.base_url}/clip/campaigns/{campaign_id}/lock"
        headers = self.session.headers.copy()

        try:
            async with self.client.post(url, headers=headers, json={}, timeout=3.0) as response:
                status = response.status
                elapsed_ms = (time.time() - start_time) * 1000

                if status in (200, 201):
                    slot_num = None
                    try:
                        data = await response.json()
                        if isinstance(data, dict):
                            slot_num = data.get("slotNumber")
                            if slot_num is None and "myLock" in data and isinstance(data["myLock"], dict):
                                slot_num = data["myLock"].get("slotNumber")
                            if slot_num is None and "lock" in data and isinstance(data["lock"], dict):
                                slot_num = data["lock"].get("slotNumber")
                            if slot_num is None:
                                slot_num = data.get("slot_number") or data.get("slotsLocked")
                    except:
                        pass

                    return SlotLockResult(
                        success=True,
                        campaign_id=campaign_id,
                        campaign_title=campaign_id,
                        slot_number=slot_num,
                        message="locked",
                        strategy_used="api-fast",
                        response_time_ms=elapsed_ms,
                        definitive=True,
                    )
                elif status == 409:
                    return SlotLockResult(
                        success=False,
                        campaign_id=campaign_id,
                        campaign_title=campaign_id,
                        message="taken",
                        strategy_used="api-fast",
                        response_time_ms=elapsed_ms,
                        definitive=True,
                    )
                else:
                    return SlotLockResult(
                        success=False,
                        campaign_id=campaign_id,
                        campaign_title=campaign_id,
                        message=f"failed: {status}",
                        strategy_used="api-fast",
                        response_time_ms=elapsed_ms,
                        definitive=True,
                    )
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            return SlotLockResult(
                success=False,
                campaign_id=campaign_id,
                campaign_title=campaign_id,
                message=f"error: {str(e)}",
                strategy_used="api-fast",
                response_time_ms=elapsed_ms,
                definitive=False,
            )

    def _parse_error(self, json_data: Any, resp_text: str) -> str:
        """Parse structured API error detail from body."""
        if isinstance(json_data, dict):
            return (
                json_data.get("message") or
                json_data.get("error") or
                json_data.get("detail") or
                json_data.get("reason") or
                str(json_data)
            )
        return resp_text[:200]

    async def health_check(self) -> bool:
        """Check if API is reachable and we can authenticate."""
        try:
            status, _, _, _ = await self._request("GET", f"{self.base_url}/clip/campaigns")
            return status == 200
        except Exception as e:
            self.logger.debug("api.health_check_failed", error=str(e))
            return False

    def _parse_campaigns(self, data) -> List[Campaign]:
        """Parse various API response formats into Campaign models."""
        campaigns = []
        items = data
        if isinstance(data, dict):
            items = data.get("campaigns", data.get("data", data.get("items", [])))

        if not isinstance(items, list):
            self.logger.warning("api.unexpected_response_format", type=type(data).__name__)
            return []

        for item in items:
            try:
                campaign = Campaign.model_validate(item)
                campaigns.append(campaign)
            except Exception as e:
                self.logger.debug("api.parse_campaign_failed", error=str(e))
                continue

        return campaigns

    async def close(self):
        """Clean up session."""
        await self.client.close()


class AuthError(Exception):
    """Raised when API authentication fails. Triggers fallback to Playwright."""
    pass