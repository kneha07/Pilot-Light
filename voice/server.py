"""Voice server: places the on-call call through Twilio and bridges the Media Stream to Nova 2 Sonic.

Run: uvicorn voice.server:app --port 8000   (expose with ngrok, set VOICE_SERVER_URL)
"""
import asyncio
import audioop
import base64
import hmac
import json
import os
from urllib.parse import urlencode
from xml.sax.saxutils import quoteattr

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from pilotlight import flags, incidents, postmortem, timeline
from pilotlight.config import (ONCALL_PHONE, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
                               TWILIO_FROM_NUMBER, VOICE_SERVER_URL)

from .audio import Converter
from .sonic import SonicSession

FRAME = 160  # 20ms of 8 kHz mu-law
ECHO_TAIL_SECONDS = 0.4    # keep the caller muted this long after the agent's audio finishes playing
NOISE_GATE_RMS = 250       # caller frames quieter than this are sent as silence (room noise, line hiss)
GATE_HOLD_SECONDS = 0.5    # keep the gate open after speech so word endings are not clipped
SILENT_FRAME = b"\xff" * FRAME

app = FastAPI(title="Pilot Light voice server")


@app.post("/demo/{action}")
async def demo(action: str, request: Request):
    """Demo trigger for the dashboard's Break something button. Requires DEMO_TRIGGER_TOKEN; touches only fail_mode."""
    token = os.getenv("DEMO_TRIGGER_TOKEN", "")
    if not token or not hmac.compare_digest(request.headers.get("x-demo-token", ""), token):
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    if action not in ("break", "reset"):
        return JSONResponse(status_code=404, content={"error": "unknown action"})
    value = "on" if action == "break" else "off"
    previous = await asyncio.to_thread(flags.set_, value, "dashboard operator")
    return {"fail_mode": value, "previous": previous}


@app.get("/health")
async def health():
    return {"ok": True, "twilio_configured": bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN)}


@app.post("/call")
async def call(body: dict):
    iid = body["incident_id"]
    missing = [k for k, v in {"TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID, "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
                              "TWILIO_FROM_NUMBER": TWILIO_FROM_NUMBER, "ONCALL_PHONE": ONCALL_PHONE,
                              "VOICE_SERVER_URL": VOICE_SERVER_URL}.items() if not v]
    if missing:
        return JSONResponse(status_code=503, content={"error": f"Twilio not configured, missing: {', '.join(missing)}"})
    from twilio.rest import Client
    # Twilio fetches the TwiML from /twiml; trial accounts reject inline twiml on calls.create
    c = await asyncio.to_thread(Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN).calls.create,
                                to=ONCALL_PHONE, from_=TWILIO_FROM_NUMBER,
                                url=f"{VOICE_SERVER_URL}/twiml?{urlencode({'incident_id': iid})}")
    return {"call_sid": c.sid}


@app.api_route("/twiml", methods=["GET", "POST"])
async def twiml(incident_id: str):
    ws_url = VOICE_SERVER_URL.replace("https://", "wss://") + "/media"
    xml = (f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Connect><Stream url={quoteattr(ws_url)}>"
           f"<Parameter name=\"incident_id\" value={quoteattr(incident_id)}/></Stream></Connect></Response>")
    return Response(content=xml, media_type="application/xml")


@app.websocket("/media")
async def media(ws: WebSocket):
    await ws.accept()
    conv, session, stream_sid, iid, call_sid = Converter(), None, None, None, None
    hangup_sent = False

    loop = asyncio.get_running_loop()
    audio = {"playing_until": 0.0, "gate_open_until": 0.0}

    def caller_frame(ulaw: bytes) -> bytes:
        """Echo guard and noise gate: the agent never hears itself on speakerphone, and quiet noise is dropped."""
        now = loop.time()
        if now < audio["playing_until"] + ECHO_TAIL_SECONDS:
            return SILENT_FRAME
        if audioop.rms(audioop.ulaw2lin(ulaw, 2), 2) >= NOISE_GATE_RMS:
            audio["gate_open_until"] = now + GATE_HOLD_SECONDS
        return ulaw if now < audio["gate_open_until"] else SILENT_FRAME

    async def to_twilio(pcm: bytes) -> None:
        ulaw = conv.sonic_to_twilio(pcm)
        # Twilio plays audio in real time from when it arrives; track when this chunk finishes playing
        audio["playing_until"] = max(audio["playing_until"], loop.time()) + len(ulaw) / 8000
        for i in range(0, len(ulaw), FRAME):
            await ws.send_text(json.dumps({"event": "media", "streamSid": stream_sid,
                                           "media": {"payload": base64.b64encode(ulaw[i:i + FRAME]).decode()}}))

    async def barge_in() -> None:
        await ws.send_text(json.dumps({"event": "clear", "streamSid": stream_sid}))

    async def hang_up() -> None:
        # Twilio echoes the mark once the goodbye audio before it has played; hang up then (or after a timeout)
        await ws.send_text(json.dumps({"event": "mark", "streamSid": stream_sid, "mark": {"name": "goodbye"}}))
        asyncio.get_running_loop().call_later(10, lambda: asyncio.ensure_future(complete_call()))

    async def complete_call() -> None:
        nonlocal hangup_sent
        if hangup_sent or not call_sid:
            return
        hangup_sent = True
        from twilio.rest import Client
        try:
            await asyncio.to_thread(lambda: Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN).calls(call_sid).update(status="completed"))
        except Exception as e:
            print(f"[voice] hang-up failed: {e}")

    try:
        while True:
            msg = json.loads(await ws.receive_text())
            event = msg.get("event")
            if event == "start":
                stream_sid, call_sid = msg["start"]["streamSid"], msg["start"].get("callSid")
                iid = msg["start"].get("customParameters", {}).get("incident_id") or (incidents.latest() or {}).get("incident_id")
                print(f"[voice] call started for {iid}")
                session = SonicSession(iid, to_twilio, barge_in, hang_up)
                await session.start()
            elif event == "media" and session:
                frame = caller_frame(base64.b64decode(msg["media"]["payload"]))
                await session.send_audio(conv.twilio_to_sonic(frame))
            elif event == "mark" and msg.get("mark", {}).get("name") == "goodbye":
                await complete_call()
            elif event == "stop":
                break
    except WebSocketDisconnect:
        pass
    finally:
        if session:
            await session.close()
            await asyncio.to_thread(_finish, iid, list(session.transcript))


def _finish(iid: str, transcript: list[str]) -> None:
    timeline.add(iid, "call", "Call ended")
    folder_id = (incidents.get(iid) or {}).get("box_folder_id", "")
    try:
        postmortem.generate(iid, folder_id, "\n".join(transcript))
        print(f"[voice] postmortem written for {iid}")
    except Exception as e:
        print(f"[voice] postmortem failed for {iid}: {e}")
