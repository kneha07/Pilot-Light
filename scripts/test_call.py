#!/usr/bin/env python3
"""Place a Pilot Light call without breaking checkout. For phone testing the Connect flow and AI agent.

Creates a test incident record (status open) with a fixed briefing, then calls ONCALL_PHONE.
Usage: python scripts/test_call.py
"""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pilotlight import connect, incidents, timeline  # noqa: E402
from pilotlight.config import ONCALL_PHONE  # noqa: E402

if not connect.configured():
    sys.exit("Set CONNECT_INSTANCE_ID, CONNECT_CONTACT_FLOW_ID, ONCALL_PHONE and "
             "CONNECT_SOURCE_PHONE (or CONNECT_QUEUE_ID) in .env")

now = datetime.datetime.now(datetime.timezone.utc)
iid = "INC-" + now.strftime("%Y%m%d-%H%M%S") + "-TEST"
briefing = ("This is a test call. Checkout API is failing with payment timeouts. "
            "The fail mode flag was turned on a few minutes ago.")
incidents.put({"incident_id": iid, "service": "checkout-api", "alarm_name": "test",
    "started_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "open",
    "box_folder_id": "", "runbook_file_id": "", "briefing_text": briefing, "oncall_phone": ONCALL_PHONE})
timeline.add(iid, "briefing", briefing)
contact_id = connect.start_call(iid, briefing)
incidents.update(iid, contact_id=contact_id)
timeline.add(iid, "call", f"Test call to number ending in {ONCALL_PHONE[-4:]} (contact {contact_id})")
print(f"{iid}: calling {ONCALL_PHONE[-4:]}, contact {contact_id}")
