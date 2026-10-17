# Amazon Connect and Nova Sonic setup

Pilot Light calls the on-call engineer through Amazon Connect. Nova Sonic runs inside Connect as the speech-to-speech model of a Conversational AI bot. An orchestrator AI agent behind that bot calls Pilot Light tools over MCP through an Amazon Bedrock AgentCore Gateway, which invokes the `pilotlight-tools` Lambda.

```
Incident Lambda ─StartOutboundVoiceContact─> Connect flow "PilotLight Oncall"
  attributes: incident_id, briefing               │
                                                  ├─ Set voice: Matthew, Generative
                                                  ├─ Connect assistant (AI agent domain)
                                                  ├─ Lambda pilotlight-session ─> UpdateSessionData
                                                  │     ({{$.Custom.incident_id}}, {{$.Custom.briefing}})
                                                  └─ Get customer input: PilotLightBot
                                                        Nova Sonic speech-to-speech
                                                        Orchestrator AI agent "PilotLightOnCall"
                                                           │ MCP tools/call
                                                           ▼
                                                 AgentCore Gateway "pilotlight-tools"
                                                           │
                                                           ▼
                                                 Lambda pilotlight-tools ─> pilotlight/tools.py
Contact DISCONNECTED ─EventBridge─> Lambda pilotlight-hangup: transcript to timeline, incident closed
```

Steps 1, 3, 4 and 11 are scripted. The rest are console steps, because Connect has no stable API for AI agent tools, bot speech models, or the Set voice generative style.

## 1. Instance (P2)

1. Create an Amazon Connect instance in `us-east-1` with **Amazon Connect Customer** (next generation) enabled. Turn on **outbound calls**.
2. Claim a phone number (DID) and note it as `CONNECT_SOURCE_PHONE`.
3. Note the instance ID (the last part of the instance ARN) and the access URL, for example `https://pilotlight.my.connect.aws`.
4. Add to `.env`:

```
CONNECT_INSTANCE_ID=...
CONNECT_INSTANCE_URL=https://<alias>.my.connect.aws
CONNECT_SOURCE_PHONE=+1...
ONCALL_PHONE=+1...
```

A trial account can only call verified or permitted destinations. Place one manual outbound call from the agent workspace first to confirm the number can dial `ONCALL_PHONE`.

## 2. Deploy

```bash
cd infra && cdk deploy
```

With `CONNECT_INSTANCE_ID` set, IAM and the hang-up rule are scoped to the instance.

## 3. Gateway and Lambda association

```bash
python scripts/connect_setup.py
```

This creates the gateway `pilotlight-tools` (MCP version `2025-03-26`, inbound JWT from the Connect instance's `/.well-known/openid-configuration`, allowed audience set to the gateway ID). It also adds the `pilotlight` Lambda target with the tools in `connect/tool_schema.json` and associates `pilotlight-session` with the instance.

## 4. AI agent domain

Connect admin website, **AI agents** (or **Amazon Q** on older consoles), **Add domain**. Create a domain. This is what the Connect assistant block attaches to the contact.

## 5. MCP integration

**Third-party applications**, **Add integration**. Integration type **MCP server**, gateway `pilotlight-tools`, instance association: your instance. Display name `pilotlight-tools`.

## 6. Security profile for the AI agent

**Users**, **Security profiles**, create `PilotLight AI agent`. Grant the `pilotlight-tools` integration's tools.

## 7. Orchestrator AI agent

**AI agent designer**, **AI agents**, **Create AI agent**:
- Type **Orchestration**, copy from **SelfServiceOrchestrator**, name `PilotLightOnCall`.
- **Tools**: **Add existing AI tool**, pick the five `pilotlight___*` tools. Keep **Complete**. Remove **Escalate**.
- **Prompt**: create a copy of `SelfServiceOrchestration` and paste the instructions from [agent_prompt.md](agent_prompt.md). Keep the `<message>` tag formatting.
- **Security profiles**: `PilotLight AI agent`.
- **Publish**. Then on the **AI agents** page, under **Default AI Agent Configurations**, set `PilotLightOnCall` in the **Self Service** row.

## 8. Conversational AI bot with Nova Sonic

**Routing**, **Flows**, **Conversational AI**, create `PilotLightBot` with the AI agent intent enabled, locale `en-US`. Then on the **Configuration** tab, select `en-US`, **Speech model**, **Edit**: model type **Speech-to-Speech**, voice provider **Amazon Nova Sonic**. **Build language**.

## 9. Contact flow "PilotLight Oncall"

Create a contact flow with these blocks in order:

1. **Set logging behavior**: enabled.
2. **Set voice**: provider Amazon, language English (US), voice **Matthew**. Other settings: **Override speaking style**, **Generative**. A non Nova Sonic voice breaks speech-to-speech.
3. **Connect assistant**: the domain from step 4.
4. **Invoke AWS Lambda function**: `pilotlight-session`, synchronous, timeout 8 seconds. Error branch continues to the next block, because tools fall back to the latest open incident.
5. **Get customer input**: Amazon Lex tab, bot `PilotLightBot`, alias live. Prompt: text to speech, set dynamically. Text:
   `Hi, this is Pilot Light with a production incident. $.Attributes.briefing What would you like to do?`
6. **Check contact attributes** on the Default branch: namespace **Lex**, key **Session attributes**, session attribute key `Tool`. Condition equals `Complete`.
7. **Disconnect** on every branch, including errors and no match.

**Save** and **Publish**. Copy the flow ID (the last part of the flow ARN) into `.env` as `CONNECT_CONTACT_FLOW_ID`.

## 10. Redeploy

```bash
cd infra && cdk deploy
```

The Incident Lambda reads `CONNECT_*` and `ONCALL_PHONE` at synth time.

## 11. Test

```bash
python scripts/test_call.py   # rings ONCALL_PHONE with a test incident, checkout stays healthy
scripts/status.sh             # call, tool, user and agent rows after hang-up
```

Then run the full demo: `traffic.sh`, `break.sh`, wait for the call, ask "what changed?", say "revert it", then "confirm".

## Troubleshooting

| Symptom | Check |
|---|---|
| Call never rings | Timeline row `Outbound call failed`. Outbound calling enabled, source number claimed, destination permitted. |
| Rings, then silence | Set voice uses a Nova Sonic voice with Generative style. Bot locale built after selecting Speech-to-Speech. |
| Agent answers but never uses tools | MCP integration associated with the instance. Gateway audience equals the gateway ID (rerun `connect_setup.py`). Tools granted in the AI agent security profile. |
| Agent reads the wrong incident | `pilotlight-session` logs. The prompt shows `{{$.Custom.incident_id}}` empty when UpdateSessionData did not run. |
| Fix refused after "confirm" | Timeline row `execute_remediation blocked` shows what the transcript heard. For an emergency demo only, set `REQUIRE_SPOKEN_CONFIRM=false` and redeploy. |
| No transcript after hang-up | `pilotlight-hangup` logs. The incident needs `contact_id`, written by the Incident Lambda. |
