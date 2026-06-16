"""Manages Arcadia authentication sessions.

Supports three auth methods:
1. API Token (Bearer) — fastest, preferred
2. Session Cookie — fallback for cookie-based auth
3. Playwright Storage State — full browser session persistence
"""
import json
import os
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import structlog
from app.config import settings

logger = structlog.get_logger()


class SessionManager:
    """Handles Arcadia session lifecycle: creation, refresh, validation."""

    def __init__(self):
        self._token: Optional[str] = None
        self._csrf: Optional[str] = None
        self._cookie: Optional[str] = None
        self._expires_at: Optional[datetime] = None
        self._storage_state_path = settings.arcadia_storage_state_path
        self._load_session()

    def _load_session(self) -> None:
        """Load existing session from env or storage file."""
        # 1. Determine if env cookie has changed since last boot (manual override check)
        env_cookie = settings.arcadia_session_cookie
        last_env_path = os.path.join(os.path.dirname(self._storage_state_path), "last_env_cookie.txt")
        
        env_changed = False
        if env_cookie:
            last_env_cookie = None
            if os.path.exists(last_env_path):
                try:
                    with open(last_env_path, "r", encoding="utf-8") as f:
                        last_env_cookie = f.read().strip()
                except Exception:
                    pass
            
            # If there is no record of a last seen env cookie, or it is different from the current one
            if last_env_cookie != env_cookie:
                env_changed = True
                logger.info("session.env_cookie_changed_or_new", changed=bool(last_env_cookie))
                # Save the new env cookie as last seen
                try:
                    os.makedirs(os.path.dirname(last_env_path), exist_ok=True)
                    with open(last_env_path, "w", encoding="utf-8") as f:
                        f.write(env_cookie)
                except Exception as e:
                    logger.warning("session.save_last_env_failed", error=str(e))

        # 2. Priority 1: If env cookie changed, use it to override everything (manual user dashboard update)
        if env_changed and env_cookie:
            self._cookie = env_cookie
            logger.info("session.loaded_from_env_override", method="cookie")
            # If env cookie is an override, remove storage state to force regeneration
            if os.path.exists(self._storage_state_path):
                try:
                    os.remove(self._storage_state_path)
                    logger.info("session.removed_stale_storage_state")
                except Exception:
                    pass
            return

        # 3. Priority 2: Playwright storage state file (the rolling session from persistent volume)
        if os.path.exists(self._storage_state_path):
            try:
                with open(self._storage_state_path, "r") as f:
                    state = json.load(f)

                # Extract cookies
                cookies = state.get("cookies", [])
                cookie_pairs = []
                for cookie in cookies:
                    cookie_pairs.append(f"{cookie['name']}={cookie['value']}")
                    if cookie.get("name") in ("__Secure-next-auth.session-token", "__Host-next-auth.session-token", "arcadia_session"):
                        logger.info("session.found_next_auth_cookie_in_storage", name=cookie['name'])

                if cookie_pairs:
                    self._cookie = "; ".join(cookie_pairs)

                # Extract localStorage tokens (legacy)
                origins = state.get("origins", [])
                for origin in origins:
                    if "arcadia-roster" in origin.get("origin", ""):
                        local_storage = origin.get("localStorage", [])
                        for item in local_storage:
                            if item.get("name") == "auth_token":
                                self._token = item["value"]

                logger.info("session.loaded_from_storage", path=self._storage_state_path)
                return
            except Exception as e:
                logger.warning("session.load_failed", error=str(e))

        # 4. Priority 3: Next-Auth cookie from env (first-time fallback or if storage state is empty/corrupt)
        if env_cookie:
            self._cookie = env_cookie
            logger.info("session.loaded_from_env_fallback", method="cookie")
            return

        # 5. Priority 4: Explicit API token (legacy)
        if settings.arcadia_api_token:
            self._token = settings.arcadia_api_token
            self._csrf = settings.arcadia_csrf_token
            logger.info("session.loaded_from_env_fallback", method="api_token")
            return

    def get_session_token(self) -> Optional[str]:
        """Extract __Secure-next-auth.session-token from cookie string."""
        if not self._cookie:
            return None
        for pair in self._cookie.split(";"):
            pair = pair.strip()
            if pair.startswith("__Secure-next-auth.session-token="):
                return pair.split("=", 1)[1]
            if pair.startswith("__Host-next-auth.session-token="):
                return pair.split("=", 1)[1]
        return None

    @property
    def is_valid(self) -> bool:
        """Check if current session is valid (not expired)."""
        if self._expires_at and datetime.utcnow() > self._expires_at:
            return False
        return bool(self._token or self._cookie or self.get_session_token())

    @property
    def headers(self) -> Dict[str, str]:
        """Build request headers for API calls."""
        if self._cookie:
            cleaned_cookies = "; ".join(f"{k}={v}" for k, v in self.cookie_jar.items())
            return {
                "Accept": "*/*",
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "Accept-Language": "en-US,en;q=0.9",
                "Cookie": cleaned_cookies,  # cleaned Next-Auth cookie string
                "Referer": "https://arcadia-roster.up.railway.app/clip/campaigns",
                "Sec-Ch-Ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
            }

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Referer": "https://arcadia-roster.up.railway.app/",
            "Origin": "https://arcadia-roster.up.railway.app",
        }

        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        if self._csrf:
            headers["X-CSRF-Token"] = self._csrf

        return headers

    @property
    def cookie_jar(self) -> Dict[str, str]:
        """Return cookies as dict for aiohttp/httpx."""
        cookies = {}
        if self._cookie:
            pairs = [p.strip() for p in self._cookie.split(";") if p.strip()]
            for pair in pairs:
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    k_stripped = k.strip()
                    v_stripped = v.strip()
                    if v_stripped and v_stripped != "...":
                        cookies[k_stripped] = v_stripped
        return cookies

    async def refresh(self) -> bool:
        """Attempt to refresh an expired session using the KOL token.

        Returns True if refresh succeeded, False if manual re-auth needed.
        """
        logger.info("session.refresh_attempt")

        if not settings.arcadia_api_token:
            logger.warning("session.refresh_failed_no_token")
            return False

        try:
            import httpx
            # 1. Fetch CSRF token
            csrf_url = f"{settings.arcadia_base_url}/api/auth/csrf"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Referer": f"{settings.arcadia_base_url}/"
            }
            
            async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
                resp = await client.get(csrf_url)
                data = resp.json()
                csrf_token = data.get("csrfToken")
                if not csrf_token:
                    logger.error("session.refresh_failed_no_csrf")
                    return False
                
                # 2. POST to callback with token
                callback_url = f"{settings.arcadia_base_url}/api/auth/callback/kol-token"
                payload = {
                    "csrfToken": csrf_token,
                    "token": settings.arcadia_api_token,
                    "json": "true"
                }
                
                post_resp = await client.post(callback_url, data=payload, follow_redirects=False)
                if post_resp.status_code == 200:
                    # Capture updated cookies from client
                    cookies_dict = dict(client.cookies)
                    session_cookie_name = "__Secure-next-auth.session-token"
                    if session_cookie_name not in cookies_dict:
                        # Fallback for local dev environment
                        session_cookie_name = "next-auth.session-token"
                        
                    if session_cookie_name in cookies_dict:
                        # Success! Reconstruct the cookie string
                        cookie_pairs = [f"{k}={v}" for k, v in cookies_dict.items()]
                        new_cookie_str = "; ".join(cookie_pairs)
                        
                        # Update instance fields
                        self._cookie = new_cookie_str
                        
                        # Save new cookies to Playwright storage state file so Playwright uses it too
                        storage_state = {
                            "cookies": [],
                            "origins": []
                        }
                        import time
                        for k, v in cookies_dict.items():
                            storage_state["cookies"].append({
                                "name": k,
                                "value": v,
                                "domain": "arcadia-roster.up.railway.app",
                                "path": "/",
                                "expires": time.time() + 30 * 86400,
                                "httpOnly": True if "token" in k.lower() or "csrf" in k.lower() else False,
                                "secure": True,
                                "sameSite": "Lax"
                            })
                        self.save_storage_state(storage_state)
                        
                        # Write the updated session cookie back to the .env file so it persists across bot restarts!
                        self._update_env_file(new_cookie_str)
                        
                        logger.info("session.refresh_success")
                        return True
                    else:
                        logger.error("session.refresh_failed_no_session_cookie_in_response", cookies=cookies_dict)
                else:
                    logger.error("session.refresh_failed_status", status=post_resp.status_code, body=post_resp.text[:500])
                    
        except Exception as e:
            logger.error("session.refresh_error", error=repr(e))
            
        return False

    def _update_env_file(self, new_cookie_str: str) -> None:
        """Update the ARCADIA_SESSION_COOKIE value in the .env file."""
        env_path = ".env"
        if not os.path.exists(env_path):
            return
            
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            found = False
            for i, line in enumerate(lines):
                if line.startswith("ARCADIA_SESSION_COOKIE="):
                    lines[i] = f"ARCADIA_SESSION_COOKIE={new_cookie_str}\n"
                    found = True
                    break
                    
            if not found:
                lines.append(f"\nARCADIA_SESSION_COOKIE={new_cookie_str}\n")
                
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
                
            logger.info("session.env_file_updated")
        except Exception as e:
            logger.error("session.env_file_update_failed", error=str(e))

    def update_cookies_from_response(self, response_cookies) -> None:
        """Update session cookies from the response cookies (e.g. Set-Cookie)."""
        if not response_cookies:
            return
            
        current_cookies = self.cookie_jar
        updated = False
        
        for name, cookie in response_cookies.items():
            val = cookie.value
            if val:
                current_cookies[name] = val
                updated = True
                
        if updated:
            new_cookie_str = "; ".join(f"{k}={v}" for k, v in current_cookies.items())
            self._cookie = new_cookie_str
            self._update_env_file(new_cookie_str)
            
            # Also update storage state
            try:
                import time
                storage_state = {"cookies": [], "origins": []}
                for k, v in current_cookies.items():
                    storage_state["cookies"].append({
                        "name": k,
                        "value": v,
                        "domain": "arcadia-roster.up.railway.app",
                        "path": "/",
                        "expires": time.time() + 30 * 86400,
                        "httpOnly": True if "token" in k.lower() or "csrf" in k.lower() else False,
                        "secure": True,
                        "sameSite": "Lax"
                    })
                # Call save directly
                os.makedirs(os.path.dirname(self._storage_state_path), exist_ok=True)
                with open(self._storage_state_path, "w") as f:
                    json.dump(storage_state, f, indent=2)
            except Exception as e:
                logger.debug("session.update_cookies_storage_failed", error=str(e))

    def save_storage_state(self, state: Dict[str, Any]) -> None:
        """Save Playwright storage state to disk."""
        os.makedirs(os.path.dirname(self._storage_state_path), exist_ok=True)
        with open(self._storage_state_path, "w") as f:
            json.dump(state, f, indent=2)
        logger.info("session.saved_to_storage", path=self._storage_state_path)

    def get_playwright_context_options(self) -> Dict[str, Any]:
        """Get Playwright context options with current session."""
        import time
        state = {"cookies": [], "origins": []}
        if os.path.exists(self._storage_state_path):
            try:
                with open(self._storage_state_path, "r") as f:
                    state = json.load(f)
            except Exception as e:
                logger.warning("session.load_storage_state_failed", error=str(e))

        existing_names = {c["name"] for c in state.get("cookies", [])}
        for k, v in self.cookie_jar.items():
            if k not in existing_names:
                state["cookies"].append({
                    "name": k,
                    "value": v,
                    "domain": "arcadia-roster.up.railway.app",
                    "path": "/",
                    "expires": time.time() + 30 * 86400,
                    "httpOnly": True if "token" in k.lower() or "csrf" in k.lower() else False,
                    "secure": True,
                    "sameSite": "Lax"
                })
        return {"storage_state": state}

    def __repr__(self) -> str:
        masked = "***" if self._token else None
        return f"SessionManager(token={masked}, valid={self.is_valid})"