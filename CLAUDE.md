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
- [x] `pilotlight/tools.py`: P1 tools wired to `aws_tools`, `log_to_incident` writes to the timeline. `get_briefing`, `ask_runbook`, `page_teammate` are still stubs.
- [x] `pilotlight/box_tools.py`: **stubs** for `create_incident_folder`, `find_runbook`, `write_briefing`
- [x] `services/checkout/handler.py`: fails with PaymentTimeout while `fail_mode` is `on`, emits a 1-second-resolution metric
- [x] `services/incident/handler.py`: alarm → what_changed + query_logs → briefing → incident record + timeline. Skips `/call` while `VOICE_SERVER_URL` is empty.
- [x] `infra/` CDK stack `PilotLight`: SSM param, both tables, checkout Lambda + HTTP API, 10s alarm, `PilotLight` dashboard, Incident Lambda with scoped IAM, EventBridge rule. `cdk synth` passes.
- [x] `scripts/`: `traffic.sh`, `break.sh`, `fix.sh`, `force_alarm.sh`, `status.sh`
- [x] Pushed to `main` (commit `b184c93`)

- [x] Box built and tested against real Box (Fri Oct 16): `box_client.py`, real `box_tools.py`, `postmortem.py`, `scripts/box_setup.py`, `runbooks/checkout-5xx.md`; `get_briefing` and `ask_runbook` wired in `tools.py`. Verified: CCG auth, `box_setup.py` (folders, `runbook` template, runbook metadata), `find_runbook`, `create_incident_folder` (idempotent), `write_briefing` (new version on rewrite), `ask_runbook` via Box AI, `create_review_task`; `build_incident_asset()` installs `box-sdk-gen`

### Not done (in order)
- [ ] `aws login` by Zain (interactive), `cdk bootstrap`, `cdk deploy`
- [ ] Test: traffic → break → alarm ALARM within ~30s → `status.sh` shows incident and timeline rows → fix → alarm OK
- [ ] Box: send the six Box values to Zain for the Incident Lambda env, then redeploy. Test `postmortem.generate` once `TEXT_MODEL_ID` is set. Delete the `INC-TEST-0001` test folder in `/Incidents`.
- [ ] Voice: `voice/sonic.py`, `voice/prompt.py`, `voice/audio.py`, `voice/server.py` (terminal mic first, then phone)
- [ ] Wire `postmortem.generate` to hang-up in the voice server
- [ ] Idempotency: skip creating a new incident if one is already open for the same alarm (promised in the README)
- [ ] Code-level confirm check in the voice server (promised in the README)
- [ ] Stretch: timeline page. README services list and architecture are already written.

## 4. Decisions already made (do not reopen)

- **Names follow the build plan:** SSM `/pilotlight/checkout/fail_mode`, alarm `pilotlight-checkout-5xx`, tables `pilotlight-timeline` and `pilotlight-incidents`, stack `PilotLight`, functions `pilotlight-checkout` and `pilotlight-incident`. The older `db-mode` and `checkout-5xx-high` names are retired.
- **Region** `us-east-1`. **Python 3.12** everywhere (the voice server needs `audioop`).
- **Lambda packaging:** `infra/stack.py` copies `services/incident/` and `pilotlight/` into `build/incident/` at synth time. No Docker bundling. `build/` is gitignored.
- **Incident Lambda env** is read from the repo `.env` at synth time (`PASSTHROUGH_ENV` in `infra/stack.py`). After changing `.env` (for example a new ngrok URL), run `cdk deploy` again.
- **No retries** on the Incident Lambda (`retry_attempts=0` on both the function and the rule target), so one alarm never places two calls.
- **`what_changed`** pages through all SSM history and speaks the time in Pacific time.
- **Alarm** fires on `PilotLight/CheckoutErrors`, Sum over 10s, threshold 3, missing data not breaching.

## 5. Open decisions

- **Telephony: Twilio or Amazon Connect.** The build plan specifies Twilio Media Streams. `README.md` says Amazon Connect. Confirm with Zain before writing `voice/server.py`.
- **Box AI Q&A:** resolved, enabled on the developer account. The Bedrock fallback in `ask_runbook` stays as a backup.
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
```

## 7. Rules

- Never commit `.env` or secrets. Credentials arrive by DM and go only in `.env`.
- Commit after each working step. End commit messages with the `Co-Authored-By` line.
- Do not change the shared contracts (`pilotlight/tools.py` signatures, `contracts/`, table schemas) without telling Zain.
- Ask before anything destructive: `cdk destroy`, any `delete-*`, force pushes.
- If a step blocks for more than 20 minutes, stub it and move on.
- **Writing style** for docs, README, commits, slides: professional, precise, declarative. No filler. **Never use em dashes.**
