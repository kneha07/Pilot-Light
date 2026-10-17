"""System prompt for the voice agent. Reuses the text agent's rules and adds the briefing."""
from pilotlight import incidents
from pilotlight.agent import SYSTEM_PROMPT

_runbooks: dict[str, str] = {}


def _runbook_text(file_id: str) -> str:
    """Runbook text for the prompt, cached per process so later calls connect without a Box download."""
    if not file_id or file_id.startswith("stub"):
        return ""
    if file_id not in _runbooks:
        try:
            from pilotlight import box_tools
            _runbooks[file_id] = box_tools.read_runbook_text(file_id)[:2000]
        except Exception as e:
            print(f"[voice] runbook download failed: {e}")
            return ""
    return _runbooks[file_id]

KICKOFF = "The call just connected. Give the briefing now."


def build(incident_id: str) -> str:
    rec = incidents.get(incident_id) or {}
    briefing = rec.get("briefing_text") or "No briefing recorded. Use the get_briefing tool."
    return (SYSTEM_PROMPT.format(incident_id=incident_id)
            + f"\n\nBriefing: {briefing}"
            + (f"\n\nRunbook for this alarm (you may quote it without a tool call):\n{rb}" if (rb := _runbook_text(rec.get("runbook_file_id", ""))) else "")
            + "\n\nCall flow:"
            + "\n- Open with: Pilot Light here. There is an incident on checkout API. Then give the briefing in two short sentences."
            + "\n- When the engineer asks what changed, call what_changed and query_logs, then answer in three short sentences:"
              " the change with time and who made it, how many errors are active in the last 10 minutes and the top error,"
              " and what the runbook says to do. Then ask if they want you to do that."
            + "\n- This is a live phone call. Keep every turn under 30 words."
            + "\n- Speech recognition may mishear \"fail mode\" as \"failover\". Treat \"failover\" as \"fail mode\"."
            + "\n- Only treat something as a request for an action if the engineer clearly asks you to do it."
              " If you are unsure what they said, ask them to repeat it."
            + "\n- When the engineer says they are done or asks to end the call, call the end_call tool, then say one"
              " short goodbye sentence such as: Thanks, the incident record is in Box. Goodbye."
              " Never call end_call before the engineer asks.")
