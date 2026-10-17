"""Alarm evaluator. Stands in for the CloudWatch alarm + EventBridge rule, which the event
account blocks. Every 2s it counts ERROR events in the checkout log group over the alarm
window and opens an incident on the OK -> ALARM transition.

Run: python -m services.incident.watcher
Force a trigger: touch .state/force_alarm (scripts/force_alarm.sh)
"""
import datetime
import json
import threading
import time
import urllib.request
from pathlib import Path

from pilotlight import logstore
from pilotlight.config import (ALARM_NAME, ALARM_THRESHOLD, ALARM_WINDOW_SECONDS,
                               CHECKOUT_LOG_GROUP, CHECKOUT_PORT, INCIDENTS_LOG_GROUP, STATE_DIR)
from services.incident.handler import handler

POLL_SECONDS = 0.5
# Logs reach filter_log_events a few seconds after they are written, so look slightly further back
INGEST_SLACK_SECONDS = 5
FORCE_FILE = Path(STATE_DIR) / "force_alarm"
STATE_FILE = Path(STATE_DIR) / "alarm_state"


def _event(reason: str) -> dict:
    return {"source": "pilotlight.watcher", "detail-type": "CloudWatch Alarm State Change",
            "detail": {"alarmName": ALARM_NAME, "state": {"value": "ALARM", "reason": reason}}}


def _fire(reason: str) -> None:
    def run():
        try:
            print(f"  incident opened: {handler(_event(reason))['incident_id']}")
        except Exception as e:
            print(f"  incident handler failed: {e}")
    threading.Thread(target=run, daemon=True).start()


def _publish(state: str) -> None:
    """Mirror the alarm state to CloudWatch Logs so the hosted dashboard can read it."""
    try:
        logstore.put_json(INCIDENTS_LOG_GROUP, "alarm-state", {
            "alarm": ALARM_NAME, "state": state,
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")})
    except Exception as e:
        print(f"  alarm state publish failed: {e}")


def _error_count(now: float) -> int:
    """Errors in the alarm window: the checkout service's live counter, else CloudWatch Logs (slower to ingest)."""
    try:
        with urllib.request.urlopen(f"http://localhost:{CHECKOUT_PORT}/metrics", timeout=1) as r:
            return int(json.loads(r.read())["errors_10s"])
    except Exception:
        return len([e for e in logstore.recent(CHECKOUT_LOG_GROUP, ALARM_WINDOW_SECONDS + INGEST_SLACK_SECONDS, '"ERROR"')
                    if e["timestamp"] >= (now - ALARM_WINDOW_SECONDS - INGEST_SLACK_SECONDS) * 1000])


def main() -> None:
    state = "OK"
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(state)
    _publish(state)
    print(f"watching {CHECKOUT_LOG_GROUP}: ALARM at >= {ALARM_THRESHOLD} errors in {ALARM_WINDOW_SECONDS}s")
    while True:
        now = time.time()
        errors = _error_count(now)
        forced = FORCE_FILE.exists()
        if forced:
            FORCE_FILE.unlink(missing_ok=True)
        new = "ALARM" if forced or errors >= ALARM_THRESHOLD else "OK"
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        if new != state:
            print(f"{stamp} {ALARM_NAME}: {state} -> {new} ({errors} errors{', forced' if forced else ''})")
            if new == "ALARM":
                _fire("forced by demo trigger" if forced else f"{errors} errors in {ALARM_WINDOW_SECONDS}s")
            state = new
            STATE_FILE.write_text(state)
            _publish(state)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
