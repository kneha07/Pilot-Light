"""Nova 2 Sonic speech-to-speech session with tool calling, one per phone call."""
import asyncio
import base64
import json
import uuid
from collections import deque
from typing import Awaitable, Callable

import boto3
from aws_sdk_bedrock_runtime.client import AsyncBedrockRuntimeClient
from aws_sdk_bedrock_runtime.config import AsyncBedrockRuntimeConfig
from aws_sdk_bedrock_runtime.models import (BidirectionalInputPayloadPart,
                                            InvokeModelWithBidirectionalStreamInputChunk,
                                            InvokeModelWithBidirectionalStreamOperationInput)
from smithy_aws_core.identity import AWSCredentialsIdentity
from smithy_core.aio.interfaces.identity import IdentityResolver
from smithy_http.aio.crt import AWSCRTHTTPClient

from pilotlight import timeline
from pilotlight.agent import TOOL_SPECS, IncidentAgent, _speakable
from pilotlight.config import SONIC_MODEL_ID, SONIC_REGION

from . import prompt

OUT_RATE = 8000  # Twilio's rate, so no resampling on the way out
VOICE_ID = "matthew"
END_CALL_QUIET_SECONDS = 1.5
MAX_RECONNECTS = 3
RECONNECT_KICKOFF = ("The audio connection dropped and is back. Say only: Sorry, I lost you for a second. "
                     "Then continue the conversation where it left off.")  # model audio has stopped for this long, so the goodbye is fully generated

END_CALL_SPEC = {"toolSpec": {
    "name": "end_call",
    "description": "Hang up the phone call. Only after the engineer agrees to end the call and you have said goodbye.",
    "inputSchema": {"json": json.dumps({"type": "object", "properties": {}})}}}


class _ProfileCredentials(IdentityResolver):
    """Resolves credentials from the boto3 default chain (AWS_PROFILE from .env) on every request."""

    async def get_identity(self, *, properties=None):
        c = boto3.Session().get_credentials().get_frozen_credentials()
        return AWSCredentialsIdentity(access_key_id=c.access_key, secret_access_key=c.secret_key,
                                      session_token=c.token)


def _sonic_tools() -> list[dict]:
    """The text agent's tool specs, with the JSON schema serialized as Sonic expects."""
    return [{"toolSpec": {**t["toolSpec"], "inputSchema": {"json": json.dumps(t["toolSpec"]["inputSchema"]["json"])}}}
            for t in TOOL_SPECS] + [END_CALL_SPEC]


class SonicSession:
    def __init__(self, incident_id: str,
                 on_audio: Callable[[bytes], Awaitable[None]],
                 on_interrupt: Callable[[], Awaitable[None]] | None = None,
                 on_end: Callable[[], Awaitable[None]] | None = None):
        self.incident_id = incident_id
        self.on_audio, self.on_interrupt, self.on_end = on_audio, on_interrupt, on_end
        self._last_audio = 0.0
        self._ready = False
        self._reconnecting = False
        self._ending = False
        self._reconnects = 0
        self._sent: deque[str] = deque(maxlen=12)  # recent outbound event summaries, printed on stream errors
        self.transcript: list[str] = []
        self.last_user = ""
        self.closed = False
        self._prompt, self._audio = str(uuid.uuid4()), str(uuid.uuid4())
        self._stages: dict[str, str] = {}
        self._send_lock = asyncio.Lock()
        self._tool_runner = IncidentAgent.__new__(IncidentAgent)  # reuse _run_tool and its confirm gate
        self._tool_runner.incident_id = incident_id

    async def _send(self, event: dict) -> None:
        kind = next(iter(event))
        if kind != "audioInput":
            self._sent.append(f"{kind}:{json.dumps(event[kind])[:160]}")
        elif not self._sent or not self._sent[-1].startswith("audioInput"):
            self._sent.append("audioInput")
        async with self._send_lock:
            await self._stream.input_stream.send(InvokeModelWithBidirectionalStreamInputChunk(
                value=BidirectionalInputPayloadPart(bytes_=json.dumps({"event": event}).encode())))

    async def _text(self, role: str, text: str, interactive: bool) -> None:
        name = str(uuid.uuid4())
        await self._send({"contentStart": {"promptName": self._prompt, "contentName": name, "type": "TEXT",
                          "interactive": interactive, "role": role,
                          "textInputConfiguration": {"mediaType": "text/plain"}}})
        await self._send({"textInput": {"promptName": self._prompt, "contentName": name, "content": text}})
        await self._send({"contentEnd": {"promptName": self._prompt, "contentName": name}})

    async def start(self) -> None:
        await self._open(prompt.build(self.incident_id), prompt.KICKOFF)
        timeline.add(self.incident_id, "call", "Call connected, voice agent started")

    async def _open(self, system_prompt: str, kickoff: str) -> None:
        self._ready = False
        self._prompt, self._audio = str(uuid.uuid4()), str(uuid.uuid4())
        cfg = await AsyncBedrockRuntimeConfig.resolve(
            region=SONIC_REGION, aws_credentials_identity_resolver=_ProfileCredentials(), transport=AWSCRTHTTPClient())
        client = AsyncBedrockRuntimeClient(config=cfg)
        self._stream = await client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=SONIC_MODEL_ID))
        await self._send({"sessionStart": {"inferenceConfiguration": {"maxTokens": 1024, "topP": 0.9, "temperature": 0.7}}})
        await self._send({"promptStart": {
            "promptName": self._prompt,
            "textOutputConfiguration": {"mediaType": "text/plain"},
            "audioOutputConfiguration": {"mediaType": "audio/lpcm", "sampleRateHertz": OUT_RATE, "sampleSizeBits": 16,
                                         "channelCount": 1, "voiceId": VOICE_ID, "encoding": "base64",
                                         "audioType": "SPEECH"},
            "toolUseOutputConfiguration": {"mediaType": "application/json"},
            "toolConfiguration": {"tools": _sonic_tools()}}})
        await self._text("SYSTEM", system_prompt, interactive=False)
        self._reader = asyncio.create_task(self._read(self._stream))
        await self._send({"contentStart": {"promptName": self._prompt, "contentName": self._audio, "type": "AUDIO",
                          "interactive": True, "role": "USER",
                          "audioInputConfiguration": {"mediaType": "audio/lpcm", "sampleRateHertz": 16000,
                                                      "sampleSizeBits": 16, "channelCount": 1,
                                                      "audioType": "SPEECH", "encoding": "base64"}}})
        await self._text("USER", kickoff, interactive=True)  # the agent speaks first
        self._ready = True

    async def send_audio(self, pcm_16k: bytes) -> None:
        if not self.closed and self._ready:
            try:
                await self._send({"audioInput": {"promptName": self._prompt, "contentName": self._audio,
                                                 "content": base64.b64encode(pcm_16k).decode()}})
            except Exception as e:
                self._trigger_reconnect(f"send failed: {e}")

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            await self._send({"contentEnd": {"promptName": self._prompt, "contentName": self._audio}})
            await self._send({"promptEnd": {"promptName": self._prompt}})
            await self._send({"sessionEnd": {}})
            await self._stream.input_stream.close()
        except Exception:
            pass
        try:
            await asyncio.wait_for(self._reader, 5)
        except Exception:
            self._reader.cancel()

    async def _read(self, stream) -> None:
        _, out = await stream.await_output()
        while True:
            try:
                r = await out.receive()
            except Exception as e:
                if not self.closed and stream is self._stream:
                    self._trigger_reconnect(str(e))
                return
            if r is None:
                return
            raw = getattr(getattr(r, "value", None), "bytes_", None)
            if raw is None:
                print(f"[sonic] non-payload event: {r!r}"[:300])
                return
            for kind, body in json.loads(raw).get("event", {}).items():
                await self._handle(kind, body)

    async def _handle(self, kind: str, body: dict) -> None:
        if kind == "audioOutput":
            self._last_audio = asyncio.get_running_loop().time()
            await self.on_audio(base64.b64decode(body["content"]))
        elif kind == "contentStart" and body.get("type") == "TEXT":
            fields = json.loads(body.get("additionalModelFields") or "{}")
            self._stages[body.get("contentId", "")] = fields.get("generationStage", "FINAL")
        elif kind == "textOutput":
            text, role = body.get("content", ""), body.get("role")
            if '"interrupted"' in text:
                if self.on_interrupt:
                    await self.on_interrupt()
                return
            if role == "USER":
                if text.strip() in (prompt.KICKOFF, RECONNECT_KICKOFF):
                    return
                self.last_user = text
                self.transcript.append(f"Engineer: {text}")
                await asyncio.to_thread(timeline.add, self.incident_id, "user", text)
            elif role == "ASSISTANT" and self._stages.get(body.get("contentId", ""), "FINAL") == "FINAL":
                text = _speakable(text)
                self.transcript.append(f"Pilot Light: {text}")
                if "goodbye" in text.lower():  # backstop when the model says goodbye without calling end_call
                    asyncio.create_task(self._end_when_quiet(0.0))
                await asyncio.to_thread(timeline.add, self.incident_id, "agent", text)
        elif kind == "toolUse":
            asyncio.create_task(self._tool(body))

    async def _tool(self, body: dict) -> None:
        name, args = body.get("toolName", ""), json.loads(body.get("content") or "{}")
        if name == "end_call":
            result = "The line will close after you speak. Now say one short goodbye sentence to the engineer."
            asyncio.create_task(self._end_when_quiet(asyncio.get_running_loop().time()))
        else:
            # Code-level confirm gate: _run_tool checks the latest engineer transcript for "confirm"
            self._tool_runner._last_user = self.last_user
            result = await asyncio.to_thread(self._tool_runner._run_tool, name, args)
        content = str(uuid.uuid4())
        await self._send({"contentStart": {"promptName": self._prompt, "contentName": content, "interactive": False,
                          "type": "TOOL", "role": "TOOL",
                          "toolResultInputConfiguration": {"toolUseId": body["toolUseId"], "type": "TEXT",
                                                           "textInputConfiguration": {"mediaType": "text/plain"}}}})
        await self._send({"toolResult": {"promptName": self._prompt, "contentName": content,
                                         "content": json.dumps({"result": result})}})
        await self._send({"contentEnd": {"promptName": self._prompt, "contentName": content}})

    async def _end_when_quiet(self, called_at: float) -> None:
        """Wait for the goodbye spoken after the tool call to finish generating, then hand off to hang up."""
        if self._ending:
            return
        self._ending = True
        loop = asyncio.get_running_loop()
        called_at = called_at or loop.time() - 1  # goodbye already spoken: only wait for quiet
        deadline = called_at + 15
        while self._last_audio <= called_at and loop.time() < called_at + 6:  # goodbye has not started yet
            await asyncio.sleep(0.1)
        while loop.time() - self._last_audio < END_CALL_QUIET_SECONDS and loop.time() < deadline:
            await asyncio.sleep(0.25)
        await asyncio.to_thread(timeline.add, self.incident_id, "call", "Agent ended the call")
        if self.on_end:
            await self.on_end()

    def _trigger_reconnect(self, reason: str) -> None:
        """Start exactly one reconnect, whichever of the reader or sender notices the failure first."""
        if self._reconnecting or self.closed:
            return
        self._reconnecting, self._ready = True, False
        print(f"[sonic] stream error: {reason}")
        print("[sonic] last events sent: " + " | ".join(self._sent))
        asyncio.create_task(self._reconnect(reason))

    async def _reconnect(self, reason: str) -> None:
        """Open a fresh Sonic session on the same call, carrying the conversation so far."""
        if self._reconnects >= MAX_RECONNECTS or self.closed:
            await asyncio.to_thread(timeline.add, self.incident_id, "call", f"Voice session lost: {reason}")
            return
        self._reconnects += 1
        await asyncio.to_thread(timeline.add, self.incident_id, "call",
                                f"Voice session dropped ({reason}), reconnecting ({self._reconnects}/{MAX_RECONNECTS})")
        history = "\n".join(self.transcript[-12:]) or "(nothing said yet)"
        system = prompt.build(self.incident_id) + f"\n\nConversation so far on this call:\n{history}"
        try:
            await self._open(system, RECONNECT_KICKOFF)
            self._reconnecting = False
        except Exception as e:
            print(f"[sonic] reconnect failed: {e}")
            await self._reconnect(f"reconnect failed: {e}")
