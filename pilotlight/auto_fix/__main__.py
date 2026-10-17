"""Run the auto-fix pipeline for an incident.

Plan mode (default, also triggered after every postmortem): extract fix tasks from the
postmortem and transcript in Box, upload auto_fix_plan.md, and assign it for review.
PR mode (opt-in): also implement up to two tasks with Claude Code in isolated worktrees.

Usage:
    python -m pilotlight.auto_fix [INCIDENT_ID] [--pr]

Original pipeline by Harika; ported to the CloudWatch Logs and Box stack.
"""
import os
import sys

from .. import box_tools, incidents, timeline
from ..box_client import client
from .extract import _download_text, extract_tasks

MAX_PR_TASKS = 2


def _find_file(folder_id: str, name: str) -> str | None:
    for item in client().folders.get_folder_items(folder_id).entries or []:
        if item.name == name:
            return item.id
    return None


def _plan_markdown(incident_id: str, tasks: list[dict], analysis: dict) -> str:
    md = f"# Auto-fix plan: {incident_id}\n\n"
    md += "Drafted by Pilot Light from the postmortem and call transcript. Human review required.\n\n"
    if analysis.get("answer"):
        md += f"## Box AI analysis\n\n{analysis['answer'][:1500]}\n\n"
    md += f"## Tasks ({len(tasks)})\n\n"
    for t in tasks:
        md += f"### {t['task_id']}: {t['title']}\n"
        md += f"- Priority: {t.get('priority', 'TBD')}\n"
        md += f"- Type: {t.get('type', 'code_fix')}\n"
        md += f"- Description: {t.get('description', '')}\n"
        files = t.get("files_to_examine") or []
        if files:
            md += f"- Files to examine: {', '.join(files)}\n"
        md += f"- Acceptance criteria: {t.get('acceptance_criteria', 'TBD')}\n\n"
    return md


def run(incident_id: str, mode: str = "plan") -> list[str]:
    """Plan (and in PR mode, implement) fixes for an incident. Returns PR URLs (empty in plan mode)."""
    rec = incidents.get(incident_id)
    if not rec or not rec.get("box_folder_id") or rec["box_folder_id"].startswith("stub"):
        print(f"[auto_fix] {incident_id}: no incident record with a Box folder")
        return []
    folder_id = rec["box_folder_id"]
    postmortem_id = _find_file(folder_id, "postmortem.md")
    if not postmortem_id:
        print(f"[auto_fix] {incident_id}: no postmortem.md in the incident folder")
        return []
    runbook_id = rec.get("runbook_file_id") or None
    if runbook_id and runbook_id.startswith("stub"):
        runbook_id = None

    timeline.add(incident_id, "autofix", "Auto-fix analysis started")
    tasks, analysis = extract_tasks(incident_id, postmortem_id, _find_file(folder_id, "transcript.md"), runbook_id)
    if not tasks:
        timeline.add(incident_id, "autofix", "Auto-fix found no code tasks in the postmortem")
        return []

    plan_id = box_tools.upload_text(folder_id, "auto_fix_plan.md", _plan_markdown(incident_id, tasks, analysis))
    box_tools.create_review_task(plan_id, f"Review the auto-fix plan for {incident_id}")
    titles = "; ".join(t["title"] for t in tasks)
    timeline.add(incident_id, "autofix", f"Auto-fix plan ready in Box: {len(tasks)} tasks ({titles})")
    print(f"[auto_fix] {incident_id}: plan with {len(tasks)} tasks uploaded (file {plan_id})")
    if mode != "pr":
        return []

    from .implement import implement_task
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    postmortem = _download_text(postmortem_id)
    pr_urls = []
    for task in tasks[:MAX_PR_TASKS]:
        task["alarm_name"] = rec.get("alarm_name", "pilotlight-checkout-5xx")
        url = implement_task(incident_id, task, repo, folder_id, postmortem, analysis.get("answer", ""))
        if url:
            pr_urls.append(url)
    summary = f"# Auto-fix PRs: {incident_id}\n\n" + "".join(f"- {u}\n" for u in pr_urls) if pr_urls \
        else f"# Auto-fix PRs: {incident_id}\n\nNo PRs were opened. See the error-*.log files.\n"
    summary_id = box_tools.upload_text(folder_id, "pr_summary.md", summary)
    box_tools.create_review_task(summary_id, f"Review auto-fix PRs for {incident_id}")
    timeline.add(incident_id, "autofix", f"Auto-fix PR mode complete: {len(pr_urls)} PRs opened")
    return pr_urls


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--pr"]
    mode = "pr" if "--pr" in sys.argv[1:] else "plan"
    iid = args[0] if args else (incidents.latest() or {}).get("incident_id")
    if not iid:
        sys.exit("No incidents found. Pass an incident ID.")
    urls = run(iid, mode)
    for u in urls:
        print(u)


if __name__ == "__main__":
    main()
