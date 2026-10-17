"""Voice-agnostic incident agent: Claude on Bedrock (Converse API) with tool use.
Any voice front end (Nova Sonic bridge, Twilio speech, terminal chat) feeds it text turns."""
import json
import re

import boto3

from . import timeline, tools
from .config import AWS_REGION, REQUIRE_SPOKEN_CONFIRM, TEXT_MODEL_ID

MODEL_ID = TEXT_MODEL_ID or "global.anthropic.claude-haiku-4-5-20251001-v1:0"
MAX_TOOL_ROUNDS = 6

SYSTEM_PROMPT = """You are Pilot Light, an incident response voice agent on a phone call with an on-call engineer.
Incident: {incident_id}.

Rules:
- Speak in short plain sentences. Two or three sentences per turn, maximum. No markdown, lists, or symbols.
- Start by giving the briefing from the get_briefing tool, then ask: "Do you want the logs, what changed, or the runbook?"
- Use tools for every fact. Never guess numbers, times, or causes.
- Before any fix: state exactly what you will change, then ask the engineer to say "confirm".
  Only call execute_remediation with confirmed=true after the engineer says the word "confirm".
- You can only perform actions on the approved list: rollback_payment_config. If asked for anything else, say so.
- Call the problem a payment configuration change and the fix rolling back the payment configuration. Never say fail mode.
- After a fix, tell the engineer what to watch, then offer to end the call.
- Calm, direct, professional. No filler."""


def _schema(props: dict, required: list[str]) -> dict:
    return {"json": {"type": "object", "properties": props, "required": required}}


TOOL_SPECS = [
    {"toolSpec": {"name": "get_briefing", "description": "Get the opening incident briefing.",
                  "inputSchema": _schema({}, [])}},
    {"toolSpec": {"name": "query_logs", "description": "Summarize recent checkout error logs.",
                  "inputSchema": _schema({"minutes": {"type": "integer", "description": "Lookback window, default 15."}}, [])}},
    {"toolSpec": {"name": "what_changed", "description": "Recent configuration changes, including who changed what and when.",
                  "inputSchema": _schema({"minutes": {"type": "integer", "description": "Lookback window, default 60."}}, [])}},
    {"toolSpec": {"name": "ask_runbook", "description": "Ask a question of the runbook for this alarm.",
                  "inputSchema": _schema({"question": {"type": "string"}}, ["question"])}},
    {"toolSpec": {"name": "execute_remediation",
                  "description": "Run an approved fix. Only call with confirmed=true after the engineer explicitly says the word confirm.",
                  "inputSchema": _schema({"action": {"type": "string", "enum": ["rollback_payment_config"]},
                                          "confirmed": {"type": "boolean"}}, ["action", "confirmed"])}},
]

_CONFIRM = re.compile(r"\bconfirm(ed)?\b", re.IGNORECASE)


def _speakable(text: str) -> str:
    text = re.sub(r"[*#`>]+", "", text).replace("_", " ")
    text = re.sub(r"^\s*[-•]\s*", "", text, flags=re.MULTILINE)
    return " ".join(text.split())


class IncidentAgent:
    def __init__(self, incident_id: str):
        self.incident_id = incident_id
        self.br = boto3.client("bedrock-runtime", region_name=AWS_REGION)
        self.system = [{"text": SYSTEM_PROMPT.format(incident_id=incident_id)}]
        self.messages: list[dict] = []
        self.transcript: list[str] = []
        self._last_user = ""

    def opening(self) -> str:
        return self._turn("The call just connected. Give the briefing now.", log_user=False)

    def respond(self, user_text: str) -> str:
        return self._turn(user_text)

    def _turn(self, user_text: str, log_user: bool = True) -> str:
        if log_user:
            self._last_user = user_text
            self.transcript.append(f"Engineer: {user_text}")
            timeline.add(self.incident_id, "user", user_text)
        self.messages.append({"role": "user", "content": [{"text": user_text}]})
        reply = ""
        for _ in range(MAX_TOOL_ROUNDS):
            r = self.br.converse(modelId=MODEL_ID, system=self.system, messages=self.messages,
                                 toolConfig={"tools": TOOL_SPECS}, inferenceConfig={"maxTokens": 300})
            msg = r["output"]["message"]
            self.messages.append(msg)
            uses = [c["toolUse"] for c in msg["content"] if "toolUse" in c]
            if not uses:
                reply = " ".join(c["text"] for c in msg["content"] if "text" in c)
                break
            self.messages.append({"role": "user", "content": [
                {"toolResult": {"toolUseId": u["toolUseId"], "content": [{"text": self._run_tool(u["name"], u["input"])}]}}
                for u in uses]})
        else:
            reply = "I am still working on that. Give me a moment."
        reply = _speakable(reply)
        self.transcript.append(f"Pilot Light: {reply}")
        timeline.add(self.incident_id, "agent", reply)
        return reply

    def _run_tool(self, name: str, args: dict) -> str:
        iid = self.incident_id  # injected server side, never chosen by the model
        try:
            if name == "get_briefing":
                return tools.get_briefing(iid)
            if name == "query_logs":
                return tools.query_logs(iid, int(args.get("minutes", 15)))
            if name == "what_changed":
                return tools.what_changed(iid, int(args.get("minutes", 60)))
            if name == "ask_runbook":
                return tools.ask_runbook(iid, str(args.get("question", "")))
            if name == "execute_remediation":
                # Code-level gate: the model's confirmed flag counts only if the engineer said "confirm"
                confirmed = bool(args.get("confirmed"))
                if REQUIRE_SPOKEN_CONFIRM:
                    confirmed = confirmed and bool(_CONFIRM.search(self._last_user))
                return tools.execute_remediation(iid, str(args.get("action", "")), confirmed)
            return f"Unknown tool {name}."
        except Exception as e:
            return f"The {name} tool failed: {e}"
