"""Postmortem drafting on Bedrock, written to the Box incident folder with a review task.

CLI: python -m pilotlight.postmortem INCIDENT_ID [TRANSCRIPT_FILE]
"""
import sys

import boto3

from . import box_tools, incidents, timeline
from .config import AWS_REGION, TEXT_MODEL_ID

MODEL_ID = TEXT_MODEL_ID or "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
br = boto3.client("bedrock-runtime", region_name=AWS_REGION)

PROMPT = """Write a concise incident postmortem in markdown with these sections:
Summary, Impact, Timeline (UTC), Root Cause, Resolution, Action Items (with owners as TBD).
Use only the facts below. Do not invent numbers, times, or names. Do not use em dashes.
Timeline timestamps are UTC; spoken times in the transcript and tool results are US Pacific.
Report times in UTC exactly as the timeline gives them, and do not infer a different date.

INCIDENT: {incident_id}

TIMELINE:
{timeline}

CALL TRANSCRIPT:
{transcript}"""


def generate(incident_id: str, folder_id: str, transcript: str) -> str:
    rows = timeline.list_all(incident_id)
    tl = "\n".join(f"{r['ts']} [{r['type']}] {r['text']}" for r in rows)
    r = br.converse(modelId=MODEL_ID, messages=[{"role": "user", "content": [
        {"text": PROMPT.format(incident_id=incident_id, timeline=tl, transcript=transcript)}]}],
        inferenceConfig={"maxTokens": 1500, "temperature": 0.2})
    md = r["output"]["message"]["content"][0]["text"].replace("—", ", ")
    box_tools.upload_text(folder_id, "transcript.md", transcript)
    box_tools.upload_text(folder_id, "timeline.md", tl)
    file_id = box_tools.upload_text(folder_id, "postmortem.md", md)
    box_tools.create_review_task(file_id, f"Review postmortem for {incident_id}")
    timeline.add(incident_id, "postmortem", "Postmortem drafted in Box and assigned for review")
    incidents.update(incident_id, status="resolved")

    # Kick off auto-fix pipeline in a background thread so the caller returns immediately
    import threading
    def _auto_fix():
        try:
            from .auto_fix.__main__ import run
            run(incident_id)
        except Exception as e:
            print(f"[auto_fix] Pipeline failed (non-fatal): {e}")
            timeline.add(incident_id, "autofix", f"Auto-fix pipeline error: {e}")
    threading.Thread(target=_auto_fix, daemon=True, name=f"autofix-{incident_id}").start()
    timeline.add(incident_id, "autofix", "Auto-fix pipeline triggered")

    return md


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python -m pilotlight.postmortem INCIDENT_ID [TRANSCRIPT_FILE]")
    iid = sys.argv[1]
    text = open(sys.argv[2]).read() if len(sys.argv) > 2 else "(no transcript)"
    rec = incidents.get(iid) or {}
    print(generate(iid, rec.get("box_folder_id") or box_tools.create_incident_folder(iid), text))
