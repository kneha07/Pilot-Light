"""Operator dashboard: login, live status, incidents with timelines, and console links.
Reads the same local state and CloudWatch Logs groups as the rest of the system; it never
changes anything, so it is safe to leave open on the projector. Without local state (hosted on
Vercel) it reads incidents, the flag, and the alarm state from CloudWatch Logs instead.

Run: uvicorn dashboard.app:app --port 8001   then open http://localhost:8001
"""
import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import os
import re
import threading
import time
import urllib.request
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse

from pilotlight import flags, incidents, logstore, timeline
from pilotlight.config import (ALARM_NAME, ALARM_THRESHOLD, ALARM_WINDOW_SECONDS, AWS_REGION,
                               BOX_INCIDENTS_FOLDER_ID, BOX_RUNBOOKS_FOLDER_ID, CHECKOUT_LOG_GROUP,
                               CONFIG_AUDIT_LOG_GROUP, DASHBOARD_PASSWORD, DASHBOARD_SECRET,
                               DASHBOARD_USER, INCIDENTS_LOG_GROUP, SONIC_REGION, STATE_DIR,
                               TIMELINE_LOG_GROUP, VOICE_SERVER_URL)

STATIC = Path(__file__).parent / "static"
COOKIE = "pl_session"
SESSION_SECONDS = 12 * 3600
CACHE_SECONDS = 2
LOGIN_MAX_FAILURES, LOGIN_WINDOW_SECONDS = 10, 300
# Without DASHBOARD_SECRET, sessions last until the process restarts; hosted deploys must set it
if not DASHBOARD_SECRET:
    print("[dashboard] WARNING: DASHBOARD_SECRET not set, using a per-process secret (local use only)")
_secret = (DASHBOARD_SECRET or secrets.token_hex(32)).encode()
_failures: dict[str, deque] = defaultdict(deque)

app = FastAPI(title="Pilot Light dashboard", docs_url=None, redoc_url=None, openapi_url=None)


def _sign(payload: str) -> str:
    return hmac.new(_secret, payload.encode(), hashlib.sha256).hexdigest()


def _make_token(user: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"u": user, "exp": int(time.time()) + SESSION_SECONDS}).encode()).decode()
    return f"{payload}.{_sign(payload)}"


def current_user(request: Request) -> str:
    token = request.cookies.get(COOKIE, "")
    payload, _, sig = token.partition(".")
    if not payload or not hmac.compare_digest(sig, _sign(payload)):
        raise HTTPException(status_code=401, detail="not signed in")
    try:
        data = json.loads(base64.urlsafe_b64decode(payload))
        user, exp = str(data["u"]), float(data["exp"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=401, detail="not signed in")
    if exp < time.time():
        raise HTTPException(status_code=401, detail="session expired")
    return user


def _client_ip(request: Request) -> str:
    # Vercel sets x-real-ip itself; the first x-forwarded-for entry is client-controlled
    real = request.headers.get("x-real-ip", "").strip()
    fwd = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
    return real or fwd or (request.client.host if request.client else "unknown")


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/login")
async def login(body: dict, request: Request, response: Response):
    if not DASHBOARD_PASSWORD:
        raise HTTPException(status_code=503, detail="dashboard login not configured")
    ip, now = _client_ip(request), time.time()
    fails = _failures[ip]
    while fails and now - fails[0] > LOGIN_WINDOW_SECONDS:
        fails.popleft()
    if len(fails) >= LOGIN_MAX_FAILURES:
        raise HTTPException(status_code=429, detail="too many failed sign-ins, try again in a few minutes")
    ok_user = hmac.compare_digest(str(body.get("username", "")).encode(), DASHBOARD_USER.encode())
    ok_pass = hmac.compare_digest(str(body.get("password", "")).encode(), DASHBOARD_PASSWORD.encode())
    if not (ok_user and ok_pass):
        fails.append(now)
        raise HTTPException(status_code=401, detail="invalid username or password")
    fails.clear()
    response.set_cookie(COOKIE, _make_token(DASHBOARD_USER), max_age=SESSION_SECONDS, httponly=True,
                        samesite="strict", secure=_is_https(request))
    return {"user": DASHBOARD_USER}


@app.post("/api/incidents/{incident_id}/review")
async def send_for_review(incident_id: str, user: str = Depends(current_user)):
    """Hand the incident to reviewers and clear it from the Live view (runs on the demo laptop)."""
    if not re.fullmatch(r"INC-\d{8}-\d{6}", incident_id):
        raise HTTPException(status_code=404, detail="unknown incident")
    return _forward_to_laptop(f"review?incident_id={incident_id}")


@app.post("/api/demo/{action}")
async def demo_action(action: str, user: str = Depends(current_user)):
    """Break or reset the demo service on the demo laptop through the voice server."""
    if action not in ("break", "reset"):
        raise HTTPException(status_code=404, detail="unknown action")
    return _forward_to_laptop(action)


def _forward_to_laptop(path: str) -> dict:
    token = os.getenv("DEMO_TRIGGER_TOKEN", "")
    if not (VOICE_SERVER_URL and token):
        raise HTTPException(status_code=503, detail="demo trigger not configured")
    req = urllib.request.Request(f"{VOICE_SERVER_URL}/demo/{path}", method="POST", data=b"{}",
                                 headers={"Content-Type": "application/json", "x-demo-token": token})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read() or b"{}")
    except Exception as e:
        print(f"[dashboard] demo {path} failed: {e}")
        raise HTTPException(status_code=502, detail="demo laptop not reachable; is the voice server and ngrok running?")


@app.post("/api/logout")
async def logout(request: Request, response: Response):
    response.delete_cookie(COOKIE, httponly=True, samesite="strict", secure=_is_https(request))
    return {"ok": True}


@app.get("/api/me")
async def me(user: str = Depends(current_user)):
    return {"user": user}


_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()


def _cached(key: str, fn):
    """In-process cache so a polling dashboard does not hammer CloudWatch."""
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    value = fn()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def _local_incidents() -> list[dict]:
    if not incidents.DIR.exists():
        return []
    return [json.loads(p.read_text()) for p in sorted(incidents.DIR.glob("INC-*.json"), reverse=True)]


def _cloudwatch_incidents() -> list[dict]:
    """Latest record per incident from the audit stream that incidents.put writes on every change."""
    latest: dict[str, dict] = {}
    for e in logstore.newest(INCIDENTS_LOG_GROUP, "incidents", 2000):  # newest page only; records repeat on every update
        try:
            rec = json.loads(e["message"])
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("incident_id"):
            latest[rec["incident_id"]] = rec
    return [latest[k] for k in sorted(latest, reverse=True)]


def _source() -> str:
    return "local" if _local_incidents() else "cloudwatch"


def _all_incidents() -> list[dict]:
    local = _local_incidents()
    if local:
        return local
    return _cached("incidents", lambda: _safe(_cloudwatch_incidents, []))


def _get_incident(incident_id: str) -> dict | None:
    return incidents.get(incident_id) or next((i for i in _all_incidents() if i["incident_id"] == incident_id), None)


def _latest_json(group: str, stream: str) -> dict | None:
    for e in reversed(logstore.newest(group, stream, 5)):
        try:
            return json.loads(e["message"])
        except ValueError:
            continue
    return None


def _alarm_state() -> str:
    p = Path(STATE_DIR) / "alarm_state"
    if p.exists():
        return p.read_text().strip()
    rec = _cached("alarm", lambda: _safe(lambda: _latest_json(INCIDENTS_LOG_GROUP, "alarm-state"), None))
    return (rec or {}).get("state", "UNKNOWN")


def _fail_mode() -> str:
    if flags.FLAG_FILE.exists():
        return flags.get()
    rec = _cached("fail_mode", lambda: _safe(lambda: _latest_json(CONFIG_AUDIT_LOG_GROUP, "fail_mode"), None))
    return (rec or {}).get("to", "off")


def _status_payload() -> dict:
    with ThreadPoolExecutor(max_workers=3) as pool:
        inc_f, flag_f, alarm_f = pool.submit(_all_incidents), pool.submit(_fail_mode), pool.submit(_alarm_state)
        all_inc, fail_mode, alarm_state = inc_f.result(), flag_f.result(), alarm_f.result()
    return {
        "fail_mode": fail_mode, "alarm_name": ALARM_NAME, "alarm_state": alarm_state,
        "alarm_rule": f">= {ALARM_THRESHOLD} errors in {ALARM_WINDOW_SECONDS}s",
        "incidents_total": len(all_inc),
        "incidents_open": sum(1 for i in all_inc if i.get("status") == "open"),
        "latest": all_inc[0] if all_inc else None,
        "voice_server": bool(VOICE_SERVER_URL),
        "source": _source(),
    }


@app.get("/api/status")
async def status(user: str = Depends(current_user)):
    return await asyncio.to_thread(_status_payload)


@app.get("/api/incidents")
async def list_incidents(user: str = Depends(current_user)):
    return _all_incidents()


def _detail_payload(incident_id: str) -> dict | None:
    rec = _get_incident(incident_id)
    if not rec:
        return None
    return {"incident": rec, "timeline": _safe(lambda: timeline.list_all(incident_id), []),
            "links": {"timeline_logs": _log_stream_url(TIMELINE_LOG_GROUP, incident_id),
                      "box_folder": f"https://app.box.com/folder/{rec['box_folder_id']}" if rec.get("box_folder_id") else ""}}


@app.get("/api/incidents/{incident_id}")
async def incident_detail(incident_id: str, user: str = Depends(current_user)):
    d = await asyncio.to_thread(_detail_payload, incident_id)
    if not d:
        raise HTTPException(status_code=404, detail="incident not found")
    return d


@app.get("/api/events")
async def events(minutes: int = 15, user: str = Depends(current_user)):
    return await asyncio.to_thread(_events_payload, minutes)


@app.get("/api/live")
async def live(user: str = Depends(current_user)):
    """Everything the Live view needs in one round trip, with the CloudWatch reads run in parallel."""
    status_t = asyncio.to_thread(_status_payload)
    events_t = asyncio.to_thread(_events_payload, 5)
    s, ev = await asyncio.gather(status_t, events_t)
    latest = s.get("latest") or {}
    detail = None
    if latest.get("incident_id") and latest.get("status") != "in_review":
        detail = await asyncio.to_thread(_detail_payload, latest["incident_id"])
    return {"status": s, "events": ev, "detail": detail}


def _events_payload(minutes: int) -> dict:
    """Checkout errors bucketed by time, plus a merged feed of errors and config changes."""
    minutes = max(1, min(minutes, 60))
    now_ms = int(time.time() * 1000)
    errors = _cached(f"errors:{minutes}", lambda: _safe(lambda: logstore.recent(CHECKOUT_LOG_GROUP, minutes * 60, '"ERROR"'), None))
    changes = _cached("changes", lambda: _safe(lambda: logstore.recent(CONFIG_AUDIT_LOG_GROUP, 24 * 3600), []))
    connected = errors is not None
    errors = errors or []
    bucket_s = 5 if minutes <= 5 else 15 if minutes <= 15 else 30
    bucket_ms, n = bucket_s * 1000, minutes * 60 // bucket_s
    buckets = [0] * n
    for e in errors:
        i = n - 1 - (now_ms - e["timestamp"]) // bucket_ms
        if 0 <= i < n:
            buckets[i] += 1
    feed = [{"ts": e["timestamp"], "kind": "error", "text": e["message"]} for e in errors[-50:]]
    feed += [{"ts": e["timestamp"], "kind": "config", "text": _config_text(e["message"])} for e in changes[-50:]]
    feed.sort(key=lambda r: r["ts"], reverse=True)
    return {"bucket_seconds": bucket_ms // 1000, "error_buckets": buckets, "errors_total": len(errors),
            "feed": feed[:60], "aws_connected": connected}


def _safe(fn, default):
    """Hosted without AWS credentials (for example on Vercel), CloudWatch reads return empty data."""
    try:
        return fn()
    except Exception as e:
        print(f"[dashboard] CloudWatch read failed: {e}")
        return default


def _config_text(message: str) -> str:
    try:
        r = json.loads(message)
        return f"Payment configuration {'changed' if r['to'] == 'on' else 'rolled back'} by {r['by']}"
    except (ValueError, KeyError):
        return message


def _console(region: str, fragment: str) -> str:
    return f"https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#{fragment}"


def _enc(s: str) -> str:
    # The CloudWatch console double-encodes path segments in the hash, with $ standing in for %
    return quote(quote(s, safe=""), safe="").replace("%", "$")


def _log_group_url(group: str) -> str:
    return _console(AWS_REGION, f"logsV2:log-groups/log-group/{_enc(group)}")


def _log_stream_url(group: str, stream: str) -> str:
    return _console(AWS_REGION, f"logsV2:log-groups/log-group/{_enc(group)}/log-events/{_enc(stream)}")


@app.get("/api/links")
async def links(user: str = Depends(current_user)):
    r = AWS_REGION
    groups = [(CHECKOUT_LOG_GROUP, "Checkout service logs"), (CONFIG_AUDIT_LOG_GROUP, "Config audit (what changed)"),
              (TIMELINE_LOG_GROUP, "Incident timelines"), (INCIDENTS_LOG_GROUP, "Incident records")]
    sections = [
        {"title": "CloudWatch Logs", "links": [{"label": label, "detail": g, "url": _log_group_url(g)} for g, label in groups] + [
            {"label": "Live Tail", "detail": "Stream checkout logs in real time", "url": _console(r, "logsV2:live-tail")},
            {"label": "Logs Insights", "detail": "Query across log groups", "url": _console(r, "logsV2:logs-insights")},
        ]},
        {"title": "Audit and models", "links": [
            {"label": "CloudTrail event history", "detail": "Who did what in the account",
             "url": f"https://{r}.console.aws.amazon.com/cloudtrailv2/home?region={r}#/events"},
            {"label": "Bedrock (Nova 2 Lite)", "detail": r, "url": f"https://{r}.console.aws.amazon.com/bedrock/home?region={r}#/"},
            {"label": "Bedrock (Nova 2 Sonic)", "detail": SONIC_REGION,
             "url": f"https://{SONIC_REGION}.console.aws.amazon.com/bedrock/home?region={SONIC_REGION}#/"},
        ]},
        {"title": "Box", "links": [
            {"label": "Incidents folder", "detail": "Briefings, transcripts, postmortems",
             "url": f"https://app.box.com/folder/{BOX_INCIDENTS_FOLDER_ID}" if BOX_INCIDENTS_FOLDER_ID else ""},
            {"label": "Runbooks folder", "detail": "Runbooks found by metadata",
             "url": f"https://app.box.com/folder/{BOX_RUNBOOKS_FOLDER_ID}" if BOX_RUNBOOKS_FOLDER_ID else ""},
            {"label": "My tasks", "detail": "Postmortem review tasks", "url": "https://app.box.com/tasks"},
        ]},
        {"title": "Telephony", "links": [
            {"label": "Twilio call logs", "detail": "Every on-call call", "url": "https://console.twilio.com/us1/monitor/logs/calls"},
            {"label": "Voice server health", "detail": VOICE_SERVER_URL or "VOICE_SERVER_URL not set",
             "url": f"{VOICE_SERVER_URL}/health" if VOICE_SERVER_URL else ""},
        ]},
    ]
    return {"sections": sections}
