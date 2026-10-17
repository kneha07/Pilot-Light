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

Teammates: Rajnikant, Harika, Neha (team of 4). **Neha owns Box (P3).** Voice and Twilio (P2) are shared by the whole team.

**One builder, orchestrated.** All code is written from this one Claude Code session (the orchestrator may launch sub-agents on disjoint files; Zain approves every commit) on Zain's laptop, in this one repo. Teammates do console setup, send credentials, and test. Do not split work across sessions.

## 3. AWS account and its limits (read before touching AWS)

- **Account:** `048394351147`, created through the event link. CLI profile **`pilotlight`** (`aws login --profile pilotlight`). **Regions: `AWS_REGION=us-east-2` (Ohio) for CloudWatch Logs and Nova 2 Lite; `SONIC_REGION=us-east-1` for Nova 2 Sonic only** (not offered in Ohio). Moved to Ohio Sat Oct 17 because the console in this account only works in Ohio (N. Virginia shows "region unavailable"). Old us-east-1 log groups hold Friday's tests only. `.env` sets `AWS_PROFILE=pilotlight`. Sessions expire: if calls fail with a login error, Zain reruns `aws login --profile pilotlight`.
- An **organization SCP blocks**: CloudFormation (so no CDK), Lambda, DynamoDB, SSM, EventBridge, API Gateway, SNS, SQS, S3 writes, CloudWatch metrics/alarms/dashboards, Secrets Manager, Lightsail, Transcribe, Polly, IAM console passwords. The IAM simulator reports Nova 2 Sonic as denied, but a real session works; trust real calls over the simulator.
- **Allowed:** CloudWatch Logs (groups, writes, Logs Insights, metric filters, Live Tail), Bedrock Nova models (Nova 2 Sonic, Nova 2 Lite confirmed), IAM roles and users, CloudTrail lookup, Budgets. **Claude models need the Anthropic use-case form** (not submitted); text model is Nova 2 Lite via `TEXT_MODEL_ID` in `.env`.
- Zain decided (Fri Oct 16) to **adapt the design to the allowed services** rather than use a different account. Do not reopen. The original CDK stack is in git history at commit `b184c93` if the SCP is lifted.
- An earlier event account `150457423219` has the same SCP. Do not use it.

## 4. Build status

Last updated: Fri Oct 16, 2026, 11:10pm.

### Done (tested end to end in the event account)
- [x] Tooling on Zain's Mac: AWS CLI 2.38.1, Python 3.12.15 (Homebrew), `.venv` with `requirements.txt` (includes `awscrt` for the Sonic stream)
- [x] `pilotlight/config.py`: env loading, log group names, `STATE_DIR` (`.state/`, gitignored), alarm rule (3 errors in 10s)
- [x] `pilotlight/logstore.py`: CloudWatch Logs helpers (put, read stream, recent across group, buffered shipper)
- [x] `pilotlight/flags.py`: fail_mode flag in `.state/fail_mode`, every change audited to `/pilotlight/config-audit`. CLI: `python -m pilotlight.flags on|off --by NAME`
- [x] `pilotlight/timeline.py`: `add`, `list_all` on `/pilotlight/timeline`, one stream per incident (same signatures as before)
- [x] `pilotlight/incidents.py`: `put`, `get`, `latest`, `update`. Local JSON in `.state/incidents/` plus audit to `/pilotlight/incidents`
- [x] `pilotlight/aws_tools.py`: `query_logs` (Logs Insights, falls back to filter), `what_changed` (config audit log), `execute_remediation` (allowlist + confirm, flips the flag, audits who)
- [x] `pilotlight/tools.py`: P1 tools wired. `get_briefing`, `ask_runbook`, `page_teammate` still stubs.
- [x] `services/checkout/handler.py`: local HTTP service on :8080, `GET /checkout`, ships logs to `/pilotlight/checkout`
- [x] `services/incident/watcher.py`: alarm evaluator (replaces CloudWatch alarm + EventBridge). Polls every 2s, opens an incident on OK to ALARM. Honors `.state/force_alarm`.
- [x] `services/incident/handler.py`: Lambda-shaped `handler(event)`. what_changed + query_logs, briefing, incident record, timeline. Skips `/call` while `VOICE_SERVER_URL` is empty.
- [x] `scripts/`: `setup_aws.py` (log groups, idempotent), `start.sh` (service + watcher), `traffic.sh`, `break.sh`, `fix.sh`, `force_alarm.sh`, `status.sh`
- [x] `pilotlight/agent.py`: `IncidentAgent` on Bedrock converse with tool use. Code-level confirm gate (fix runs only if the engineer's latest turn contains "confirm"). Logs user/agent turns to the timeline. 1.8s per turn on Nova 2 Lite.
- [x] `pilotlight/chat.py`: terminal chat, `python -m pilotlight.chat [INCIDENT_ID]`, runs the postmortem on exit
- [x] `pilotlight/postmortem.py`: Bedrock draft (six sections) from timeline and transcript, uploads transcript/timeline/postmortem, review task, marks incident resolved
- [x] **Nova 2 Sonic works** in this account (Fri 11:30pm test): speech in, speech out, tool calling, 8 kHz output accepted, about 3s to first audio. SDK: `AsyncBedrockRuntimeClient`, `await AsyncBedrockRuntimeConfig.resolve(region, aws_credentials_identity_resolver=EnvironmentCredentialsResolver(), transport=AWSCRTHTTPClient())`. Start the output reader after session start, prompt start and system prompt; keep sending silence while the model answers.
- [x] Test passed: break, alarm in under 10s, incident with real what_changed and Logs Insights data, allowlist refusal, confirm gate, fix, alarm OK after 17s

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

- [x] Revert PR (Sat 11:45): after every confirmed fix, `pilotlight/revert_pr.py` opens a GitHub PR in the background via the `gh` CLI login (branch `pilot-light/revert-<inc>`, adds `config/flags.json` and `incidents/<inc>.md`), logs "Pull request opened: <url>" to the timeline, and the dashboard shows it as a link. About 7s. `AUTO_REVERT_PR=false` disables it. Test PR #5 on INC-20261017-183550.
- [x] Voice prompt: "failover" is treated as a mishearing of "fail mode"; actions only on clear requests.

- [x] **Break something** button (Sat 12:00): dashboard Live view card "Run the live demo" calls `POST /api/demo/break|reset` (login required), which forwards to the voice server `POST /demo/break|reset` through ngrok with header `x-demo-token` = `DEMO_TRIGGER_TOKEN` (in local `.env` and Vercel env; never commit it). The voice server endpoint only toggles fail_mode and returns 403 without the token. The voice server, ngrok, watcher, and checkout service must be running on the laptop for the button to work.

- [x] Call quality (Sat 12:10): voice prompt opens with the incident, answers "what changed" with the change, active error count, and runbook guidance (runbook text loaded into the prompt, cached per process). Server-side echo guard (caller muted while agent audio plays plus 0.4s; no barge-in) and noise gate (RMS 250, 0.5s hold) on caller audio. Not yet tested on a live call.

### Harika's additions (merged Sat 11:20, PR #1)
Kept as additive files: `pilotlight/auto_fix/` (postmortem to tasks to GitHub PRs; run on demand: `python -m pilotlight.auto_fix <INCIDENT_ID>`, needs `GITHUB_REPO`/`GITHUB_TOKEN`), `connect/`, `pilotlight/connect.py`, `services/hangup|session|tools/`, `scripts/connect_setup.py`, `scripts/box_setup_metadata.py`, `scripts/test_call.py`, `samples/`, `infra/stack.py`. These target Amazon Connect, DynamoDB, and Lambda, which the event account blocks, and some call DynamoDB-era helpers (`incidents.latest_open`, `by_contact`) that the working build does not have. Her PR's edits to the demo core (config, timeline, incidents, tools, postmortem, incident handler, requirements, docs) were not taken, because they switched storage to DynamoDB and telephony to Connect. Ported Sat 11:50 onto the working stack: incident dedupe (`incidents.latest_open`, 30 min window, no second call), `REQUIRE_SPOKEN_CONFIRM` (default true) in the agent's confirm gate, auto-fix **plan mode** triggered after every postmortem (`AUTO_FIX_ENABLED`, default on: Box AI + Nova 2 Lite, `auto_fix_plan.md` + review task in Box, `autofix` timeline rows; **never run end to end yet**), opt-in PR mode `python -m pilotlight.auto_fix <INC> --pr` (isolated git worktree in temp, `claude -p`, never the live repo), `scripts/test_call.py --yes`, `scripts/box_setup_metadata.py` (creates her autoFixTask and incident templates; not run). Box `Incidents` folder was emptied by a teammate on Sat morning; old incidents' Box links 404, CloudWatch timelines remain.

## 5. Decisions already made (do not reopen)

- **Adapted design** for the restricted event account (section 3). Everything runs on Zain's laptop; AWS provides CloudWatch Logs and Bedrock.
- **Names:** flag `/pilotlight/checkout/fail_mode` (name kept for the story; value lives in `.state/fail_mode`), alarm `pilotlight-checkout-5xx`, log groups `/pilotlight/checkout`, `/pilotlight/config-audit`, `/pilotlight/timeline`, `/pilotlight/incidents`. The older `db-mode` and `checkout-5xx-high` names are retired.
- **Regions:** Ohio for logs and text models, N. Virginia for Nova 2 Sonic (see section 3). **Python 3.12** everywhere (the voice server needs `audioop`).
- **Alarm rule:** at least 3 ERROR events in 10s across `/pilotlight/checkout`, evaluated every 2s with 5s ingestion slack. One incident per OK to ALARM transition, so no duplicate calls.
- **The incident handler keeps the Lambda signature** `handler(event, context)` and an EventBridge-shaped event, so it can move to Lambda if the SCP is lifted.
- **`what_changed`** reads the config audit log and speaks Pacific time.
- Tool contracts in `pilotlight/tools.py` and the incident record shape are unchanged.

## 6. Open decisions

- **Telephony:** Twilio Media Streams (build plan). Voice engine is Nova 2 Sonic (decided, works). Amazon Connect is blocked by the SCP.


## 7. Commands

```bash
source .venv/bin/activate
aws login --profile pilotlight                     # when the session expires
python scripts/setup_aws.py                        # once: CloudWatch Logs groups

scripts/start.sh          # checkout service :8080 + alarm watcher (Ctrl-C stops both)
scripts/traffic.sh        # dots = 200, X = error
scripts/break.sh          # fail_mode on
scripts/status.sh         # flag, alarm state, latest incident timeline
scripts/fix.sh            # fail_mode off
scripts/force_alarm.sh    # watcher opens an incident on its next poll if the alarm is OK
uvicorn dashboard.app:app --port 8001   # operator dashboard, http://localhost:8001
```

## 8. Rules

- Never commit `.env` or secrets. Credentials arrive by DM and go only in `.env`.
- Commit after each working step. End commit messages with the `Co-Authored-By` line.
- Do not change the shared contracts (`pilotlight/tools.py` signatures, `contracts/`, table schemas) without telling Zain.
- Ask before anything destructive: `cdk destroy`, any `delete-*`, force pushes.
- If a step blocks for more than 20 minutes, stub it and move on.
- **Writing style** for docs, README, commits, slides: professional, precise, declarative. No filler. **Never use em dashes.**
