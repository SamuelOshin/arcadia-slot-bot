import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.session_manager import SessionManager
from app.strategies.api_strategy import APIStrategy
from app.strategies.playwright_strategy import PlaywrightStrategy
from app.strategies.ai_agent_strategy import AIAgentStrategy
from app.core.notifier import Notifier
from app.core.circuit_breaker import CircuitBreaker
from app.strategies.strategy_router import StrategyRouter
from app.services.arcadia_client import ArcadiaClient

# Use standard print since we're writing ASCII logs
def main():
    print("=" * 60)
    print("    Arcadia Automated Multi-Strategy Tester")
    print("=" * 60)

    session = SessionManager()
    if not session.is_valid:
        print("[FAIL] Session is not valid.")
        sys.exit(1)
        
    print("[OK] Session loaded successfully.")
    
    # 1. API Strategy Test
    print("\n--- [1] Testing API Strategy ---")
    async def run_api():
        strategy = APIStrategy(session)
        try:
            print("Fetching campaigns via API Strategy...")
            campaigns = await strategy.list_campaigns()
            print(f"API Success! Found {len(campaigns)} campaigns.")
            for c in campaigns[:3]:
                print(f"  - {c.title} ({c.id}) | Payout: {c.payout_amount} | Status: {c.status} | Lockable: {c.is_lockable}")
            return campaigns
        except Exception as e:
            print(f"API Strategy failed: {e}")
            import traceback
            traceback.print_exc()
            return []
        finally:
            await strategy.close()

    campaigns = asyncio.run(run_api())
    
    # 2. Playwright Strategy Test
    print("\n--- [2] Testing Playwright Strategy ---")
    async def run_playwright(target_campaign_id):
        strategy = PlaywrightStrategy(session)
        try:
            print("Fetching campaigns via Playwright Strategy...")
            playwright_campaigns = await strategy.list_campaigns()
            print(f"Playwright Success! Found {len(playwright_campaigns)} campaigns in DOM.")
            for pc in playwright_campaigns[:3]:
                print(f"  - {pc.title} ({pc.id})")
                
            if target_campaign_id:
                print(f"Attempting lock_slot for campaign '{target_campaign_id}' via Playwright...")
                result = await strategy.lock_slot(target_campaign_id)
                print("Playwright Lock Slot Result:")
                print(f"  - Success: {result.success}")
                print(f"  - Message: {result.message}")
                print(f"  - Strategy used: {result.strategy_used}")
                print(f"  - Response time: {result.response_time_ms:.1f}ms")
        except Exception as e:
            print(f"Playwright Strategy failed: {e}")
        finally:
            await strategy.close()

    # Determine campaign ID to test with (use the user's campaign if available, otherwise first campaign)
    target_id = "6a26fc8012907abb71e8dcab"
    if not any(c.id == target_id for c in campaigns) and campaigns:
        target_id = campaigns[0].id
        print(f"Using campaign '{target_id}' for lock test.")
    else:
        print(f"Using target campaign '{target_id}' for lock test.")

    asyncio.run(run_playwright(target_id))

    # 3. AI Agent Strategy Test
    print("\n--- [3] Testing AI Agent Strategy ---")
    from app.config import settings
    if not settings.openai_api_key or "sk-..." in settings.openai_api_key:
        print("[WARN] OpenAI API key is a placeholder or not provided. Skipping AI Agent test.")
    else:
        async def run_ai(target_campaign_id):
            strategy = AIAgentStrategy(session)
            try:
                print(f"Attempting lock_slot for campaign '{target_campaign_id}' via AI Agent...")
                result = await strategy.lock_slot(target_campaign_id)
                print("AI Agent Lock Slot Result:")
                print(f"  - Success: {result.success}")
                print(f"  - Message: {result.message}")
                print(f"  - Strategy used: {result.strategy_used}")
                print(f"  - Response time: {result.response_time_ms:.1f}ms")
            except Exception as e:
                print(f"AI Agent Strategy failed: {e}")
            finally:
                await strategy.close()
        
        asyncio.run(run_ai(target_id))

if __name__ == "__main__":
    main()
