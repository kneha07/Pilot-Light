"""System prompt for the voice agent. Reuses the text agent's rules and adds the briefing."""
from pilotlight import incidents
from pilotlight.agent import SYSTEM_PROMPT

KICKOFF = "The call just connected. Give the briefing now."


def build(incident_id: str) -> str:
    rec = incidents.get(incident_id) or {}
    briefing = rec.get("briefing_text") or "No briefing recorded. Use the get_briefing tool."
    return (SYSTEM_PROMPT.format(incident_id=incident_id)
            + f"\n\nBriefing: {briefing}"
            + "\n- This is a live phone call. Keep every turn under 30 words."
            + "\n- Speech recognition may mishear \"fail mode\" as \"failover\". Treat \"failover\" as \"fail mode\"."
            + "\n- Only treat something as a request for an action if the engineer clearly asks you to do it."
              " If you are unsure what they said, ask them to repeat it."
            + "\n- When the engineer says they are done or asks to end the call, call the end_call tool, then say one"
              " short goodbye sentence such as: Thanks, the incident record is in Box. Goodbye."
              " Never call end_call before the engineer asks.")
