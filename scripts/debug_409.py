#!/usr/bin/env python3
"""
Debug why lock returns 409 even when slots appear available.
Tests multiple hypotheses.
"""
import asyncio
import json
import os
import sys

# Ensure app is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.session_manager import SessionManager
from app.strategies.api_strategy import APIStrategy


async def debug():
    session = SessionManager()
    api = APIStrategy(session)
    
    print("=" * 60)
    print("        Arcadia 409 Conflict Diagnostic Tool")
    print("=" * 60)
    
    # Fetch campaign details
    print("\n[1] Fetching active campaigns...")
    campaigns = await api.list_campaigns()
    if not campaigns:
        print("❌ No campaigns found or fetch failed.")
        await api.close()
        return
        
    print("\nSummary of all campaigns:")
    print(f"{'ID':<26} | {'Title':<30} | {'Status':<7} | {'Lockable':<8} | {'Remaining':<9} | {'End Date'}")
    print("-" * 105)
    for c in campaigns:
        from datetime import datetime
        end = c.ends_at
        now = datetime.now(end.tzinfo) if (end and end.tzinfo) else datetime.utcnow()
        ended = " (Ended)" if (end and now > end) else ""
        print(f"{c.id:<26} | {c.title[:30]:<30} | {c.status:<7} | {str(c.is_lockable):<8} | {str(c.slotsRemaining):<9} | {str(end)}{ended}")
    print("=" * 105)

    # We will diagnostic the Wire UGC #1 campaign (6a184ece8c31d3845d79e5be) first, then Clasho campaign (6a26fc8012907abb71e8dcab), or campaigns[0]
    target = next((c for c in campaigns if c.id == "6a184ece8c31d3845d79e5be"), None)
    if not target:
        target = next((c for c in campaigns if c.id == "6a26fc8012907abb71e8dcab"), campaigns[0])

    
    print(f"\nTargeting Campaign: '{target.title}'")
    print(f"  ID: {target.id}")
    print(f"  Status: {target.status}")
    print(f"  Kind: {target.kind}")
    print(f"  Slots Remaining: {target.slotsRemaining}")
    print(f"  Slots Locked: {target.slotsLocked}")
    print(f"  Max Slots: {target.maxSlots}")
    print(f"  UGC Capacity Mode: {target.ugcCapacityMode}")
    print(f"  UGC Slot Mode: {target.ugcSlotMode}")
    print(f"  My Lock: {target.myLock}")
    print(f"  My Submission: {target.mySubmission}")
    print(f"  Reservation: {json.dumps(target.reservation, indent=2) if target.reservation else 'None'}")
    print(f"  CPM Rules: {json.dumps(target.cpmRules, indent=2)}")
    print("=" * 60)
    
    # Hypothesis 1: Campaign is actually closed despite status="active"
    print("\n[H1] Is endDate passed?")
    from datetime import datetime
    end = target.ends_at
    now = datetime.now(end.tzinfo) if (end and end.tzinfo) else datetime.utcnow()
    print(f"  Now (UTC): {now}")
    print(f"  End (UTC): {end}")
    if end:
        print(f"  Passed: {now > end}")
    else:
        print("  Passed: N/A")
    
    # Hypothesis 2: Reservation blocks Bronze user
    print("\n[H2] Reservation check:")
    if target.reservation:
        print(f"  Enabled: {target.reservation.get('enabled')}")
        print(f"  Reserved Eligible For Me: {target.reservation.get('reservedEligibleForMe')}")
        print(f"  General Capacity: {target.reservation.get('generalCapacity')}")
        print(f"  General Locked: {target.reservation.get('generalLocked')}")
        general_avail = target.reservation.get('generalCapacity', 0) - target.reservation.get('generalLocked', 0)
        print(f"  General Available: {general_avail}")
    else:
        print("  No reservation")
    
    # Hypothesis 3: UGC mode requires different action
    print("\n[H3] UGC Slot Mode check:")
    print(f"  Mode: {target.ugcSlotMode}")
    print(f"  Capacity Mode: {target.ugcCapacityMode}")
    if target.ugcSlotMode == "claim_slot":
        print("  ⚠️  This campaign uses CLAIM mode, not OPEN SUBMIT!")
    
    # Hypothesis 4: Try lock and capture EXACT error
    print("\n[H4] Attempting lock with full response capture...")
    # Use APIStrategy lock directly to capture the full logging we added
    result = await api.lock_slot(target.id)
    print(f"  Success: {result.success}")
    print(f"  Message: {result.message}")
    print(f"  Strategy used: {result.strategy_used}")
    print(f"  Response time: {result.response_time_ms:.1f}ms")

    await api.close()

if __name__ == "__main__":
    asyncio.run(debug())
