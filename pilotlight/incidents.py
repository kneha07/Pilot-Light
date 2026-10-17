"""Incident records (contract: contracts/incident.example.json). Stored as local JSON for fast
reads by the voice server on the same machine, and audited to CloudWatch Logs."""
import datetime
import json
from pathlib import Path

from . import logstore
from .config import INCIDENTS_LOG_GROUP, STATE_DIR

DIR = Path(STATE_DIR) / "incidents"


def put(record: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{record['incident_id']}.json").write_text(json.dumps(record, indent=2))
    logstore.put_json(INCIDENTS_LOG_GROUP, "incidents", record)


def get(incident_id: str) -> dict | None:
    p = DIR / f"{incident_id}.json"
    return json.loads(p.read_text()) if p.exists() else None


def latest() -> dict | None:
    files = sorted(DIR.glob("INC-*.json")) if DIR.exists() else []
    return json.loads(files[-1].read_text()) if files else None


def latest_open(alarm_name: str | None = None, within_minutes: int | None = None) -> dict | None:
    """Most recent open incident, optionally for one alarm and started within a window."""
    cutoff = ""
    if within_minutes:
        cutoff = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(minutes=within_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for f in sorted(DIR.glob("INC-*.json"), reverse=True) if DIR.exists() else []:
        rec = json.loads(f.read_text())
        if rec.get("status") != "open" or (alarm_name and rec.get("alarm_name") != alarm_name):
            continue
        if cutoff and rec.get("started_at", "") < cutoff:
            continue
        return rec
    return None


def update(incident_id: str, **fields) -> None:
    rec = get(incident_id)
    if rec:
        rec.update(fields)
        put(rec)
