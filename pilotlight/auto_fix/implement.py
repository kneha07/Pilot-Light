"""Implement one auto-fix task with Claude Code and open a GitHub PR (opt-in PR mode).

Each task runs in an isolated git worktree under the system temp dir, created from
origin/main, so the live working tree that serves the demo is never touched.
Original pipeline by Harika; ported to run outside the live repo.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

from .. import box_tools, timeline
from .prompt import AGENT_PROMPT

CLAUDE_TIMEOUT_SECONDS = 600


def _run(cmd: list[str], cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)


def _find_pr_url(text: str) -> str | None:
    for line in text.splitlines():
        if "PR_URL=" in line:
            return line.split("PR_URL=", 1)[1].strip()
    urls = re.findall(r"https://github\.com/\S+/pull/\d+", text)
    return urls[0] if urls else None


def implement_task(incident_id: str, task: dict, repo_path: str, box_folder_id: str,
                   postmortem: str = "", analysis: str = "") -> str | None:
    """Implement one task in a throwaway worktree. Returns the PR URL, or None."""
    task_id, title = task["task_id"], task["title"]
    branch = f"auto-fix/{incident_id}/{task_id}".lower()
    timeline.add(incident_id, "autofix", f"Implementing {task_id}: {title} (isolated worktree, branch {branch})")

    workdir = tempfile.mkdtemp(prefix="pilotlight-autofix-")
    tree = os.path.join(workdir, "repo")
    try:
        _run(["git", "fetch", "origin", "main"], cwd=repo_path)
        _run(["git", "worktree", "add", "-B", branch, tree, "origin/main"], cwd=repo_path)
        prompt = AGENT_PROMPT.format(
            incident_id=incident_id, task_id=task_id, task_title=title, branch=branch,
            task_json=json.dumps(task, indent=2), alarm_name=task.get("alarm_name", "pilotlight-checkout-5xx"),
            service=task.get("service", "checkout-api"),
            box_folder_url=f"https://app.box.com/folder/{box_folder_id}",
            postmortem=postmortem[:6000] or "(not available)",
            past_fixes_context=analysis or "No prior analysis available.")
        cmd = ["claude", "-p", prompt]
        if os.getenv("AUTO_FIX_CLAUDE_MODEL"):
            cmd[1:1] = ["--model", os.environ["AUTO_FIX_CLAUDE_MODEL"]]
        result = subprocess.run(cmd, cwd=tree, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT_SECONDS)
        output = result.stdout + "\n" + result.stderr
        pr_url = _find_pr_url(output)
        if pr_url:
            diff = _run(["git", "diff", "origin/main...HEAD"], cwd=tree, check=False).stdout[:5000] or "(no diff)"
            box_tools.upload_text(box_folder_id, f"pr-{task_id}.md",
                                  f"# {task_id}: {title}\n\nPR: {pr_url}\n\n```diff\n{diff[:3000]}\n```\n")
            timeline.add(incident_id, "autofix", f"PR opened for {task_id}: {pr_url}")
            return pr_url
        box_tools.upload_text(box_folder_id, f"error-{task_id}.log", output[-3000:])
        timeline.add(incident_id, "autofix", f"No PR for {task_id} (Claude Code exit {result.returncode})")
        return None
    except Exception as e:
        timeline.add(incident_id, "autofix", f"Implementation failed for {task_id}: {e}")
        return None
    finally:
        _run(["git", "worktree", "remove", "--force", tree], cwd=repo_path, check=False)
        shutil.rmtree(workdir, ignore_errors=True)
