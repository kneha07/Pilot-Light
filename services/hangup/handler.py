"""Hang-up Lambda. Invoked by EventBridge when a Pilot Light Connect contact disconnects.

Copies the AI agent transcript into the timeline and closes the incident.
"""
import datetime

from pilotlight import connect, incidents, timeline

SPEAKER = {"CUSTOMER": "user", "BOT": "agent", "AGENT": "agent"}


def handler(event, context):
    contact_id = event["detail"]["contactId"]
    item = incidents.by_contact(contact_id)
    if not item:
        return {"skipped": contact_id}
    iid = item["incident_id"]

    turns = connect.transcript(contact_id)
    for t in turns:
        at = t["timestamp"]
        if isinstance(at, str):
            at = datetime.datetime.fromisoformat(at.replace("Z", "+00:00"))
        timeline.add(iid, SPEAKER.get(t["participant"], "agent"), t["text"], at=at)

    reason = event["detail"].get("disconnectReason", "unknown")
    timeline.add(iid, "call", f"Call ended ({reason}), {len(turns)} transcript turns saved")
    incidents.update(iid, status="closed",
        ended_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return {"incident_id": iid, "turns": len(turns)}
