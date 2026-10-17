"""Amazon Connect helpers: outbound call, AI agent session lookup, transcript, spoken confirmation."""
import re
import time

import boto3

from .config import (AWS_REGION, CONNECT_CONTACT_FLOW_ID, CONNECT_INSTANCE_ID, CONNECT_QUEUE_ID,
                     CONNECT_SOURCE_PHONE, ONCALL_PHONE)

connect = boto3.client("connect", region_name=AWS_REGION)
qconnect = boto3.client("qconnect", region_name=AWS_REGION)

CONFIRM = re.compile(r"\bconfirm(ed)?\b", re.I)
NEGATION = re.compile(r"\b(don'?t|do not|not|no|cancel|wait|stop|hold on)\b", re.I)


def configured() -> bool:
    return bool(CONNECT_INSTANCE_ID and CONNECT_CONTACT_FLOW_ID and ONCALL_PHONE
                and (CONNECT_SOURCE_PHONE or CONNECT_QUEUE_ID))


def start_call(incident_id: str, briefing: str) -> str:
    """Ring the on-call engineer. The flow reads incident_id and briefing from contact attributes."""
    kwargs = {
        "InstanceId": CONNECT_INSTANCE_ID, "ContactFlowId": CONNECT_CONTACT_FLOW_ID,
        "DestinationPhoneNumber": ONCALL_PHONE,
        "ClientToken": incident_id,  # one call per incident even if this is invoked twice
        "Name": f"Pilot Light {incident_id}",
        "Attributes": {"incident_id": incident_id, "briefing": briefing},
    }
    if CONNECT_QUEUE_ID:
        kwargs["QueueId"] = CONNECT_QUEUE_ID
    else:
        kwargs["SourcePhoneNumber"] = CONNECT_SOURCE_PHONE
    return connect.start_outbound_voice_contact(**kwargs)["ContactId"]


def session_ids(contact_id: str) -> tuple[str, str] | None:
    """(assistant_id, session_id) of the AI agent session, available once the flow's Connect assistant block runs."""
    contact = connect.describe_contact(InstanceId=CONNECT_INSTANCE_ID, ContactId=contact_id)["Contact"]
    arn = contact.get("WisdomInfo", {}).get("SessionArn")  # arn:aws:wisdom:...:session/<assistant>/<session>
    if not arn:
        return None
    assistant_id, session_id = arn.split("/")[-2:]
    return assistant_id, session_id


def set_session_data(contact_id: str, data: dict[str, str]) -> bool:
    """Expose values to the AI agent prompt as {{$.Custom.<key>}}."""
    ids = session_ids(contact_id)
    if not ids:
        return False
    qconnect.update_session_data(assistantId=ids[0], sessionId=ids[1], namespace="Custom",
        data=[{"key": k, "value": {"stringValue": v}} for k, v in data.items()])
    return True


def transcript(contact_id: str) -> list[dict]:
    """Conversation turns, oldest first: {participant: CUSTOMER|BOT|AGENT, text, timestamp}."""
    ids = session_ids(contact_id)
    if not ids:
        return []
    turns, kwargs = [], {"assistantId": ids[0], "sessionId": ids[1], "filter": "TEXT_ONLY"}
    while True:
        r = qconnect.list_messages(**kwargs)
        for m in r["messages"]:
            text = m.get("value", {}).get("text", {}).get("value")
            if text:
                turns.append({"participant": m["participant"], "text": text, "timestamp": m["timestamp"]})
        if not r.get("nextToken"):
            break
        kwargs["nextToken"] = r["nextToken"]
    return sorted(turns, key=lambda t: t["timestamp"])


def last_caller_turn(contact_id: str) -> str:
    turns = [t for t in transcript(contact_id) if t["participant"] == "CUSTOMER"]
    return turns[-1]["text"] if turns else ""


def is_confirmation(text: str) -> bool:
    return bool(CONFIRM.search(text)) and not NEGATION.search(text)


def caller_confirmed(contact_id: str, attempts: int = 3) -> tuple[bool, str]:
    """Code-level check that the engineer's latest spoken turn says "confirm".

    Retries briefly because the latest utterance can land in the session a moment after the tool call.
    """
    text = ""
    for i in range(attempts):
        text = last_caller_turn(contact_id)
        if is_confirmation(text):
            return True, text
        if i < attempts - 1:
            time.sleep(0.7)
    return False, text
