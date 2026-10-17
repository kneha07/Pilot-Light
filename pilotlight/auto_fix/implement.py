"""Implement a fix for a single task using Claude Code, then create a GitHub PR.

Runs Claude Code as a subprocess. Each task gets its own git branch.
"""
import json
import os
import re
import subprocess
from pathlib import Path

from .. import box_tools
from .prompt import AGENT_PROMPT


def _timeline_add(incident_id: str, type_: str, text: str) -> None:
    try:
        from .. import timeline
        timeline.add(incident_id, type_, text)
    except Exception:
        print(f"[auto_fix] [{type_}] {text}")


def _run(cmd: list[str], cwd: str = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command, capture output."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)


def _git_diff(repo_path: str) -> str:
    """Get the current git diff."""
    r = _run(["git", "diff", "HEAD~1"], cwd=repo_path, check=False)
    return r.stdout[:5000] if r.stdout else "(no diff)"


def _find_pr_url(text: str) -> str | None:
    """Extract PR URL from Claude Code output."""
    for line in text.splitlines():
        if "PR_URL=" in line:
            return line.split("PR_URL=", 1)[1].strip()
    # Fallback: look for github.com/*/pull/* URLs
    urls = re.findall(r"https://github\.com/\S+/pull/\d+", text)
    return urls[0] if urls else None


def implement_task(
    incident_id: str,
    task: dict,
    repo_path: str,
    box_folder_id: str,
    past_fixes_context: str = "",
) -> str | None:
    """Implement one task. Returns PR URL on success, None on failure."""
    task_id = task["task_id"]
    task_title = task["title"]
    branch = f"auto-fix/{incident_id}/{task_id}".lower()

    print(f"\n[auto_fix] === Implementing {task_id}: {task_title} ===")
    _timeline_add(incident_id, "autofix", f"Starting implementation: {task_id} - {task_title}")

    # 1. Create branch
    _run(["git", "checkout", "main"], cwd=repo_path, check=False)
    _run(["git", "pull", "origin", "main"], cwd=repo_path, check=False)
    _run(["git", "branch", "-D", branch], cwd=repo_path, check=False)
    _run(["git", "checkout", "-b", branch], cwd=repo_path)

    # 2. Build the prompt
    prompt = AGENT_PROMPT.format(
        incident_id=incident_id,
        task_id=task_id,
        task_title=task_title,
        task_json=json.dumps(task, indent=2),
        alarm_name=task.get("alarm_name", "pilotlight-checkout-5xx"),
        service=task.get("service", "checkout-api"),
        box_folder_url=f"https://app.box.com/folder/{box_folder_id}",
        past_fixes_context=past_fixes_context or "No past fixes found.",
    )

    # 3. Run Claude Code
    print(f"[auto_fix] Running Claude Code on branch {branch}...")
    prompt_file = Path(repo_path) / ".auto_fix_prompt.txt"
    prompt_file.write_text(prompt)

    result = subprocess.run(
        ["claude", "-p", "--model", "us.anthropic.claude-sonnet-4-6", prompt],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=600,  # 10 minute timeout
    )
    prompt_file.unlink(missing_ok=True)

    output = result.stdout + "\n" + result.stderr
    print(f"[auto_fix] Claude Code exit code: {result.returncode}")

    # 4. Find PR URL
    pr_url = _find_pr_url(output)

    if pr_url:
        print(f"[auto_fix] PR created: {pr_url}")
        _timeline_add(incident_id, "autofix", f"PR created for {task_id}: {pr_url}")

        # Upload patch and results to Box
        try:
            diff = _git_diff(repo_path)
            tasks_folder = box_tools.create_incident_folder(f"{incident_id}/patches") if False else box_folder_id
            box_tools.upload_text(box_folder_id, f"patch-{task_id}.diff", diff)
            box_tools.upload_text(box_folder_id, f"pr-{task_id}.md",
                                 f"# {task_id}: {task_title}\n\nPR: {pr_url}\n\n```diff\n{diff[:3000]}\n```")
        except Exception as e:
            print(f"[auto_fix] Box upload failed (non-fatal): {e}")

        return pr_url
    else:
        print(f"[auto_fix] No PR created for {task_id}")
        print(f"[auto_fix] Output tail: {output[-500:]}")
        _timeline_add(incident_id, "autofix", f"Implementation failed for {task_id}")

        # Upload failure log to Box
        try:
            box_tools.upload_text(box_folder_id, f"error-{task_id}.log", output[-3000:])
        except Exception:
            pass

        # Go back to main
        _run(["git", "checkout", "main"], cwd=repo_path, check=False)
        return None
