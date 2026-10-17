"""Incident Lambda. Invoked by EventBridge when the checkout alarm enters ALARM."""
import datetime

from pilotlight import aws_tools, box_tools, connect, incidents, timeline
from pilotlight.config import ONCALL_PHONE

DEDUPE_MINUTES = 30  # an open incident older than this no longer suppresses a new one


def handler(event, context):
    alarm = event["detail"]["alarmName"]
    existing = incidents.latest_open(alarm, within_minutes=DEDUPE_MINUTES)
    if existing:
        timeline.add(existing["incident_id"], "alarm", f"{alarm} entered ALARM again, existing incident kept")
        return {"incident_id": existing["incident_id"], "deduplicated": True}

    now = datetime.datetime.now(datetime.timezone.utc)
    iid = "INC-" + now.strftime("%Y%m%d-%H%M%S")
    timeline.add(iid, "alarm", f"{alarm} entered ALARM")

    changed = aws_tools.what_changed(iid)
    errors = aws_tools.query_logs(iid, 10)
    folder_id = box_tools.create_incident_folder(iid)
    runbook_id = box_tools.find_runbook(alarm)
    briefing = f"Checkout API is failing. {errors} {changed}"
    if runbook_id:
        briefing += " A runbook for this alarm is available."
    box_tools.write_briefing(folder_id, iid, briefing)
    timeline.add(iid, "briefing", briefing)

    incidents.put({
        "incident_id": iid, "service": "checkout-api", "alarm_name": alarm,
        "started_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "open",
        "box_folder_id": folder_id, "runbook_file_id": runbook_id or "",
        "briefing_text": briefing, "oncall_phone": ONCALL_PHONE})

    if not connect.configured():
        timeline.add(iid, "call", "Amazon Connect not configured, call skipped")
        return {"incident_id": iid}
    try:
        contact_id = connect.start_call(iid, briefing)
    except Exception as e:  # the incident is already recorded; surface the failure on the timeline
        timeline.add(iid, "call", f"Outbound call failed: {e}")
        raise
    incidents.update(iid, contact_id=contact_id)
    timeline.add(iid, "call", f"Calling on-call engineer ending in {ONCALL_PHONE[-4:]} (contact {contact_id})")
    return {"incident_id": iid, "contact_id": contact_id}
