#!/usr/bin/env python3
"""Interactive session setup for Arcadia authentication.

Guides the user through capturing their Next-Auth session cookie
and saving it for the bot to use.

Usage:
    python scripts/setup_session.py
    python scripts/setup_session.py --check
    python scripts/setup_session.py --test
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings


def safe_print(*args, **kwargs):
    sep = kwargs.get('sep', ' ')
    end = kwargs.get('end', '\n')
    file = kwargs.get('file', sys.stdout)
    text = sep.join(str(arg) for arg in args)
    try:
        file.write(text + end)
        file.flush()
    except UnicodeEncodeError:
        text = (text.replace("✅", "[OK]")
                    .replace("❌", "[FAIL]")
                    .replace("⚠️", "[WARN]")
                    .replace("🎉", "[SUCCESS]")
                    .replace("🎯", "[DROP]")
                    .replace("💰", "[PAYOUT]")
                    .replace("🪑", "[SLOTS]")
                    .replace("⏰", "[ENDS]")
                    .replace("🚀", "[START]")
                    .replace("🏁", "[RUN]")
                    .replace("❓", "[?]")
                    .replace("🎭", "[PLAYWRIGHT]")
                    .replace("🌐", "[WEB]")
                    .replace("📡", "[API]")
                    .replace("⚡", "[ACTION]")
                    .replace("🔒", "[LOCK]")
                    .replace("🔍", "[DEBUG]")
                    .replace("📢", "[CAMP]")
                    .replace("📊", "[STATS]"))
        try:
            file.write(text + end)
            file.flush()
        except Exception:
            try:
                file.write(text.encode('ascii', errors='replace').decode('ascii') + end)
                file.flush()
            except Exception:
                pass

print = safe_print


def print_header(text: str):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def setup_next_auth_cookie():
    """Guide user to capture and save the Next-Auth session cookie."""
    print_header("Arcadia Next-Auth Session Cookie Setup")

    print("""
Arcadia uses Next-Auth for authentication (not a custom JWT Bearer token).
To authenticate, you need to capture the cookies from your browser.

INSTRUCTIONS:
1. Open https://arcadia-roster.up.railway.app in your browser and log in.
2. Open Chrome DevTools (press F12 or Right-Click -> Inspect).
3. Go to Application tab (or Storage tab in Firefox).
4. Click on Cookies -> https://arcadia-roster.up.railway.app.
5. Look for the cookie named:
   __Secure-next-auth.session-token
   (or next-auth.session-token if running locally)
6. Copy the entire COOKIE HEADER value (all cookies) OR copy just that token.
   For the best results, copy your entire Cookie string from any request header
   in the Network tab.

Paste the value below:
""")

    cookie = input("Cookie string / Session token: ").strip()

    if cookie:
        # If they just pasted the token, format it as a cookie pair
        if "=" not in cookie:
            cookie = f"__Secure-next-auth.session-token={cookie}"
        
        save_session_cookie(cookie)
        print("✅ Session cookie saved to .env!")
    else:
        print("⚠️ No session cookie provided.")


def save_session_cookie(cookie: str):
    """Save session cookie to .env file."""
    env_path = Path(".env")

    lines = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()

    # Remove existing ARCADIA_SESSION_COOKIE and ARCADIA_API_TOKEN lines
    lines = [l for l in lines if not l.startswith("ARCADIA_SESSION_COOKIE=") and not l.startswith("ARCADIA_API_TOKEN=")]
    lines.append(f"ARCADIA_SESSION_COOKIE={cookie}")

    env_path.write_text("\n".join(lines) + "\n")


def check_session():
    """Check if current session configuration is valid."""
    print_header("Session Health Check")

    checks = {
        "Next-Auth Cookie (ARCADIA_SESSION_COOKIE)": bool(settings.arcadia_session_cookie),
        "Storage State File (data/auth.json)": os.path.exists(settings.arcadia_storage_state_path),
    }

    any_valid = False
    for name, valid in checks.items():
        status = "✅" if valid else "❌"
        print(f"  {status} {name}")
        if valid:
            any_valid = True

    print()
    if any_valid:
        print("🎉 At least one authentication method is configured!")
        print("   Test your session with: python scripts/setup_session.py --test")
    else:
        print("⚠️ No valid auth method found.")
        print("   Run setup: python scripts/setup_session.py")

    return any_valid


async def test_session_async():
    """Verify session against the live campaigns API endpoint."""
    from app.core.session_manager import SessionManager
    from app.strategies.api_strategy import APIStrategy

    print_header("Testing Session Cookie Connection")

    session = SessionManager()
    if not session.is_valid:
        print("❌ Session is not configured or is invalid. Run setup first.")
        return False

    strategy = APIStrategy(session)
    try:
        print("📡 Making a GET request to /api/clip/campaigns...")
        campaigns = await strategy.list_campaigns()
        
        # Verify if request was successful and returned campaigns list
        if campaigns is not None:
            print(f"✅ Session is VALID! Successfully fetched {len(campaigns)} campaigns.")
            for c in campaigns[:3]:
                slots = c.slotsRemaining if c.slotsRemaining is not None else "unlimited"
                print(f"   - {c.title} ({c.campaignCode}) | Payout: ${c.payout_amount}/{c.payout_unit} | Slots: {slots}")
            return True
        else:
            print("❌ Connection test failed. The API returned an empty or invalid campaigns list.")
            return False
    except Exception as e:
        print(f"❌ Error connecting to Arcadia API: {e}")
        return False
    finally:
        await strategy.close()


def test_session():
    """Synchronous wrapper for test_session_async."""
    try:
        return asyncio.run(test_session_async())
    except Exception as e:
        print(f"❌ Async execution error: {e}")
        return False


def capture_browser_session():
    """Use Playwright to capture a live browser session and export state."""
    print_header("Capturing Browser Session via Playwright")

    try:
        from playwright.async_api import async_playwright

        async def do_capture():
            print("🎭 Launching Chromium...")
            async with async_playwright() as p:
                from app.core.browser_utils import launch_playwright_browser
                browser = await launch_playwright_browser(
                    p,
                    headless=False,
                    channel=settings.playwright_channel
                )
                context = await browser.new_context()
                page = await context.new_page()

                print("🌐 Navigating to Arcadia...")
                print("   URL: https://arcadia-roster.up.railway.app")
                await page.goto("https://arcadia-roster.up.railway.app")

                input("\n👉 Log in via the browser window. Once you're fully logged in and on the dashboard, press ENTER here...")

                # Save storage state
                os.makedirs("data", exist_ok=True)
                await context.storage_state(path="data/auth.json")

                # Extract cookie string
                cookies = await context.cookies()
                cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                save_session_cookie(cookie_str)

                print("\n✅ Playwright session state saved to data/auth.json")
                print("✅ Next-Auth cookie string saved to .env")
                await browser.close()

        asyncio.run(do_capture())

    except ImportError:
        print("❌ Playwright is not installed. Please install it first:")
        print("   uv pip install playwright && playwright install chromium")
    except Exception as e:
        print(f"❌ Error during capture: {e}")


def main():
    parser = argparse.ArgumentParser(description="Arcadia Session Setup")
    parser.add_argument("--check", action="store_true", help="Check current session status")
    parser.add_argument("--capture", action="store_true", help="Capture browser session interactively")
    parser.add_argument("--test", action="store_true", help="Make a test request to verify the session works")
    args = parser.parse_args()

    if args.check:
        ok = check_session()
        sys.exit(0 if ok else 1)

    if args.test:
        ok = test_session()
        sys.exit(0 if ok else 1)

    if args.capture:
        capture_browser_session()
        return

    # Interactive setup
    print_header("Arcadia Slot Bot — Session Setup")
    print("""
Welcome! This script helps you authenticate the bot with Arcadia's Next-Auth session.

The bot needs your session cookie to act on your behalf.
Choose your preferred method:
""")

    print("1. Next-Auth Cookie (easy, copy-paste cookie string)")
    print("2. Interactive Browser Capture (opens browser automatically, captures session)")
    print("3. Check current session status")
    print("4. Test active session connection")
    print("5. Exit")

    choice = input("\nSelect option (1-5): ").strip()

    if choice == "1":
        setup_next_auth_cookie()
    elif choice == "2":
        capture_browser_session()
    elif choice == "3":
        check_session()
    elif choice == "4":
        test_session()
    else:
        print("Goodbye!")


if __name__ == "__main__":
    main()