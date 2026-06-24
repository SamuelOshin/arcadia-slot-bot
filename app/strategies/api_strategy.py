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
                self.logger.info("api.request_sent", method=method, url=url)
                async with self.client.request(method, url, **kwargs) as response:
                    text_data = await response.text()
                    json_data = None
                    if "application/json" in response.headers.get("Content-Type", "").lower():
                        try:
                            json_data = await response.json()
                        except Exception:
                            pass
                    self.logger.info("api.request_done", method=method, url=url, status=response.status)
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
                self.logger.warning("api.request_error", method=method, url=url, error=repr(e))
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
                raise RuntimeError(f"API list_campaigns failed with status {status}")

        except AuthError:
            raise
        except Exception as e:
            self.logger.error("api.list_campaigns_error", error=repr(e))
            raise

    # --- claim_slot campaign constants ---
    MAX_SLOT_ATTEMPTS = 10         # give up after this many collisions
    MAX_LOCK_BUDGET_MS = 5000.0    # hard time-budget across all slot attempts

    async def get_campaign(self, campaign_id: str) -> Optional[Campaign]:
        """Fetch individual campaign details, including scheduledSlots.

        For claim_slot campaigns the API returns scheduledSlots at the ROOT of the
        response (not nested inside the 'campaign' object).  This method merges those
        slots into the Campaign model so callers don't need to know the response shape.
        """
        url = f"{self.base_url}/clip/campaigns/{campaign_id}"
        try:
            status, data, _, _ = await self._request("GET", url)
            if status == 200 and isinstance(data, dict):
                item = data.get("campaign", data)
                campaign = Campaign.model_validate(item)

                # Hydrate scheduledSlots from root-level key
                scheduled = data.get("scheduledSlots", [])
                if isinstance(scheduled, list):
                    campaign.scheduledSlots = scheduled
                    if scheduled:
                        # Log real field names so we can confirm/update the schema later
                        self.logger.info(
                            "api.slots_schema_observed",
                            campaign_id=campaign_id,
                            count=len(scheduled),
                            first_slot_keys=list(scheduled[0].keys()),
                        )

                return campaign

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

    async def lock_slot_for_claim_campaign(self, campaign: Campaign) -> SlotLockResult:
        """Handle slot locking for ugcSlotMode == 'claim_slot' campaigns.

        Fetches a fresh slot list, filters for eligible slots using the API's own
        reservation eligibility signal, then tries slots sequentially until one
        succeeds, the attempt ceiling is hit, or the time budget runs out.

        IMPORTANT: All 409 collisions are handled HERE and never propagate to the
        StrategyRouter or CircuitBreaker — they are expected business-domain events,
        not infrastructure failures.
        """
        start_time = time.time()
        campaign_id = campaign.id

        # Always fetch fresh detail — list endpoint doesn't include scheduledSlots
        fresh = await self.get_campaign(campaign_id)
        if not fresh or not fresh.scheduledSlots:
            self.logger.warning("api.claim_slot.no_slots", campaign_id=campaign_id)
            return SlotLockResult(
                success=False,
                campaign_id=campaign_id,
                campaign_title=campaign.title,
                message="No scheduledSlots returned by detail endpoint",
                strategy_used=self.name,
                response_time_ms=(time.time() - start_time) * 1000,
            )

        eligible = fresh.eligible_slots()
        self.logger.info(
            "api.claim_slot.eligible",
            campaign_id=campaign_id,
            total_slots=len(fresh.scheduledSlots),
            eligible_slots=len(eligible),
        )

        if not eligible:
            return SlotLockResult(
                success=False,
                campaign_id=campaign_id,
                campaign_title=campaign.title,
                message="No eligible slots after tier/availability filtering",
                strategy_used=self.name,
                response_time_ms=(time.time() - start_time) * 1000,
                definitive=True,
            )

        # Attempt sequential locking across eligible slots
        result = await self._try_lock_slots(
            campaign_id=campaign_id,
            campaign_title=campaign.title,
            eligible=eligible,
            start_time=start_time,
        )

        if result.success:
            return result

        # ONE re-fetch if we exhausted the list but still have time budget left
        elapsed_ms = (time.time() - start_time) * 1000
        if elapsed_ms < self.MAX_LOCK_BUDGET_MS:
            self.logger.info("api.claim_slot.refetch", campaign_id=campaign_id, elapsed_ms=elapsed_ms)
            refetched = await self.get_campaign(campaign_id)
            if refetched and refetched.eligible_slots():
                seen_ids = {s.get("_id") or s.get("id") for s in eligible}
                new_slots = [
                    s for s in refetched.eligible_slots()
                    if (s.get("_id") or s.get("id")) not in seen_ids
                ]
                if new_slots:
                    self.logger.info(
                        "api.claim_slot.refetch_found_new",
                        campaign_id=campaign_id,
                        new_count=len(new_slots),
                    )
                    result = await self._try_lock_slots(
                        campaign_id=campaign_id,
                        campaign_title=campaign.title,
                        eligible=new_slots,
                        start_time=start_time,
                    )

        return result

    async def _try_lock_slots(
        self,
        campaign_id: str,
        campaign_title: str,
        eligible: list,
        start_time: float,
    ) -> SlotLockResult:
        """Sequential slot try-lock loop with attempt ceiling and time budget.

        Returns on first success, or a non-definitive failure after exhaustion
        so the caller can decide whether to re-fetch.
        """
        attempts = 0
        last_result = None

        for slot in eligible:
            elapsed_ms = (time.time() - start_time) * 1000

            if elapsed_ms >= self.MAX_LOCK_BUDGET_MS:
                self.logger.warning(
                    "api.claim_slot.budget_exceeded",
                    campaign_id=campaign_id,
                    attempts=attempts,
                    elapsed_ms=elapsed_ms,
                )
                break

            if attempts >= self.MAX_SLOT_ATTEMPTS:
                self.logger.warning(
                    "api.claim_slot.max_attempts_reached",
                    campaign_id=campaign_id,
                    attempts=attempts,
                )
                break

            attempts += 1

            # Build request body — try all known candidate field names defensively
            slot_id = slot.get("_id") or slot.get("id")
            slot_number = (
                slot.get("slotNumber")
                or slot.get("position")
                or slot.get("slotIndex")
                or slot.get("index")
            )
            body: dict = {}
            if slot_id:
                body["slotId"] = slot_id
            if slot_number is not None:
                body["slotNumber"] = slot_number

            self.logger.info(
                "api.claim_slot.attempt",
                campaign_id=campaign_id,
                attempt=attempts,
                slot_id=slot_id,
                slot_number=slot_number,
            )

            url = f"{self.base_url}/clip/campaigns/{campaign_id}/lock"
            try:
                status, data, resp_text, headers = await self._request("POST", url, json=body)
            except Exception as e:
                self.logger.error("api.claim_slot.request_error", campaign_id=campaign_id, error=str(e))
                continue

            elapsed_ms = (time.time() - start_time) * 1000

            if status in (200, 201):
                title = campaign_title
                if isinstance(data, dict):
                    title = (
                        data.get("title")
                        or (data.get("campaign") or {}).get("title")
                        or campaign_title
                    )
                self.logger.info(
                    "api.claim_slot.success",
                    campaign_id=campaign_id,
                    attempt=attempts,
                    slot_id=slot_id,
                    slot_number=slot_number,
                    elapsed_ms=elapsed_ms,
                )
                return SlotLockResult(
                    success=True,
                    campaign_id=campaign_id,
                    campaign_title=title,
                    slot_number=slot_number,
                    message=f"Slot claimed on attempt {attempts} (slot_id={slot_id})",
                    strategy_used=self.name,
                    response_time_ms=elapsed_ms,
                    definitive=True,
                )

            elif status == 409:
                # Expected slot collision — NOT a circuit breaker failure event
                self.logger.info(
                    "api.claim_slot.collision",
                    campaign_id=campaign_id,
                    attempt=attempts,
                    slot_id=slot_id,
                    slot_number=slot_number,
                )
                last_result = SlotLockResult(
                    success=False,
                    campaign_id=campaign_id,
                    campaign_title=campaign_title,
                    message=f"Slot taken (attempt {attempts}, slot_id={slot_id}), trying next",
                    strategy_used=self.name,
                    response_time_ms=elapsed_ms,
                    definitive=False,  # Not definitive — keep iterating
                )
                continue  # Instant next slot

            elif status in (401, 403):
                raise AuthError("Auth failed during slot claim attempt")

            else:
                # Unexpected error on this slot — stop the whole sequence
                error_detail = self._parse_error(data, resp_text)
                self.logger.warning(
                    "api.claim_slot.unexpected_status",
                    campaign_id=campaign_id,
                    status=status,
                    error=error_detail,
                )
                return SlotLockResult(
                    success=False,
                    campaign_id=campaign_id,
                    campaign_title=campaign_title,
                    message=f"Unexpected {status} on slot claim: {error_detail}",
                    strategy_used=self.name,
                    response_time_ms=elapsed_ms,
                    definitive=True,
                )

        # All eligible slots exhausted or ceiling/budget hit
        total_elapsed = (time.time() - start_time) * 1000
        self.logger.info(
            "api.claim_slot.exhausted",
            campaign_id=campaign_id,
            attempts=attempts,
            elapsed_ms=total_elapsed,
        )
        return last_result or SlotLockResult(
            success=False,
            campaign_id=campaign_id,
            campaign_title=campaign_title,
            message=f"All {attempts} eligible slots were taken ({total_elapsed:.0f}ms)",
            strategy_used=self.name,
            response_time_ms=total_elapsed,
            definitive=False,  # Let caller decide whether to re-fetch
        )

    async def fast_lock(self, campaign_id: str) -> SlotLockResult:
        """Direct lock using the shared _request() helper.

        Previously used raw aiohttp which skipped the cookie jar, causing
        400 errors on CPM campaigns. Now uses _request() so auth headers
        and cookies are always properly injected.
        """
        start_time = time.time()
        url = f"{self.base_url}/clip/campaigns/{campaign_id}/lock"

        try:
            status, data, resp_text, headers = await self._request("POST", url, json={})
            elapsed_ms = (time.time() - start_time) * 1000

            if status in (200, 201):
                slot_num = None
                title = campaign_id
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
            elif status == 400:
                # Log full 400 body so we can see exactly what the API requires
                error_detail = self._parse_error(data, resp_text)
                self.logger.warning(
                    "api.fast_lock.bad_request",
                    campaign_id=campaign_id,
                    error=error_detail,
                    body=resp_text[:500],
                )
                return SlotLockResult(
                    success=False,
                    campaign_id=campaign_id,
                    campaign_title=campaign_id,
                    message=f"bad_request: {error_detail}",
                    strategy_used="api-fast",
                    response_time_ms=elapsed_ms,
                    definitive=True,
                )
            elif status in (401, 403):
                raise AuthError("Auth failed in fast_lock")
            else:
                self.logger.warning(
                    "api.fast_lock.unexpected_status",
                    campaign_id=campaign_id,
                    status=status,
                    body=resp_text[:200],
                )
                return SlotLockResult(
                    success=False,
                    campaign_id=campaign_id,
                    campaign_title=campaign_id,
                    message=f"failed: {status}",
                    strategy_used="api-fast",
                    response_time_ms=elapsed_ms,
                    definitive=True,
                )
        except AuthError:
            raise
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