"""Agent tools Lambda. AgentCore Gateway target behind the Amazon Connect AI agent (MCP).

The event is the tool's input arguments. The tool name arrives in the client context as
"<target>___<tool>". Every tool returns {"result": <short speakable text>}.
"""
from pilotlight import connect, incidents, timeline, tools
from pilotlight.config import REQUIRE_SPOKEN_CONFIRM


def _tool_name(event, context) -> str:
    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    name = custom.get("bedrockAgentCoreToolName") or event.pop("tool", "")  # "tool" key for direct tests
    return name.split("___", 1)[-1]


def _incident(event) -> dict | None:
    """The incident this call is about. The model's incident_id is used only if it names a real record."""
    iid = str(event.get("incident_id") or "").strip()
    return (incidents.get(iid) if iid else None) or incidents.latest_open()


def _remediate(item: dict, event) -> str:
    iid, action = item["incident_id"], event.get("action", "")
    confirmed = bool(event.get("confirmed"))
    if confirmed and REQUIRE_SPOKEN_CONFIRM:
        contact_id = item.get("contact_id")
        heard = ""
        try:
            ok, heard = connect.caller_confirmed(contact_id) if contact_id else (False, "")
        except Exception as e:  # fail closed: no transcript, no fix
            ok, heard = False, f"transcript unavailable ({e.__class__.__name__})"
        if not ok:
            timeline.add(iid, "tool", f"execute_remediation blocked: latest caller turn was not a confirmation: {heard!r}")
            confirmed = False
    return tools.execute_remediation(iid, action, confirmed)


def handler(event, context):
    event = dict(event or {})
    name = _tool_name(event, context)
    item = _incident(event)
    if not item:
        return {"result": "There is no open incident right now."}
    iid = item["incident_id"]

    if name == "get_briefing":
        text = tools.get_briefing(iid)
    elif name == "query_logs":
        text = tools.query_logs(iid, int(event.get("minutes") or 15))
    elif name == "what_changed":
        text = tools.what_changed(iid, int(event.get("minutes") or 60))
    elif name == "ask_runbook":
        text = tools.ask_runbook(iid, str(event.get("question", "")))
    elif name == "execute_remediation":
        text = _remediate(item, event)
    else:
        text = f"Unknown tool {name}."
    return {"result": text}
