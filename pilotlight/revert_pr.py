"""Open a reviewable GitHub pull request for every remediation Pilot Light runs.

The PR records the rollback as config-as-code (config/flags.json) plus an incident record
(incidents/<id>.md). It uses the GitHub CLI login on the demo machine and runs in a background
thread, so the voice agent never waits on it. Disable with AUTO_REVERT_PR=false.
"""
import base64
import datetime
import json
import os
import subprocess
import threading

from . import incidents, timeline

REPO = os.getenv("REVERT_PR_REPO", "kneha07/Pilot-Light")


def _gh(method: str, path: str, body: dict | None = None) -> dict:
    cmd = ["gh", "api", "-X", method, f"repos/{REPO}/{path}"]
    if body is not None:
        cmd += ["--input", "-"]
    r = subprocess.run(cmd, input=json.dumps(body) if body is not None else None,
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"gh api {method} {path} failed: {(r.stderr or r.stdout).strip()[:200]}")
    return json.loads(r.stdout or "{}")


def _put_file(branch: str, path: str, text: str, message: str) -> None:
    _gh("PUT", f"contents/{path}", {"message": message, "branch": branch,
                                    "content": base64.b64encode(text.encode()).decode()})


def _incident_record(incident_id: str, rec: dict, now: str) -> str:
    rows = timeline.list_all(incident_id)
    lines = [f"- `{r['ts']}` **{r['type']}**: {r['text']}" for r in rows]
    box = f"https://app.box.com/folder/{rec['box_folder_id']}" if rec.get("box_folder_id") else "n/a"
    return (f"# {incident_id}\n\n"
            f"- Service: {rec.get('service', 'checkout-api')}\n"
            f"- Alarm: {rec.get('alarm_name', '')}\n"
            f"- Started: {rec.get('started_at', '')}\n"
            f"- Remediation: rollback_payment_config, payment configuration rolled back at {now}\n"
            f"- Approval: verbal \"confirm\" from the on-call engineer, enforced in code\n"
            f"- Box incident folder: {box}\n\n"
            f"## Briefing\n\n{rec.get('briefing_text', '')}\n\n"
            f"## Timeline (UTC)\n\n" + "\n".join(lines) + "\n")


def open_revert_pr(incident_id: str) -> str:
    rec = incidents.get(incident_id) or {"incident_id": incident_id}
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    branch = f"pilot-light/revert-{incident_id.lower()}"
    base = _gh("GET", "git/ref/heads/main")["object"]["sha"]
    _gh("POST", "git/refs", {"ref": f"refs/heads/{branch}", "sha": base})
    flags = {"checkout-api": {"fail_mode": "off", "changed_at": now, "incident": incident_id,
                              "changed_by": "pilot-light-agent", "approved_by": "on-call engineer (voice)"}}
    _put_file(branch, "config/flags.json", json.dumps(flags, indent=2) + "\n",
              f"Roll back payment configuration for {incident_id}")
    _put_file(branch, f"incidents/{incident_id}.md", _incident_record(incident_id, rec, now),
              f"Add incident record for {incident_id}")
    box = f"https://app.box.com/folder/{rec['box_folder_id']}" if rec.get("box_folder_id") else "n/a"
    pr = _gh("POST", "pulls", {
        "title": f"Roll back payment configuration for {incident_id}", "head": branch, "base": "main",
        "body": (f"Opened by Pilot Light when the on-call engineer approved the fix by voice.\n\n"
                 f"- Action: `rollback_payment_config` (the only allowlisted action)\n"
                 f"- Approval: spoken \"confirm\", checked in code before the change ran\n"
                 f"- Incident record: `incidents/{incident_id}.md`\n"
                 f"- Box incident folder: {box}\n\n"
                 f"Review and merge to keep config in sync with production.")})
    return pr["html_url"]


def open_in_background(incident_id: str) -> None:
    if os.getenv("AUTO_REVERT_PR", "true").lower() == "false":
        return

    def run():
        try:
            url = open_revert_pr(incident_id)
            timeline.add(incident_id, "action", f"Pull request opened: {url}")
            print(f"[revert_pr] {incident_id}: {url}")
        except Exception as e:
            timeline.add(incident_id, "action", f"Pull request failed: {e}")
            print(f"[revert_pr] {incident_id}: failed: {e}")
    threading.Thread(target=run, daemon=True, name=f"revert-pr-{incident_id}").start()
