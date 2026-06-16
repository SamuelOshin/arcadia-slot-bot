import asyncio
from playwright.async_api import async_playwright
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.session_manager import SessionManager

def safe_print(text):
    try:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    except UnicodeEncodeError:
        safe_text = text.encode('ascii', errors='replace').decode('ascii')
        sys.stdout.write(safe_text + "\n")
        sys.stdout.flush()

async def main():
    session = SessionManager()
    opts = session.get_playwright_context_options()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        context = await browser.new_context(**opts)
        page = await context.new_page()
        
        await page.goto("https://arcadia-roster.up.railway.app/clip/campaigns", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(5)
        
        # Find all anchors matching the pattern
        anchors = page.locator('a[href^="/clip/campaigns/"]')
        count = await anchors.count()
        safe_print(f"Found {count} campaign anchor links.")
        
        for i in range(count):
            anchor = anchors.nth(i)
            href = await anchor.get_attribute("href")
            inner_text = await anchor.inner_text()
            inner_html = await anchor.inner_html()
            safe_print(f"\n--- Anchor {i}: {href} ---")
            safe_print(f"Inner Text:\n{inner_text}")
            safe_print(f"HTML Structure:\n{inner_html[:1000]}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
