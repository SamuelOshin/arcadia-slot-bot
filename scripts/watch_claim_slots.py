"""
Phase 0 Reconnaissance Script — watch_claim_slots.py

Polls the Arcadia campaign list every 5 seconds.
When a campaign with ugcSlotMode == "claim_slot" is detected,
immediately fetches the full detail JSON (including scheduledSlots)
and saves it to data/claim_slot_campaign_{id}.json.

This lets us observe the REAL slot schema before writing any models.

Usage:
    python scripts/watch_claim_slots.py

    # Or with uv:
    uv run python scripts/watch_claim_slots.py

Press Ctrl+C to stop.
"""
import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.session_manager import SessionManager
from app.strategies.api_strategy import APIStrategy


def log(msg: str) -> None:
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


async def main() -> None:
    session = SessionManager()
    if not session.is_valid:
        print("ERROR: No valid session found. Run scripts/setup_session.py first.")
        sys.exit(1)

    api = APIStrategy(session)
    seen: set = set()
    poll_count = 0

    log("Watching for claim_slot campaigns... (Ctrl+C to stop)")
    log(f"Saving to: {os.path.abspath('data/')}")
    print()

    while True:
        poll_count += 1
        try:
            status, data, _, _ = await api._request(
                "GET", f"{api.base_url}/clip/campaigns"
            )

            if status != 200:
                log(f"[poll #{poll_count}] Unexpected status {status} from list endpoint")
                await asyncio.sleep(5)
                continue

            # Parse campaign list
            items = data
            if isinstance(data, dict):
                items = data.get("campaigns", data.get("data", data.get("items", [])))
            if not isinstance(items, list):
                log(f"[poll #{poll_count}] Unexpected response format: {type(data)}")
                await asyncio.sleep(5)
                continue

            claim_slot_campaigns = [
                c for c in items
                if c.get("ugcSlotMode") == "claim_slot"
            ]
            all_modes = list({c.get("ugcSlotMode", "unknown") for c in items})
            log(
                f"[poll #{poll_count}] {len(items)} campaigns found. "
                f"Modes: {all_modes}. "
                f"claim_slot: {len(claim_slot_campaigns)}"
            )

            for campaign in claim_slot_campaigns:
                cid = campaign.get("_id")
                title = campaign.get("title", cid)

                if cid in seen:
                    # Already fetched — just log status
                    slots_remaining = campaign.get("slotsRemaining")
                    log(f"  [KNOWN] {title} | slotsRemaining={slots_remaining}")
                    continue

                seen.add(cid)
                log(f"  [NEW CLAIM_SLOT] {title} ({cid}) — fetching detail...")

                # Fetch full detail to capture scheduledSlots schema
                d_status, detail, d_text, _ = await api._request(
                    "GET", f"{api.base_url}/clip/campaigns/{cid}"
                )

                if d_status != 200:
                    log(f"  [ERROR] Detail fetch returned {d_status}: {d_text[:200]}")
                    continue

                # Save full JSON
                os.makedirs("data", exist_ok=True)
                out_path = f"data/claim_slot_campaign_{cid}.json"
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(detail, f, indent=2)

                scheduled_slots = detail.get("scheduledSlots", [])
                print()
                print("=" * 60)
                log(f"SAVED: {out_path}")
                log(f"  Title           : {title}")
                log(f"  Campaign ID     : {cid}")
                log(f"  ugcSlotMode     : {campaign.get('ugcSlotMode')}")
                log(f"  ugcCapacityMode : {campaign.get('ugcCapacityMode')}")
                log(f"  scheduledSlots  : {len(scheduled_slots)} items")
                log(f"  myLock          : {detail.get('myLock')}")
                log(f"  reservation     : {detail.get('campaign', {}).get('reservation')}")

                if scheduled_slots:
                    log(f"  === FIRST SLOT SCHEMA ===")
                    print(json.dumps(scheduled_slots[0], indent=4))
                    if len(scheduled_slots) > 1:
                        log(f"  === SECOND SLOT (for comparison) ===")
                        print(json.dumps(scheduled_slots[1], indent=4))
                else:
                    log("  WARNING: scheduledSlots is empty — campaign may not have started yet")
                    log("           Full detail response:")
                    print(json.dumps(detail, indent=2))

                print("=" * 60)
                print()

        except asyncio.CancelledError:
            break
        except KeyboardInterrupt:
            break
        except Exception as e:
            log(f"[poll #{poll_count}] Error: {e}")

        await asyncio.sleep(5)

    log("Stopped.")
    await api.close()


if __name__ == "__main__":
    asyncio.run(main())
