# Pilot Light: Claude Code context

Read this before doing anything in this repo. It records what is already built, what is decided, and what is next, so no session repeats finished work. **Update the Build status section after every completed step and commit it with the work.**

## 1. Project in one paragraph

Hackathon project for the Box + AWS Agentic Enterprise AI Hackathon (Seattle, Oct 16 to 17, 2026). **Submission deadline Sat Oct 17, 1:00pm.** When production breaks, Pilot Light phones the on-call engineer. A voice agent (Amazon Nova 2 Sonic) briefs them, answers questions with live AWS data and Box runbooks, and runs an allowlisted fix only after the engineer says "confirm." Everything is recorded in a Box incident folder, and a postmortem is drafted and assigned as a Box review task.

Full plan and contracts: `~/Desktop/PILOT_LIGHT_BUILD_PLAN.md` (local to Zain's machine, not in the repo). Background and decisions: `~/Desktop/CLAUDE.md`. The repo code is the source of truth where they differ.

## 2. Team and working model

| Person | Role |
|---|---|
| P1 Zain | Runs this Claude Code session, deploys, integration lead, presents the pitch |
| P2 | Voice and telephony: accounts, credentials, phone testing |
| P3 | Box: app, metadata template, credentials, Box UI checks, deck, backup video |

**One builder.** All code is written in this one Claude Code session on Zain's laptop, in this one repo. P2 and P3 do console setup, send credentials, and test. Do not split work across sessions.

## 3. Build status

Last updated: Fri Oct 16, 2026.

### Done
- [x] Tooling on Zain's Mac: AWS CLI 2.38.1, Python 3.12.15 (Homebrew), AWS CDK 2.1145, `.venv` with `requirements.txt` installed
- [x] Repo scaffold, `.env.example`, `requirements.txt`, `contracts/`
- [x] `pilotlight/config.py`: env loading, `python-dotenv` optional so it imports inside Lambda
- [x] `pilotlight/timeline.py`: `add`, `list_all` (paginated)
- [x] `pilotlight/aws_tools.py`: real `query_logs`, `what_changed`, `execute_remediation` with `ALLOWED_ACTIONS`
- [x] `pilotlight/tools.py`: P1 tools wired to `aws_tools`, `log_to_incident` writes to the timeline, `get_briefing` reads `briefing_text` from the incident record. `ask_runbook`, `page_teammate` are still stubs.
- [x] `pilotlight/box_tools.py`: **stubs** for `create_incident_folder`, `find_runbook`, `write_briefing`
- [x] `services/checkout/handler.py`: fails with PaymentTimeout while `fail_mode` is `on`, emits a 1-second-resolution metric
- [x] `services/incident/handler.py`: alarm → what_changed + query_logs → briefing → incident record + timeline → Connect outbound call (`contact_id` saved on the incident). Skips the call while `CONNECT_*` is unset. Dedupes: no new incident while one for the same alarm is open and under 30 minutes old.
- [x] `infra/` CDK stack `PilotLight`: SSM param, both tables, checkout Lambda + HTTP API, 10s alarm, `PilotLight` dashboard, Incident Lambda with scoped IAM, EventBridge rule. `cdk synth` passes.
- [x] `scripts/`: `traffic.sh`, `break.sh`, `fix.sh`, `force_alarm.sh`, `status.sh`
- [x] Pushed to `main` (commit `b184c93`)
- [x] Branch `feature/connect-nova-sonic`: Amazon Connect + Nova Sonic voice path (see `connect/SETUP.md`)
  - `pilotlight/connect.py`: `start_call`, AI agent session lookup, `set_session_data`, `transcript`, `caller_confirmed`
  - `pilotlight/incidents.py`: incident record helpers (`get`, `put`, `update`, `latest_open`, `by_contact`)
  - `services/tools/`: AgentCore Gateway Lambda target. Dispatches five tools, enforces the code-level confirm check against the live transcript (fails closed)
  - `services/session/`: flow Lambda, puts `incident_id` and `briefing` into the AI agent session (`{{$.Custom.*}}`)
  - `services/hangup/`: on contact DISCONNECTED, transcript to timeline as `user`/`agent` rows, incident `closed`
  - `infra/stack.py`: `build_asset(service)`, Lambdas `pilotlight-tools`, `pilotlight-session`, `pilotlight-hangup`, role `pilotlight-gateway`, rule `pilotlight-call-ended`, Connect IAM scoped to the instance. Synth verified with aws-cdk-lib 2.273.0.
  - `connect/`: `SETUP.md` (console steps), `agent_prompt.md`, `tool_schema.json`
  - `scripts/connect_setup.py` (gateway, target, Lambda association), `scripts/test_call.py`
  - Mocked handler tests pass. Nothing deployed or called against real AWS yet.

### Not done (in order)
- [x] Box (real, Neha's enterprise 1489125471, service account `pilot-light`): incident folder, runbook by metadata query, briefing, `ask_runbook` via **Box AI** (Bedrock fallback; Box AI needs a few seconds after a new file version), uploads with versioning, review task assigned to `BOX_REVIEWER_LOGIN`. `scripts/box_setup.py` is idempotent and supports `--collab email1,email2`. Runbook in Box updated to the adapted wording (version 2 of file 2532168279852).
- [ ] Box collaborators: Neha, Zain (zainbhutta.ai@gmail.com) and Rajnikant (trajanikantr@gmail.com) are editors on `/Runbooks` and `/Incidents`. Still needed: Harika via `python scripts/box_setup.py --collab <logins>`.
- [ ] Sat 11:30 cleanup (with Zain's approval): delete test incident folders in Box (`INC-20261017-063151` id 428391585179, `INC-20261017-065436` id 428395190170, `INC-20261017-065521`, `INC-20261017-071133`, `INC-20261017-071847` id 428401391373, `INC-20261017-072653`, `INC-20261017-072734` id 428403255684, `INC-20261017-073346`) and `.state/incidents/` test records before the clean run.
- [x] `voice/`: FastAPI server bridging Twilio Media Streams to Nova 2 Sonic (`uvicorn voice.server:app --port 8000`). `POST /call` (503 until Twilio creds are set), `WS /media`, `GET /health`. Reuses agent.py prompt, tools and confirm gate. Postmortem runs on hang-up. Tested with `voice/fake_twilio.py`: briefing 2.3s after connect, replies 1.2 to 2.8s, fix only after "confirm".
- [x] Twilio + ngrok configured in `.env`: Twilio number +17177167379 (trial), on-call phone +17189157570 (verified), `VOICE_SERVER_URL=https://vacant-neatly-clock.ngrok-free.dev` (free static domain, `ngrok http 8000 --url <that>`). Calls fetch TwiML from `GET/POST /twiml` (trial rejects inline twiml).
- [x] **Real phone call works end to end** (Sat 12:27am, `INC-20261017-072734`): break, alarm in 5s, Box folder and briefing, phone rings, briefing, what changed, Box AI runbook answer, fix refused until "confirm", fix, postmortem and review task in Box. Twilio upgraded to a full account; US standard-number dialing enabled via the Voice dialing permissions API.
- [x] `end_call` voice tool + Twilio `mark` hang-up (10s fallback). Live call 12:43am: hang-up worked on real Twilio but cut off the goodbye.
- [x] Goodbye fix (untested): server waits for goodbye audio spoken after `end_call`, plus a backstop that hangs up after any agent line containing "goodbye". **Not verified** (last test did not run). Safe demo fallback: Zain hangs up after the goodbye.
- [x] Sonic auto-reconnect: on stream error, reopen a session on the same call with the transcript so far ("Sorry, I lost you for a second"), max 3; logs the last events sent. Forced-drop test passed. Cause of the 12:36am live crash ("Invalid input request" after the briefing) still unknown; the logging will capture it if it recurs.
- Zain confirmed the second live call (12:27am) worked as expected. **Zain's budget is limited: do not run test calls or fake calls without explicit approval.**
- [x] `dashboard/` (Rajnikant, cleaned up Sat): operator console. **Live on Vercel: https://pilot-light-beta.vercel.app** (project `pilot-light`, account zainbhuttaai-1770, deployed with `vercel deploy --prod` from the repo root; no GitHub link, so redeploy from the laptop). Entry point `index.py` (FastAPI zero-config, no vercel.json). Login `admin` + password in Vercel env (Zain has it; never commit it). Reads CloudWatch Logs in us-east-2 when there is no local state: incidents from `/pilotlight/incidents` stream `incidents`, alarm from stream `alarm-state` (published by the watcher), flag from config-audit. Vercel env: `PL_AWS_ACCESS_KEY_ID`, `PL_AWS_SECRET_ACCESS_KEY`, `PL_AWS_REGION` (IAM user `pilotlight-dashboard-readonly`, read-only on `/pilotlight/*` logs in us-east-2; delete after the event), `DASHBOARD_USER`, `DASHBOARD_PASSWORD`, `DASHBOARD_SECRET`, `BOX_*_FOLDER_ID`, `VOICE_SERVER_URL`. Security reviewed: no innerHTML, http(s)-only links, 401 on all data routes, docs disabled, login throttle on x-real-ip. Local: `uvicorn dashboard.app:app --port 8001`.
- [ ] Code-level confirm check in the voice server (promised in the README)
- [ ] Projector view: CloudWatch Logs Live Tail on `/pilotlight/checkout` replaces the blocked metrics dashboard. Optional: metric filter graph (filter creation is allowed, graph read untested)
- [ ] README architecture diagram still shows the serverless design; update during the Sat 11:30 README pass
- [ ] Teammate AWS access: console passwords are blocked by the SCP. Teammates sign up through the event link themselves, or work through Zain's machine.

## 4. Decisions already made (do not reopen)

- **Names follow the build plan:** SSM `/pilotlight/checkout/fail_mode`, alarm `pilotlight-checkout-5xx`, tables `pilotlight-timeline` and `pilotlight-incidents`, stack `PilotLight`, functions `pilotlight-checkout` and `pilotlight-incident`. The older `db-mode` and `checkout-5xx-high` names are retired.
- **Region** `us-east-1`. **Python 3.12** everywhere.
- **Lambda packaging:** `infra/stack.py` copies `services/<name>/` and `pilotlight/` into `build/<name>/` at synth time. No Docker bundling. `build/` is gitignored.
- **Incident Lambda env** is read from the repo `.env` at synth time (`PASSTHROUGH_ENV` in `infra/stack.py`). After changing `.env` (for example `CONNECT_CONTACT_FLOW_ID`), run `cdk deploy` again.
- **No retries** on the Incident Lambda (`retry_attempts=0` on both the function and the rule target), so one alarm never places two calls.
- **`what_changed`** pages through all SSM history and speaks the time in Pacific time.
- **Telephony: Amazon Connect, native.** Nova Sonic runs inside Connect as the speech-to-speech model of a Conversational AI bot, with an orchestrator AI agent (copy of `SelfServiceOrchestrator`). Tools reach `pilotlight/tools.py` over MCP: AgentCore Gateway `pilotlight-tools`, Lambda target `pilotlight` (tool names `pilotlight___<tool>`). No voice server, no ngrok, no Twilio. `VOICE_SERVER_URL` and `TWILIO_*` are retired.
- **Confirm check** lives in `services/tools/handler.py`: `confirmed=True` only if the latest CUSTOMER message from `qconnect.list_messages` contains "confirm" without a negation. `REQUIRE_SPOKEN_CONFIRM=false` is an emergency demo switch only.
- **Incident lifecycle:** `open` at alarm, `closed` at hang-up.
- **Alarm** fires on `PilotLight/CheckoutErrors`, Sum over 10s, threshold 3, missing data not breaching.

## 5. Open decisions

- **Box AI Q&A** availability on the developer account. If disabled, `ask_runbook` uses Bedrock over the runbook text.
- **Text model ID** for the postmortem (P2 to confirm in the Bedrock playground).

## 6. Commands

```bash
source .venv/bin/activate
aws login && aws configure set region us-east-1 && aws sts get-caller-identity
cd infra && cdk bootstrap && cdk deploy     # if creds error: eval "$(aws configure export-credentials --format env)"

scripts/traffic.sh        # dots = 200, X = error
scripts/break.sh          # fail_mode on
scripts/status.sh         # flag, alarm state, latest incident timeline
scripts/fix.sh            # fail_mode off
scripts/force_alarm.sh    # only fires if the alarm is not already in ALARM; run fix.sh and wait for OK first

python scripts/connect_setup.py   # after cdk deploy: AgentCore Gateway + target, Lambda association (idempotent)
python scripts/test_call.py       # ring ONCALL_PHONE with a test incident, checkout untouched
uvicorn dashboard.app:app --port 8001   # operator dashboard, http://localhost:8001
```

## 7. Rules

- Never commit `.env` or secrets. Credentials arrive by DM and go only in `.env`.
- Commit after each working step. End commit messages with the `Co-Authored-By` line.
- Do not change the shared contracts (`pilotlight/tools.py` signatures, `contracts/`, table schemas) without telling Zain.
- Ask before anything destructive: `cdk destroy`, any `delete-*`, force pushes.
- If a step blocks for more than 20 minutes, stub it and move on.
- **Writing style** for docs, README, commits, slides: professional, precise, declarative. No filler. **Never use em dashes.**
