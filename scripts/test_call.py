#!/usr/bin/env python3
"""Place a real Pilot Light phone call for an existing incident, without breaking checkout.

Asks the running voice server to call ONCALL_PHONE through Twilio. The voice server and ngrok
must be up, and VOICE_SERVER_URL must be set in .env.

Usage: python scripts/test_call.py [INCIDENT_ID] --yes      (defaults to the latest incident)
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pilotlight import incidents  # noqa: E402
from pilotlight.config import ONCALL_PHONE, VOICE_SERVER_URL  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("incident_id", nargs="?")
ap.add_argument("--yes", action="store_true", help="confirm placing a real, billed phone call")
a = ap.parse_args()

if not VOICE_SERVER_URL:
    sys.exit("Set VOICE_SERVER_URL in .env and start the voice server and ngrok.")
rec = incidents.get(a.incident_id) if a.incident_id else incidents.latest()
if not rec:
    sys.exit(f"Incident not found: {a.incident_id or '(no incidents yet)'}")
iid = rec["incident_id"]

print(f"WARNING: this places a REAL phone call to the number ending in {ONCALL_PHONE[-4:]} for {iid}.")
print("It uses Twilio and Bedrock credit.")
if not a.yes:
    sys.exit("Rerun with --yes to place the call.")

req = urllib.request.Request(f"{VOICE_SERVER_URL}/call", method="POST",
                             data=json.dumps({"incident_id": iid}).encode(),
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=15) as r:
    print(f"{iid}: {r.read().decode()}")
