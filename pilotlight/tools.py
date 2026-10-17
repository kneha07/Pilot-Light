"""Shared tool contract for Pilot Light.

Persons 1 and 3 replace the stub bodies with real implementations.
Person 2 (voice agent) calls these. Every function returns short, speakable text.
Keep the signatures unchanged.
"""
from . import aws_tools, incidents, timeline


def query_logs(incident_id: str, minutes: int = 15) -> str:
    """Summarize recent error logs for the incident's service. (P1)"""
    return aws_tools.query_logs(incident_id, minutes)


def what_changed(incident_id: str, minutes: int = 60) -> str:
    """Recent SSM parameter changes. (P1)"""
    return aws_tools.what_changed(incident_id, minutes)


def ask_runbook(incident_id: str, question: str) -> str:
    """Box AI Q&A over the incident's runbook. (P3) STUB"""
    return "The runbook says: if fail_mode is on, revert it to off, then confirm the error rate drops within two minutes."


def get_briefing(incident_id: str) -> str:
    """Spoken opening briefing for the on-call engineer, as written by the Incident Lambda."""
    item = incidents.get(incident_id)
    return item["briefing_text"] if item else "I could not find a briefing for that incident."


def execute_remediation(incident_id: str, action: str, confirmed: bool) -> str:
    """Run an allowlisted SSM revert. Must refuse unless confirmed is True. (P1)"""
    return aws_tools.execute_remediation(incident_id, action, confirmed)


def log_to_incident(incident_id: str, event_type: str, text: str) -> None:
    """Write to the DynamoDB timeline.

    event_type is one of: alarm, briefing, call, user, agent, tool, action, postmortem.
    """
    timeline.add(incident_id, event_type, text)


def page_teammate(incident_id: str, message: str) -> str:
    """Page a second responder. First on the cut list. (P1) STUB"""
    return "I've paged a teammate."
