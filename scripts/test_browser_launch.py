import asyncio
from playwright.async_api import async_playwright

async def test_launch(channel_name):
    print(f"\nTesting launch with channel: '{channel_name}'...")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                channel=channel_name if channel_name else None
            )
            print(f"  -> SUCCESS! Browser version: {browser.version}")
            await browser.close()
            return True
    except Exception as e:
        # Avoid printing full exception trace containing box-drawing characters
        err_msg = str(e).replace("\u2554", "").replace("\u2550", "").replace("\u2551", "").replace("\u255a", "").replace("\u255d", "")
        # Keep it simple and ascii only
        err_msg = err_msg.encode('ascii', errors='replace').decode('ascii')
        print(f"  -> FAILED: {err_msg[:120]}...")
        return False

async def main():
    print("Testing browser launch methods...")
    # 1. Default (None)
    await test_launch(None)
    # 2. Chrome
    await test_launch("chrome")
    # 3. MSEdge
    await test_launch("msedge")

if __name__ == "__main__":
    asyncio.run(main())
