"""Box tools: incident folder, runbook lookup, briefing, runbook Q&A, review task."""
import io

import boto3
from box_sdk_gen import (AiItemAsk, AiItemAskTypeField, CreateAiAskMode,
                         CreateFolderParent, CreateTaskAssignmentAssignTo,
                         CreateTaskAssignmentTask, CreateTaskItem,
                         CreateTaskItemTypeField, UploadFileAttributes,
                         UploadFileAttributesParentField,
                         UploadFileVersionAttributes)
from box_sdk_gen.box.errors import BoxAPIError

from . import timeline
from .box_client import client
from .config import (BOX_ENTERPRISE_ID, BOX_INCIDENTS_FOLDER_ID,
                     BOX_REVIEWER_LOGIN, BOX_RUNBOOKS_FOLDER_ID,
                     INCIDENTS_TABLE, TEXT_MODEL_ID)

ASK_PROMPT = "Answer in 2 short spoken sentences: {question}"


def _incident(incident_id: str) -> dict:
    table = boto3.resource("dynamodb").Table(INCIDENTS_TABLE)
    return table.get_item(Key={"incident_id": incident_id}).get("Item", {})


def create_incident_folder(incident_id: str) -> str:
    try:
        folder = client().folders.create_folder(
            incident_id, CreateFolderParent(id=BOX_INCIDENTS_FOLDER_ID))
    except BoxAPIError as e:
        if e.response_info.status_code != 409:
            raise
        folder_id = e.response_info.body["context_info"]["conflicts"][0]["id"]
        return str(folder_id)
    timeline.add(incident_id, "briefing", f"Created Box incident folder {folder.id}")
    return folder.id


def find_runbook(alarm_name: str) -> str | None:
    try:
        res = client().search.search_by_metadata_query(
            from_=f"enterprise_{BOX_ENTERPRISE_ID}.runbook",
            ancestor_folder_id=BOX_RUNBOOKS_FOLDER_ID,
            query="alarm_name = :a",
            query_params={"a": alarm_name},
        )
    except BoxAPIError as e:
        print(f"find_runbook failed: {e}")
        return None
    return res.entries[0].id if res.entries else None


def upload_text(folder_id: str, name: str, text: str) -> str:
    """Create a text file, or add a new version if the name already exists."""
    data = text.encode("utf-8")
    try:
        res = client().uploads.upload_file(
            UploadFileAttributes(name=name, parent=UploadFileAttributesParentField(id=folder_id)),
            io.BytesIO(data))
        return res.entries[0].id
    except BoxAPIError as e:
        if e.response_info.status_code != 409:
            raise
        file_id = e.response_info.body["context_info"]["conflicts"]["id"]
        res = client().uploads.upload_file_version(
            file_id, UploadFileVersionAttributes(name=name), io.BytesIO(data))
        return res.entries[0].id


def write_briefing(folder_id: str, incident_id: str, text: str) -> None:
    upload_text(folder_id, "briefing.md", f"# Briefing for {incident_id}\n\n{text}\n")
    timeline.add(incident_id, "briefing", "briefing.md written to Box incident folder")


def get_briefing(incident_id: str) -> str:
    """Read from the incident record, not Box, to keep the call path fast."""
    text = _incident(incident_id).get("briefing_text")
    return text or "No briefing is available for this incident yet."


def _bedrock_answer(file_id: str, question: str) -> str:
    runbook = client().downloads.download_file(file_id).read().decode("utf-8")
    prompt = f"Runbook:\n{runbook}\n\n" + ASK_PROMPT.format(question=question)
    r = boto3.client("bedrock-runtime").converse(
        modelId=TEXT_MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}])
    return r["output"]["message"]["content"][0]["text"]


def ask_runbook(incident_id: str, question: str) -> str:
    file_id = _incident(incident_id).get("runbook_file_id")
    if not file_id:
        return "I could not find a runbook for this incident."
    try:
        resp = client().ai.create_ai_ask(
            CreateAiAskMode.SINGLE_ITEM_QA,
            ASK_PROMPT.format(question=question),
            [AiItemAsk(id=file_id, type=AiItemAskTypeField.FILE)])
        answer = resp.answer
    except BoxAPIError as e:
        print(f"Box AI unavailable, falling back to Bedrock: {e}")
        try:
            answer = _bedrock_answer(file_id, question)
        except Exception as e2:  # noqa: BLE001
            print(f"Bedrock fallback failed: {e2}")
            return "I could not read the runbook right now."
    timeline.add(incident_id, "tool", f"ask_runbook: {question} -> {answer}")
    return answer


def create_review_task(file_id: str, message: str) -> None:
    task = client().tasks.create_task(
        CreateTaskItem(id=file_id, type=CreateTaskItemTypeField.FILE), message=message)
    client().task_assignments.create_task_assignment(
        CreateTaskAssignmentTask(id=task.id),
        CreateTaskAssignmentAssignTo(login=BOX_REVIEWER_LOGIN))
