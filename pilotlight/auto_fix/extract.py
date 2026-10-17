"""Extract actionable code tasks from incident postmortem and transcript.

Uses Box AI Ask (multi-item with citations) for analysis, then Bedrock
Nova 2 Lite for structured task extraction.
"""
import json

import boto3
from box_sdk_gen.managers.ai import CreateAiAskMode
from box_sdk_gen.schemas.ai_item_ask import AiItemAsk, AiItemAskTypeField

from ..box_client import client
from ..config import AWS_REGION, BOX_ENTERPRISE_ID, BOX_INCIDENTS_FOLDER_ID, TEXT_MODEL_ID


def _timeline_add(incident_id: str, type_: str, text: str) -> None:
    try:
        from .. import timeline
        timeline.add(incident_id, type_, text)
    except Exception:
        print(f"[auto_fix] [{type_}] {text}")

MODEL_ID = TEXT_MODEL_ID or "amazon.nova-2-lite-v1:0"
br = boto3.client("bedrock-runtime", region_name=AWS_REGION)

EXTRACT_PROMPT = """You are a senior engineer. Read this incident analysis and extract
concrete code tasks that would PREVENT this incident from recurring.

Rules:
- Only output tasks that require code or config changes.
- Skip process items like "update runbook" or "schedule review meeting."
- Each task must be independently implementable.
- Be specific about which files and what kind of change is needed.

Output valid JSON only, no markdown fences:
{{"tasks": [
    {{"task_id": "TASK-001",
      "title": "short imperative description",
      "type": "code_fix",
      "description": "detailed description of what to change and why",
      "files_to_examine": ["best guess at files"],
      "acceptance_criteria": "how to verify the fix works",
      "priority": "P1",
      "root_cause_link": "which part of the root cause this addresses"}}
]}}

POSTMORTEM:
{postmortem}

TRANSCRIPT:
{transcript}

AI ANALYSIS:
{analysis}"""


def _box_ai_analyze(file_ids: list[str], prompt: str) -> dict:
    """Box AI Ask in multi-item mode with citations."""
    items = [AiItemAsk(id=fid, type=AiItemAskTypeField.FILE) for fid in file_ids]
    try:
        r = client().ai.create_ai_ask(
            mode=CreateAiAskMode.MULTIPLE_ITEM_QA,
            prompt=prompt,
            items=items,
            include_citations=True,
        )
        citations = []
        if hasattr(r, "citations") and r.citations:
            citations = [{"content": c.content, "name": getattr(c, "name", "")}
                         for c in r.citations]
        return {"answer": r.answer, "citations": citations}
    except Exception as e:
        print(f"[auto_fix] Box AI Ask failed: {e}")
        return {"answer": "", "citations": []}


def _find_past_incidents(alarm_name: str) -> list[str]:
    """Find postmortem file IDs from past incidents with the same alarm."""
    try:
        r = client().search.search_by_metadata_query(
            f"enterprise_{BOX_ENTERPRISE_ID}.incident",
            BOX_INCIDENTS_FOLDER_ID,
            query="alarm_name = :a",
            query_params={"a": alarm_name},
            limit=3,
        )
        past_ids = []
        for entry in r.entries or []:
            items = client().folders.get_folder_items(entry.id)
            for item in items.entries or []:
                if item.name == "postmortem.md":
                    past_ids.append(item.id)
        return past_ids
    except Exception as e:
        print(f"[auto_fix] Past incident search failed: {e}")
        return []


def _bedrock_extract(postmortem: str, transcript: str, analysis: str) -> list[dict]:
    """Use Bedrock Nova 2 Lite to extract structured tasks."""
    prompt = EXTRACT_PROMPT.format(
        postmortem=postmortem, transcript=transcript, analysis=analysis
    )
    r = br.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 2000, "temperature": 0.1},
    )
    text = r["output"]["message"]["content"][0]["text"].strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()
    parsed = json.loads(text)
    return parsed.get("tasks", [])


def extract_tasks(
    incident_id: str,
    postmortem_file_id: str,
    transcript_file_id: str | None,
    runbook_file_id: str | None,
    alarm_name: str,
) -> tuple[list[dict], dict]:
    """Full extraction pipeline: Box AI analysis then Bedrock structured extraction.

    Returns (tasks, analysis_result).
    """
    print(f"[auto_fix] Analyzing incident {incident_id}...")

    # 1. Gather file IDs for Box AI multi-item ask
    file_ids = [postmortem_file_id]
    if transcript_file_id:
        file_ids.append(transcript_file_id)
    if runbook_file_id:
        file_ids.append(runbook_file_id)

    # 2. Find past incidents for cross-incident learning
    past_ids = _find_past_incidents(alarm_name)
    if past_ids:
        file_ids.extend(past_ids[:3])
        print(f"[auto_fix] Found {len(past_ids)} past postmortems for {alarm_name}")

    # 3. Box AI Ask with citations
    analysis = _box_ai_analyze(
        file_ids,
        "Analyze this incident postmortem and runbook. What are the code-level root "
        "causes? What specific permanent code fixes would prevent this incident from "
        "recurring? Be specific about files and changes needed.",
    )
    _timeline_add(incident_id, "autofix", "Box AI analysis complete")
    if analysis["citations"]:
        cite_summary = "; ".join(c.get("name", "?") for c in analysis["citations"][:3])
        print(f"[auto_fix] Citations from: {cite_summary}")

    # 4. Download postmortem and transcript text for Bedrock
    postmortem_text = client().downloads.download_file(postmortem_file_id).read().decode("utf-8", errors="replace")
    transcript_text = ""
    if transcript_file_id:
        transcript_text = client().downloads.download_file(transcript_file_id).read().decode("utf-8", errors="replace")

    # 5. Bedrock structured extraction
    tasks = _bedrock_extract(postmortem_text, transcript_text, analysis["answer"])
    _timeline_add(incident_id, "autofix", f"Extracted {len(tasks)} tasks from postmortem")
    print(f"[auto_fix] Extracted {len(tasks)} tasks")

    return tasks, analysis
