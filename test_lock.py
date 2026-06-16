#!/usr/bin/env python3
"""Standalone test script to check Arcadia campaigns and test locking a specific campaign.
"""
import asyncio
import json
import os
import sys

# Ensure app is in path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.core.session_manager import SessionManager
from app.strategies.api_strategy import APIStrategy


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
                    .replace("🔒", "[LOCK]")
                    .replace("📡", "[API]"))
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
    print("        Arcadia Lock Strategy Tester")
    print("=" * 60)

    # 1. Load session
    print("\n[1] Loading session...")
    session = SessionManager()
    if not session.is_valid:
        print("❌ Error: No valid session cookie or token found.")
        sys.exit(1)

    print("✅ Session loaded.")

    # Initialize API strategy
    strategy = APIStrategy(session)

    try:
        # 2. Fetch campaigns
        print("\n[2] Fetching active campaigns via API Strategy...")
        campaigns = await strategy.list_campaigns()
        if not campaigns:
            print("❌ No campaigns found or failed to fetch.")
            sys.exit(1)

        print(f"📊 Found {len(campaigns)} active campaigns.")

        lockable_campaigns = []
        for c in campaigns:
            is_lockable = c.is_lockable
            lockable_str = "✅ Lockable" if is_lockable else "❌ Ineligible/Locked"
            slots = c.slotsRemaining if c.slotsRemaining is not None else "unlimited"
            print(f"- {c.title} ({c.id}) [{lockable_str}] (Slots: {slots}, Status: {c.status})")
            if is_lockable:
                lockable_campaigns.append(c)

        print(f"\nTotal lockable campaigns: {len(lockable_campaigns)}")

        # 3. Interactive lock
        print("\n[3] Interactive Locking Test")
        print("\nEnter Campaign ID to lock (or press Enter to select first lockable, or 'exit'): ", end="")
        target_campaign_id = input().strip()
        
        if target_campaign_id.lower() == 'exit':
            return
            
        campaign_to_lock = None
        if target_campaign_id:
            # Find the campaign by ID
            for c in campaigns:
                if c.id == target_campaign_id:
                    campaign_to_lock = c
                    break
            if not campaign_to_lock:
                print(f"⚠️ Campaign with ID '{target_campaign_id}' not found in active list. Will attempt lock directly anyway.")
        elif lockable_campaigns:
            campaign_to_lock = lockable_campaigns[0]
            print(f"Selecting first lockable campaign: '{campaign_to_lock.title}' ({campaign_to_lock.id})")
        else:
            print("❌ No lockable campaigns available and no ID provided.")
            return

        cid = campaign_to_lock.id if campaign_to_lock else target_campaign_id
        title = campaign_to_lock.title if campaign_to_lock else cid
        
        print(f"❓ Confirm: Attempt to lock slot for '{title}' ({cid})? (y/n): ", end="")
        ans = input().strip().lower()
        if ans == 'y':
            print(f"⚡ Attempting API lock for '{title}'...")
            result = await strategy.lock_slot(cid)
            
            print(f"\n🔒 Lock Result Details:")
            print(f"   - Success: {result.success}")
            print(f"   - Message: {result.message}")
            print(f"   - Campaign ID: {result.campaign_id}")
            print(f"   - Campaign Title: {result.campaign_title}")
            print(f"   - Slot Number: {result.slot_number}")
            print(f"   - Strategy used: {result.strategy_used}")
            print(f"   - Response time: {result.response_time_ms:.2f} ms")
            print(f"   - Timestamp: {result.timestamp}")
            
            # Print raw dict for verification
            print("\n🔍 Result JSON Dump:")
            print(json.dumps(result.model_dump(), default=str, indent=2))
        else:
            print("Lock attempt cancelled.")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await strategy.close()


if __name__ == "__main__":
    # Ensure Windows console supports UTF-8 characters if setting is forced
    if sys.platform.startswith('win'):
        import os
        os.environ["PYTHONUTF8"] = "1"
    asyncio.run(main())
