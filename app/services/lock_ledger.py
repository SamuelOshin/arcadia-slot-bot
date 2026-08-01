"""Lock ledger service for persisting and querying slot lock attempt history."""
import os
import json
from datetime import datetime
from typing import List, Optional, Dict, Any

LEDGER_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "locked_slots.json")


def get_locked_slots(account_name: Optional[str] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve lock history records with optional filters."""
    if not os.path.exists(LEDGER_FILE):
        return []
    try:
        with open(LEDGER_FILE, "r", encoding="utf-8") as f:
            records = json.load(f)
    except Exception:
        return []

    if account_name:
        records = [r for r in records if r.get("account_name") == account_name]
    if status:
        if status.upper() == "SUCCESSFUL":
            records = [r for r in records if r.get("success")]
        elif status.upper() == "FAILED":
            records = [r for r in records if not r.get("success")]
        else:
            records = [r for r in records if r.get("status") == status.upper()]

    return records


def record_lock_attempt(
    account_name: str,
    campaign_id: str,
    campaign_title: str,
    success: bool,
    slot_number: Optional[int] = None,
    slot_id: Optional[str] = None,
    payout: Optional[str] = None,
    strategy: str = "api",
    response_time_ms: float = 0.0,
    message: str = "",
) -> Dict[str, Any]:
    """Record a successful or failed lock attempt into the persistent ledger."""
    records = get_locked_slots()

    # Determine status string
    msg_lower = message.lower()
    if success:
        status = "LOCKED"
    elif "taken" in msg_lower or "collision" in msg_lower:
        status = "SLOT_TAKEN"
    elif "quota" in msg_lower:
        status = "QUOTA_EXCEEDED"
    elif "auth" in msg_lower or "401" in msg_lower:
        status = "AUTH_ERROR"
    else:
        status = "FAILED"

    record = {
        "id": f"rec-{int(datetime.utcnow().timestamp() * 1000)}-{account_name.replace(' ', '_')}",
        "account_name": account_name,
        "campaign_id": campaign_id,
        "campaign_title": campaign_title or campaign_id,
        "slot_number": slot_number,
        "slot_id": slot_id,
        "payout": payout or "Dynamic",
        "strategy": strategy or "api",
        "response_time_ms": round(response_time_ms, 2),
        "locked_at": datetime.utcnow().isoformat(),
        "success": success,
        "status": status,
        "reason": message,
    }

    records.insert(0, record)
    records = records[:500]  # Cap history at 500 records

    os.makedirs(os.path.dirname(LEDGER_FILE), exist_ok=True)
    try:
        with open(LEDGER_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)
    except Exception:
        pass

    return record


def clear_locked_slots() -> bool:
    """Clear all records from the lock ledger."""
    try:
        if os.path.exists(LEDGER_FILE):
            os.remove(LEDGER_FILE)
        return True
    except Exception:
        return False
