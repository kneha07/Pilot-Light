"""Connect flow Lambda. Runs after the Connect assistant block, before the AI agent speaks.

Copies incident_id and briefing from contact attributes into the AI agent session so the
prompt can read them as {{$.Custom.incident_id}} and {{$.Custom.briefing}}.
"""
from pilotlight import connect, incidents, timeline


def handler(event, context):
    data = event["Details"]["ContactData"]
    contact_id, attrs = data["ContactId"], data.get("Attributes", {})
    iid = attrs.get("incident_id", "")
    briefing = attrs.get("briefing", "")
    if not iid:
        return {"session": "no_incident"}

    item = incidents.get(iid)
    if item and not item.get("contact_id"):
        incidents.update(iid, contact_id=contact_id)
    ok = connect.set_session_data(contact_id, {"incident_id": iid, "briefing": briefing})
    timeline.add(iid, "call", "Engineer answered, Pilot Light agent connected" if ok
                 else "Engineer answered, but no AI agent session was found on the contact")
    return {"session": "ready" if ok else "missing"}
