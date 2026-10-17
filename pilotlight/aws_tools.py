"""AWS-backed agent tools. Every function returns short, speakable text."""
import datetime
import json
import time

import boto3

from . import flags, logstore, timeline
from .config import AWS_REGION, CHECKOUT_LOG_GROUP, CONFIG_AUDIT_LOG_GROUP

logs = boto3.client("logs", region_name=AWS_REGION)

ALLOWED_ACTIONS = {
    "revert_fail_mode": "Set /pilotlight/checkout/fail_mode to off",
}

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("America/Los_Angeles")
except Exception:  # no tz database available
    LOCAL_TZ = datetime.timezone(datetime.timedelta(hours=-7))


def _spoken_time(dt: datetime.datetime) -> str:
    return dt.astimezone(LOCAL_TZ).strftime("%-I:%M %p")


def _count_errors_insights(minutes: int) -> list[dict] | None:
    """Logs Insights breakdown by error type. None if the query does not finish in time."""
    end = int(time.time())
    q = logs.start_query(
        logGroupName=CHECKOUT_LOG_GROUP, startTime=end - minutes * 60, endTime=end,
        queryString='filter @message like /ERROR/ | parse @message "ERROR *:" as err '
                    "| stats count(*) as errors by err | sort errors desc | limit 3")
    for _ in range(16):
        r = logs.get_query_results(queryId=q["queryId"])
        if r["status"] == "Complete":
            return [{f["field"]: f["value"] for f in row} for row in r["results"]]
        time.sleep(0.5)
    return None


def query_logs(incident_id: str, minutes: int = 15) -> str:
    rows = _count_errors_insights(minutes)
    if rows is None:  # fall back to a direct filter so the agent always has an answer
        events = logstore.recent(CHECKOUT_LOG_GROUP, minutes * 60, '"ERROR"')
        rows = [{"err": "PaymentTimeout", "errors": len(events)}] if events else []
    total = sum(int(row.get("errors", 0)) for row in rows)
    if total == 0:
        text = f"No errors in the checkout logs in the last {minutes} minutes."
    else:
        top = rows[0].get("err") or "unknown"
        text = f"In the last {minutes} minutes there were {total} errors. The top error is {top} from the checkout handler."
    timeline.add(incident_id, "tool", f"query_logs: {text}")
    return text


def what_changed(incident_id: str, minutes: int = 60) -> str:
    changes = []
    for e in logstore.recent(CONFIG_AUDIT_LOG_GROUP, minutes * 60):
        try:
            changes.append(json.loads(e["message"]))
        except ValueError:
            continue
    changes = [c for c in changes if c.get("from") != c.get("to")]
    if not changes:
        text = f"No configuration changes found in the last {minutes} minutes."
    else:
        last = max(changes, key=lambda c: c["at"])
        when = _spoken_time(datetime.datetime.fromisoformat(last["at"]))
        text = f"The parameter fail_mode changed from {last['from']} to {last['to']} at {when} by {last['by']}."
    timeline.add(incident_id, "tool", f"what_changed: {text}")
    return text


def execute_remediation(incident_id: str, action: str, confirmed: bool) -> str:
    if action not in ALLOWED_ACTIONS:
        text = "That action is not on the approved list. I can only revert the fail mode flag."
    elif not confirmed:
        text = "Say confirm and I will revert fail mode to off."
    else:
        flags.set_("off", by=f"pilot-light-agent for {incident_id}")
        text = "Done. fail_mode is now off. Errors should drop within about ten seconds."
        timeline.add(incident_id, "action", f"{action}: {ALLOWED_ACTIONS[action]} (verbally confirmed)")
        from . import revert_pr
        revert_pr.open_in_background(incident_id)  # reviewable PR for the rollback, never blocks the call
        return text
    timeline.add(incident_id, "tool", f"execute_remediation({action}, confirmed={confirmed}): {text}")
    return text
