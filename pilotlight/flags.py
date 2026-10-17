"""The fail_mode break switch. Value lives in a local state file; every change is audited
to CloudWatch Logs, which is what what_changed reads.

CLI: python -m pilotlight.flags on|off [--by NAME]
"""
import argparse
import datetime
import getpass
import json
import os
from pathlib import Path

from . import logstore
from .config import CONFIG_AUDIT_LOG_GROUP, FAIL_MODE_PARAM, STATE_DIR

FLAG_FILE = Path(STATE_DIR) / "fail_mode"
AUDIT_FILE = Path(STATE_DIR) / "config_audit.jsonl"


def get() -> str:
    try:
        return FLAG_FILE.read_text().strip() or "off"
    except FileNotFoundError:
        return "off"


def set_(value: str, by: str) -> str:
    """Set fail_mode and write an audit record. Returns the previous value."""
    prev = get()
    FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FLAG_FILE.with_suffix(".tmp")
    tmp.write_text(value)
    os.replace(tmp, FLAG_FILE)
    record = {"parameter": FAIL_MODE_PARAM, "from": prev, "to": value, "by": by,
              "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    with open(AUDIT_FILE, "a") as f:  # local copy so the incident briefing does not wait on CloudWatch ingestion
        f.write(json.dumps(record) + "\n")
    logstore.put_json(CONFIG_AUDIT_LOG_GROUP, "fail_mode", record)
    return prev


def recent_changes(minutes: int) -> list[dict]:
    """Audit records from the local copy within the last N minutes, oldest first."""
    if not AUDIT_FILE.exists():
        return []
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes)
    out = []
    for line in AUDIT_FILE.read_text().splitlines():
        try:
            r = json.loads(line)
            if datetime.datetime.fromisoformat(r["at"]) >= cutoff:
                out.append(r)
        except (ValueError, KeyError):
            continue
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("value", choices=["on", "off"])
    ap.add_argument("--by", default=getpass.getuser())
    a = ap.parse_args()
    prev = set_(a.value, a.by)
    print(json.dumps({"fail_mode": a.value, "previous": prev, "by": a.by}))
