#!/usr/bin/env python3
"""Standalone test script to check Arcadia campaigns and attempt locks.
"""
import asyncio
import json
import os
import sys
from typing import List

# Ensure app is in path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.core.session_manager import SessionManager
from app.strategies.api_strategy import APIStrategy
from app.strategies.strategy_router import StrategyRouter
from app.services.arcadia_client import ArcadiaClient


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


async def main():
    print("=" * 60)
    print("        Arcadia API Strategy Tester")
    print("=" * 60)

    # 1. Load session
    print("\n[1] Loading session...")
    session = SessionManager()
    if not session.is_valid:
        print("❌ Error: No valid session cookie or token found in .env or data/auth.json.")
        print("   Please run setup first: python scripts/setup_session.py")
        sys.exit(1)

    print("✅ Session loaded.")

    strategy = APIStrategy(session)
    from app.core.notifier import Notifier
    from app.core.circuit_breaker import CircuitBreaker
    notifier = Notifier()
    circuit_breaker = CircuitBreaker()
    router = StrategyRouter(session, notifier, circuit_breaker)
    client = ArcadiaClient(router)

    try:
        campaigns = await strategy.list_campaigns()
        if campaigns is None:
            print("❌ Failed to fetch campaigns list.")
            sys.exit(1)

        print(f"📊 Found {len(campaigns)} total campaigns.")

        lockable_campaigns = []

        print("\n--- Campaign List & Lockability ---")
        for c in campaigns:
            is_lockable = c.is_lockable
            lockable_str = "✅ LOCKABLE" if is_lockable else "❌ LOCKED/INELIGIBLE"
            
            # Print details
            slots = c.slotsRemaining if c.slotsRemaining is not None else "unlimited"
            print(f"\n📢 {c.title} ({c.campaignCode}) [{lockable_str}]")
            print(f"   - Kind: {c.kind}")
            print(f"   - Payout: ${c.payout_amount}/{c.payout_unit}")
            print(f"   - Slots Remaining: {slots}")
            print(f"   - Status: {c.status}")
            print(f"   - URL: {c.url}")
            
            # Reservation details if present
            if c.reservation:
                print(f"   - Reservation:")
                print(f"     * Enabled: {c.reservation.get('enabled')}")
                print(f"     * Eligible for Me: {c.reservation.get('reservedEligibleForMe')}")
                print(f"     * General: {c.reservation.get('generalLocked')}/{c.reservation.get('generalCapacity')}")
                print(f"     * Reserved: {c.reservation.get('reservedLocked')}/{c.reservation.get('reservedTotal')}")

            # Explanation of lockability
            reasons = []
            if c.status != "active":
                reasons.append("Status is not 'active'")
            if c.myLock is not None:
                reasons.append("You already locked this campaign")
            if c.mySubmission is not None:
                reasons.append("You already submitted a clip")
            if c.slotsRemaining is not None and c.slotsRemaining <= 0:
                reasons.append("No slots remaining")
            if c.ends_at:
                from datetime import datetime
                now = datetime.now(c.ends_at.tzinfo) if c.ends_at.tzinfo else datetime.utcnow()
                if now > c.ends_at:
                    reasons.append("Campaign has ended")
            if c.reservation and not c.reservation.get("reservedEligibleForMe", False):
                gen_locked = c.reservation.get("generalLocked", 0)
                gen_capacity = c.reservation.get("generalCapacity", 0)
                if gen_locked >= gen_capacity:
                    reasons.append("Reservation enabled: you are ineligible for reserved slots, and general slots are full")
            
            if reasons:
                print(f"   - Reason not lockable: {', '.join(reasons)}")
            else:
                print(f"   - Status: Lockable!")
                lockable_campaigns.append(c)

        print("\n" + "=" * 40)
        print(f"Summary: {len(lockable_campaigns)} lockable campaigns found.")
        print("=" * 40)

        # 3. Interactive locking
        print("\n[3] Interactive Locking Test")
        for lc in campaigns:
            ans = input(f"\n❓ Do you want to attempt to lock slot for '{lc.title}' ({lc.campaignCode})? (y/n): ").strip().lower()
            if ans == 'y':
                strategy_choice = input("   Choose strategy (api / playwright / ai_agent / ENTER for default): ").strip().lower()
                strategy_override = strategy_choice if strategy_choice in ("api", "playwright", "ai_agent") else None
                
                print(f"⚡ Attempting to lock campaign '{lc.title}' using {strategy_override or 'default'} strategy...")
                
                # Lock via ArcadiaClient
                result = await client.lock_campaign(lc.id, strategy=strategy_override, force=True)
                
                print(f"\n🔒 Result:")
                print(f"   - Success: {result.success}")
                print(f"   - Message: {result.message}")
                print(f"   - Strategy used: {result.strategy_used}")
                print(f"   - Response time: {result.response_time_ms:.1f}ms")
                
                # Print full strategy lock result payload for debugging
                print(f"\n🔍 Debug details (Result JSON):")
                print(json.dumps(result.model_dump(), default=str, indent=2))

    except Exception as e:
        print(f"❌ Error during test run: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await strategy.close()


if __name__ == "__main__":
    asyncio.run(main())
