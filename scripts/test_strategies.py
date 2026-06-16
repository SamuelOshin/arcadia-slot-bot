#!/usr/bin/env python3
"""Test all strategies individually to verify setup.

Usage:
    python scripts/test_strategies.py
    python scripts/test_strategies.py --strategy api
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.session_manager import SessionManager
from app.core.circuit_breaker import CircuitBreaker
from app.core.notifier import Notifier
from app.strategies.api_strategy import APIStrategy
from app.strategies.playwright_strategy import PlaywrightStrategy
from app.strategies.ai_agent_strategy import AIAgentStrategy


async def test_strategy(strategy_class, name: str):
    """Test a single strategy."""
    print(f"\n{'='*50}")
    print(f"Testing: {name}")
    print(f"{'='*50}")

    session = SessionManager()
    strategy = strategy_class(session)

    # Health check
    print(f"\n[1/3] Health Check...")
    healthy = await strategy.health_check()
    print(f"      Result: {'✅ Healthy' if healthy else '❌ Unhealthy'}")

    if not healthy:
        print(f"      Skipping further tests (strategy unhealthy)")
        return

    # List campaigns
    print(f"\n[2/3] List Campaigns...")
    try:
        campaigns = await strategy.list_campaigns()
        print(f"      Found: {len(campaigns)} campaigns")
        for c in campaigns[:3]:
            print(f"      - {c.title} (${c.payout_amount}/{c.payout_unit}, {c.slots_remaining} slots)")
    except Exception as e:
        print(f"      ❌ Error: {e}")

    # Cleanup
    print(f"\n[3/3] Cleanup...")
    if hasattr(strategy, 'close'):
        await strategy.close()
    print(f"      ✅ Done")


async def main():
    parser = argparse.ArgumentParser(description="Test Arcadia Bot Strategies")
    parser.add_argument("--strategy", choices=["api", "playwright", "ai_agent"], help="Test specific strategy")
    args = parser.parse_args()

    strategies = {
        "api": (APIStrategy, "API Strategy (Primary)"),
        "playwright": (PlaywrightStrategy, "Playwright Strategy (Fallback)"),
        "ai_agent": (AIAgentStrategy, "AI Agent Strategy (Emergency)"),
    }

    if args.strategy:
        cls, name = strategies[args.strategy]
        await test_strategy(cls, name)
    else:
        for key, (cls, name) in strategies.items():
            await test_strategy(cls, name)

    print("\n\n✅ All tests complete!")


if __name__ == "__main__":
    asyncio.run(main())