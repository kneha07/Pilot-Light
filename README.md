# Pilot Light

**Always on. Ignites when production breaks.**

Built for the Box + AWS Agentic Enterprise AI Hackathon, Seattle, Oct 16 to 17.

When production breaks, Pilot Light **phones the on-call engineer**. A voice agent (Amazon Nova 2 Sonic) briefs them on what broke, answers questions using live AWS data and Box runbooks, and runs an approved fix only after the engineer says **"confirm."** Every step is recorded in a **Box incident folder**, and a **postmortem** is drafted automatically and assigned for review.

> Status: hackathon build in progress. See [Build status](#build-status).

## Build status

| Component | State |
|---|---|
| AWS infra (CDK stack, demo service, alarm, EventBridge, tables, dashboard) | Built, not yet deployed |
| Incident Lambda (alarm to incident record, timeline, outbound call) | Built, Box calls stubbed, deduplicates open incidents |
| AWS tools (`query_logs`, `what_changed`, `execute_remediation`) | Built |
| Box tools (`ask_runbook`, incident folder, runbook lookup) | Stubbed. `get_briefing` reads the incident record. |
| Voice agent and telephony (Amazon Connect, Nova Sonic, AgentCore Gateway tools) | Built, Connect console setup pending ([connect/SETUP.md](connect/SETUP.md)) |
| Postmortem and Box review task | Not started |

Detailed progress for contributors is tracked in [CLAUDE.md](CLAUDE.md).

## The demo in one line

Flip the break switch → errors spike → phone rings → "What changed?" → "Revert it." → "Confirm." → errors drop → the Box folder shows briefing, transcript, timeline and postmortem.

## Why voice?

At 3am you are not at your laptop. A phone call meets the engineer where they are, and the conversation itself becomes the documentation. Slack alerts get ignored; a ringing phone does not.

## How it works

```
[Traffic script] → API Gateway → checkout Lambda ──reads──> SSM /pilotlight/checkout/fail_mode
                                      │ errors (high-resolution custom metric)
                                      ▼
                          CloudWatch Alarm (pilotlight-checkout-5xx)
                                      │ state change
                                      ▼
                          EventBridge rule → Incident Lambda
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        ▼                             ▼                             ▼
 Logs Insights + SSM history   Box: /Incidents/INC-xxx        DynamoDB timeline
 + CloudTrail ("what changed") briefing.md, runbook lookup    (dashboard reads)
                                      │
                                      ▼ StartOutboundVoiceContact
                   Amazon Connect flow → Conversational AI bot
                   Nova 2 Sonic speech-to-speech + orchestrator AI agent
                                      │ MCP tool calls
                                      ▼
                   AgentCore Gateway → tools Lambda → pilotlight/tools.py
                                      │ contact DISCONNECTED (EventBridge)
                                      ▼
                   Hang-up Lambda: transcript to timeline, incident closed
                                      │
                                      ▼
                  Bedrock drafts postmortem → Box file + Box review task
```

1. **Detect.** A checkout Lambda reads a feature flag from SSM. Flipping it on makes the service return errors and emit a CloudWatch metric.
2. **Alarm.** A CloudWatch alarm fires within seconds and an EventBridge rule invokes the Incident Lambda.
3. **Gather context.** The Incident Lambda runs a Logs Insights query, reads SSM parameter history (with CloudTrail as an extra source), creates a Box incident folder, finds the matching runbook by metadata, and writes a briefing.
4. **Call.** It places an Amazon Connect outbound call to the on-call engineer, passing the incident ID and briefing as contact attributes.
5. **Talk.** The Connect flow speaks the briefing, then hands the call to an orchestrator AI agent whose speech runs on Nova 2 Sonic. The agent answers questions by calling Pilot Light tools over MCP through an AgentCore Gateway.
6. **Fix.** The agent runs an allowlisted SSM revert only after the engineer verbally confirms.
7. **Record.** On hang-up, the transcript is copied to the timeline, and Bedrock drafts a postmortem from the timeline and transcript, saves it to Box, and creates a review task.

## Agent tools

Defined in [pilotlight/tools.py](pilotlight/tools.py). Every function returns short, speakable text (under 60 words).

| Tool | Purpose | Owner |
|---|---|---|
| `get_briefing(incident_id)` | Spoken opening briefing | Box |
| `query_logs(incident_id, minutes)` | Recent error summary from Logs Insights | AWS |
| `what_changed(incident_id, minutes)` | Recent SSM / CloudTrail config changes | AWS |
| `ask_runbook(incident_id, question)` | Box AI Q&A over the runbook | Box |
| `execute_remediation(incident_id, action, confirmed)` | Allowlisted SSM revert | AWS |
| `log_to_incident(incident_id, event_type, text)` | Write to the DynamoDB timeline and Box | Both |
| `page_teammate(incident_id, message)` | Page a second responder (first on the cut list) | AWS |

## Safety guardrails

- **Allowlist only.** The only actions that can run are listed in `ALLOWED_ACTIONS`. Anything else is refused. New actions are reviewed entries with their own runbook.
- **Verbal confirmation.** The prompt tells the model to ask for "confirm" before a fix. Because a prompt is not a code constraint, the tools Lambda also reads the live call transcript (Connect AI agent session messages) and passes `confirmed=True` only when the engineer's latest turn contains "confirm" without a negation. If the transcript cannot be read, the fix is refused.
- **Scoped IAM.** `ssm:PutParameter` is limited to the single fail-mode parameter.
- **Audit trail.** Every tool call, action and utterance is written to the timeline and to the Box incident folder.
- **Human review.** The postmortem is a draft generated from structured timeline data, and a Box review task assigns a human to approve it.
- **Idempotent incidents.** The Incident Lambda skips a new incident, and a new call, while an incident for the same alarm opened in the last 30 minutes is still open. The hang-up Lambda closes the incident.

## Shared contracts

**Incident record** (DynamoDB `pilotlight-incidents`, created by the Incident Lambda):

```json
{
  "incident_id": "INC-20261017-1002",
  "service": "checkout-api",
  "alarm_name": "pilotlight-checkout-5xx",
  "started_at": "2026-10-17T10:02:11Z",
  "status": "open",
  "box_folder_id": "123456789",
  "runbook_file_id": "987654321",
  "briefing_text": "Checkout API errors spiked at 10:02...",
  "oncall_phone": "+1206XXXXXXX",
  "contact_id": "a1b2c3d4-5678-90ab-cdef-111122223333",
  "ended_at": "2026-10-17T10:09:40Z"
}
```

**Timeline table** (DynamoDB `pilotlight-timeline`): partition key `incident_id`, sort key `ts` (ISO with milliseconds), fields `type` and `text`. Types: `alarm`, `briefing`, `call`, `user`, `agent`, `tool`, `action`, `postmortem`. The dashboard reads from this table.

**Box layout:**

```
/Runbooks/                  (metadata template: runbook)
  checkout-5xx.md           service, alarm_name, severity
/Incidents/
  INC-20261017-1002/
    briefing.md
    timeline.md
    transcript.md
    postmortem.md           (review task assigned)
```

## Repo layout

```
pilot-light/
  infra/             CDK app: demo service, alarm, EventBridge, tables, dashboard
  services/
    checkout/        demo service Lambda
    incident/        Incident Lambda: incident record, outbound call
    tools/           agent tools Lambda (AgentCore Gateway target)
    session/         Connect flow Lambda: incident context into the AI agent session
    hangup/          call ended: transcript to timeline, incident closed
  pilotlight/        shared Python package
    config.py        env loading
    tools.py         tool contract
    aws_tools.py     logs, SSM, remediation
    box_client.py    Box CCG client
    box_tools.py     Box folder, runbook, AI, task helpers
    connect.py       outbound call, AI agent session, transcript, spoken confirmation
    incidents.py     DynamoDB incident record helpers
    timeline.py      DynamoDB timeline helpers
    postmortem.py    Bedrock postmortem drafting
  connect/           Connect setup guide, AI agent prompt, MCP tool schema
  voice/             FastAPI server, Nova Sonic session, telephony bridge, audio conversion
  dashboard/         operator console: login, status, incidents, events, console links
  scripts/           demo scripts, connect_setup.py, test_call.py
  runbooks/          markdown runbooks uploaded to Box
  contracts/         example incident object and timeline schema
```

The repo is being built up to this layout; some directories do not exist yet.

## Setup

**Prerequisites**
- AWS account, region `us-east-1`, with Bedrock access enabled for Amazon Nova 2 Sonic (`amazon.nova-2-sonic-v1:0`) and a text model
- Box developer app using Server Authentication (Client Credentials Grant), authorized by an enterprise admin
- Amazon Connect instance with Amazon Connect Customer (next generation) enabled, outbound calling on, and a claimed phone number
- Python 3.12
- AWS CDK

**Steps**

```bash
git clone https://github.com/kneha07/Pilot-Light.git
cd Pilot-Light
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in values, never commit .env
```

1. Deploy the stack: `cd infra && cdk bootstrap && cdk deploy`.
2. Create the Box `/Runbooks` and `/Incidents` folders and the `runbook` metadata template, then upload `runbooks/checkout-5xx.md` with its metadata.
3. Set up Amazon Connect and Nova Sonic: `python scripts/connect_setup.py`, then the console steps in [connect/SETUP.md](connect/SETUP.md). Put `CONNECT_CONTACT_FLOW_ID` in `.env` and run `cdk deploy` again.
4. Test the phone path alone: `python scripts/test_call.py`.
5. Start the operator dashboard: `uvicorn dashboard.app:app --port 8001`, then open http://localhost:8001. Sign in with `DASHBOARD_USER` and `DASHBOARD_PASSWORD` from `.env`.

Box files are created by the app's service account. Collaborate your own Box login onto the folders to see them in the web UI.

## Running the demo

```bash
./scripts/traffic.sh      # steady traffic against the demo service
./scripts/break.sh        # flip the fail-mode flag on
./scripts/force_alarm.sh  # backup trigger if the alarm is slow
./scripts/fix.sh          # reset the flag between rehearsals
./scripts/status.sh       # flag, alarm state, latest incident timeline
```

Pre-flight checklist: flag off and alarm OK, no open incident from a previous rehearsal (`status.sh`), traffic running, `CONNECT_*` and `ONCALL_PHONE` set on the Incident Lambda. After a run, the Box folder should contain the briefing, timeline, transcript, postmortem and a review task.

## Services used

**AWS:** Amazon Connect (outbound calling, Conversational AI bot with Nova 2 Sonic speech-to-speech, orchestrator AI agent with MCP tools), Bedrock AgentCore Gateway, Bedrock (text model), Lambda, API Gateway, CloudWatch (metrics, alarms, Logs Insights), EventBridge, Systems Manager Parameter Store, CloudTrail, DynamoDB, CDK

**Box:** Platform API with Client Credentials Grant, folders and uploads, metadata templates and metadata queries, Box AI Q&A, tasks, collaborations

## Known risks and mitigations

| Risk | Mitigation |
|---|---|
| Outbound call fails (number not permitted, flow error) | Failure logged to the timeline, `test_call.py` rehearses the phone path alone, manual trigger script |
| A tool call exceeds the 30s MCP limit | Tools Lambda timeout 25s, Logs Insights polling capped at 10s |
| Slow first Box token exchange delays the call | Warm the token path, or place the call in parallel with folder creation |
| Tool calls add pauses to the conversation | Keep tool output short and have the agent say it is checking before calling a tool |
| Duplicate incidents when an alarm re-fires | Idempotency check on open incidents, alarm datapoint settings, cooldown after fix |
| Phone path fails live | Pre-recorded backup run. `REQUIRE_SPOKEN_CONFIRM=false` relaxes the transcript check only as a last resort |
