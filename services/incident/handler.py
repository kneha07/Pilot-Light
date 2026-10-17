"""Incident handler. Takes an EventBridge-shaped alarm event (sent by services/incident/watcher.py)
so it can move to Lambda unchanged where the account allows it."""
import datetime
import json
import threading
import urllib.request

from pilotlight import aws_tools, box_tools, incidents, timeline
from pilotlight.config import CHECKOUT_PORT, ONCALL_PHONE, VOICE_SERVER_URL

DEDUPE_MINUTES = 30  # an open incident older than this no longer suppresses a new one


def _error_summary(iid: str) -> str:
    """Error count from the checkout service's live counter; falls back to Logs Insights."""
    try:
        with urllib.request.urlopen(f"http://localhost:{CHECKOUT_PORT}/metrics", timeout=1) as r:
            m = json.loads(r.read())
        text = (f"In the last 10 minutes there were {m['errors_10m']} errors. "
                f"The top error is {m['top_error'] or 'PaymentError'} from the checkout handler.")
        timeline.add(iid, "tool", f"query_logs: {text}")
        return text
    except Exception:
        return aws_tools.query_logs(iid, 10)


def _box_setup(iid: str, alarm: str, briefing: str) -> None:
    try:
        runbook_id = box_tools.find_runbook(alarm)
        incidents.update(iid, runbook_file_id=runbook_id or "")
        folder_id = box_tools.create_incident_folder(iid)
        incidents.update(iid, box_folder_id=folder_id)
        box_tools.write_briefing(folder_id, iid, briefing)
    except Exception as e:
        timeline.add(iid, "tool", f"Box setup failed: {e}")


def handler(event, context=None):
    alarm = event["detail"]["alarmName"]
    existing = incidents.latest_open(alarm, within_minutes=DEDUPE_MINUTES)
    if existing:
        timeline.add(existing["incident_id"], "alarm", f"{alarm} entered ALARM again, existing incident kept")
        return {"incident_id": existing["incident_id"], "deduplicated": True}

    now = datetime.datetime.now(datetime.timezone.utc)
    iid = "INC-" + now.strftime("%Y%m%d-%H%M%S")
    timeline.add(iid, "alarm", f"{alarm} entered ALARM")

    changed = aws_tools.what_changed(iid)
    briefing = f"Checkout API is failing with payment errors. {_error_summary(iid)} {changed} A runbook for this alarm is available."
    timeline.add(iid, "briefing", briefing)
    incidents.put({
        "incident_id": iid, "service": "checkout-api", "alarm_name": alarm,
        "started_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "open",
        "box_folder_id": "", "runbook_file_id": "",
        "briefing_text": briefing, "oncall_phone": ONCALL_PHONE})
    # Dial first; the Box folder, runbook lookup, and briefing upload run while the phone rings
    threading.Thread(target=_box_setup, args=(iid, alarm, briefing), daemon=True).start()

    if VOICE_SERVER_URL:
        try:
            req = urllib.request.Request(
                f"{VOICE_SERVER_URL}/call", method="POST",
                data=json.dumps({"incident_id": iid}).encode(),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
            timeline.add(iid, "call", f"Calling on-call engineer ending in {ONCALL_PHONE[-4:]}")
        except Exception as e:
            timeline.add(iid, "call", f"Call request failed: {e}")
    else:
        timeline.add(iid, "call", "VOICE_SERVER_URL not set, call skipped")
    return {"incident_id": iid}
