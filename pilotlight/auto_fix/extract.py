"""Extract actionable code tasks from an incident postmortem and transcript.

Box AI Ask (multi-item, with citations) analyzes the incident files when available,
then Bedrock Nova 2 Lite turns the material into a structured task list.
Original pipeline by Harika; ported to the CloudWatch Logs and Box stack.
"""
import json

import boto3
from box_sdk_gen.managers.ai import CreateAiAskMode
from box_sdk_gen.schemas.ai_item_ask import AiItemAsk, AiItemAskTypeField

from .. import timeline
from ..box_client import client
from ..config import AWS_REGION, TEXT_MODEL_ID

MODEL_ID = TEXT_MODEL_ID or "us.amazon.nova-2-lite-v1:0"

EXTRACT_PROMPT = """You are a senior engineer. Read this incident material and extract
concrete code tasks that would PREVENT this incident from recurring.

Rules:
- Only output tasks that require code or config changes.
- Skip process items like "update runbook" or "schedule review meeting."
- Each task must be independently implementable.
- Be specific about which files and what kind of change is needed.
- Output at most 3 tasks. Do not use em dashes.

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

ANALYSIS_PROMPT = ("Analyze this incident postmortem, call transcript, and runbook. What are the code-level "
                   "root causes? What specific permanent code fixes would prevent this incident from recurring? "
                   "Be specific about files and changes needed.")


def _download_text(file_id: str) -> str:
    stream = client().downloads.download_file(file_id)
    return stream.read().decode("utf-8", errors="replace") if stream else ""


def _box_ai_analyze(file_ids: list[str]) -> dict:
    """Box AI multi-item ask with citations. Empty analysis if Box AI is unavailable."""
    try:
        r = client().ai.create_ai_ask(
            mode=CreateAiAskMode.MULTIPLE_ITEM_QA, prompt=ANALYSIS_PROMPT,
            items=[AiItemAsk(id=fid, type=AiItemAskTypeField.FILE) for fid in file_ids],
            include_citations=True)
        citations = [{"content": c.content, "name": getattr(c, "name", "")} for c in (r.citations or [])]
        return {"answer": r.answer or "", "citations": citations}
    except Exception as e:
        print(f"[auto_fix] Box AI analysis unavailable ({type(e).__name__}), continuing without it")
        return {"answer": "", "citations": []}


def _parse_tasks(text: str) -> list[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return []
    return json.loads(text[start:end + 1]).get("tasks", [])


def _bedrock_extract(postmortem: str, transcript: str, analysis: str) -> list[dict]:
    br = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    r = br.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": EXTRACT_PROMPT.format(
            postmortem=postmortem, transcript=transcript, analysis=analysis or "(none)")}]}],
        inferenceConfig={"maxTokens": 2000, "temperature": 0.1})
    return _parse_tasks(r["output"]["message"]["content"][0]["text"])


def extract_tasks(incident_id: str, postmortem_file_id: str, transcript_file_id: str | None,
                  runbook_file_id: str | None) -> tuple[list[dict], dict]:
    """Box AI analysis, then Bedrock structured extraction. Returns (tasks, analysis)."""
    file_ids = [f for f in (postmortem_file_id, transcript_file_id, runbook_file_id) if f]
    analysis = _box_ai_analyze(file_ids)
    if analysis["answer"]:
        timeline.add(incident_id, "autofix", "Box AI analysis of postmortem, transcript, and runbook complete")
    postmortem_text = _download_text(postmortem_file_id)
    transcript_text = _download_text(transcript_file_id) if transcript_file_id else ""
    tasks = _bedrock_extract(postmortem_text, transcript_text, analysis["answer"])
    for i, t in enumerate(tasks, 1):
        t.setdefault("task_id", f"TASK-{i:03d}")
        t.setdefault("title", "Untitled task")
    return tasks, analysis
