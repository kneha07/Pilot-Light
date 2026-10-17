"""Draft the postmortem at hang-up, store it in Box, and assign a review task."""
import boto3

from . import box_tools, timeline
from .config import TEXT_MODEL_ID

PROMPT = """Write a concise incident postmortem in markdown with these sections:
Summary, Impact, Timeline (UTC), Root Cause, Resolution, Action Items (with owners as TBD).
Use only the facts below. Do not invent numbers.

TIMELINE:
{timeline}

CALL TRANSCRIPT:
{transcript}"""


def generate(incident_id: str, folder_id: str, transcript: str) -> None:
    rows = timeline.list_all(incident_id)
    tl = "\n".join(f"{r['ts']} [{r['type']}] {r['text']}" for r in rows)
    r = boto3.client("bedrock-runtime").converse(
        modelId=TEXT_MODEL_ID,
        messages=[{"role": "user", "content": [{"text": PROMPT.format(timeline=tl, transcript=transcript)}]}])
    md = r["output"]["message"]["content"][0]["text"]
    box_tools.upload_text(folder_id, "transcript.md", transcript)
    box_tools.upload_text(folder_id, "timeline.md", tl)
    file_id = box_tools.upload_text(folder_id, "postmortem.md", md)
    box_tools.create_review_task(file_id, f"Review postmortem for {incident_id}")
    timeline.add(incident_id, "postmortem", "Postmortem drafted in Box and assigned for review")
