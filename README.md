# RescueOps for Slack

RescueOps is a Slack-native revenue rescue agent that uses Slack Real-Time Search and Slack AI surfaces to find hidden customer risk inside work conversations, explain the evidence, and launch an approved rescue workflow.

## Core Technology

Primary capability: **Real-Time Search API**

Agent experience: **Slack AI capabilities**

Supporting capability: **MCP server integration** for business-system evidence.

RescueOps uses:

- `assistant.search.info` to verify whether Slack Real-Time Search is reachable in the workspace.
- `assistant.search.context` to pull live Slack evidence for an account when RTS is enabled.
- Slack AI assistant hooks for dynamic suggested prompts and grounded account-risk briefs.
- Slack Block Kit and interactive actions to approve rescue steps inside Slack.
- MCP-style connectors for CRM, support, incident, and revenue context.

## Demo Scenario

Account: Acme Robotics

Problem: SSO reliability issues are scattered across sales, support, incidents, engineering, and exec channels. Renewal/expansion worth USD 500,000 is at risk.

RescueOps:

1. Searches live Slack evidence through the official RTS API.
2. Scores the account from current evidence.
3. Explains root causes and weighted signals.
4. Shows expected protected revenue.
5. Creates `#rescue-acme`.
6. Assigns owners.
7. Posts a customer-safe recovery update.
8. Produces an impact receipt for the audit trail.

## Live RTS Proof

Run the app, then use these commands in Slack:

```text
/rescueops rts-check
/rescueops scan acme
/rescueops live acme
```

Expected behavior:

- `/rescueops rts-check` calls Slack `assistant.search.info` and reports whether RTS/AI search is reachable.
- `/rescueops scan acme` runs the live RTS workflow by default.
- `/rescueops live acme` is an explicit alias for the same live RTS workflow.
- If Slack returns live evidence, the card shows `Evidence source: Live Slack RTS`.
- If Slack blocks the call in a sandbox, the card can use demo workspace evidence and tells you to run `rts-check`.
- `/rescueops demo acme` is the only deterministic fallback demo command.
- `/rescueops hybrid acme` is an optional comparison mode that merges RTS with baseline evidence.

Slack notes from the official API behavior:

- Bot-token RTS calls require an `action_token` from a Slack event.
- User-token RTS calls do not require an `action_token`.
- Add the search scopes, reinstall the app, then restart the Socket Mode process.

## Dynamic Evidence, Not a Canned Chatbot

The demo includes stable fixture data only as a named fallback, but the submission path is live RTS:

- `/rescueops scan acme`, `/rescueops scan Globex Corp`, and app mentions use `RESCUEOPS_EVIDENCE_MODE=rts` by default.
- `rescueops/data_loader.py` resolves known fixture accounts and creates ad hoc account records for unknown live account names.
- `rescueops/rts_search.py` builds RTS queries from `data/risk_taxonomy.json`, calls Slack RTS, and converts returned Slack snippets into weighted evidence.
- `RESCUEOPS_EVIDENCE_MODE=rts` forces the live API path and only falls back when Slack does not return evidence.
- `RESCUEOPS_EVIDENCE_MODE=hybrid` is optional and merges live RTS with baseline evidence for comparison.
- `RESCUEOPS_USE_MCP=1` enriches Slack evidence with MCP business-system signals.
- Revenue at risk can be read from configured account data or inferred from money amounts found in live evidence.
- The risk card, explanation, owner plan, rescue room, and impact receipt are generated from the current `RescueCase`, not a static message.
- Risk tags and signal weights are loaded from `data/risk_taxonomy.json`, so teams can tune the scoring model without changing application code.
- Rescue owners, action templates, and due dates are loaded from `data/rescue_policy.json`, so teams can map actions to Slack user groups through environment variables.
- `rescueops/signal_discovery.py` mines repeated phrases from the current evidence set, so emerging workspace-specific patterns can influence the explanation and bounded score bonus.

## How Live Chats Become Patterns

1. `rescueops/rts_search.py` builds account-specific queries from the configurable taxonomy, calls Slack Real-Time Search, and collects matching Slack snippets for the account.
2. `rescueops/evidence_scoring.py` maps each snippet through the configurable risk taxonomy.
3. `rescueops/signal_discovery.py` extracts repeated phrases from the scanned messages and ranks them by evidence count, channel spread, source spread, and evidence weight.
4. `rescueops/risk_engine.py` combines weighted evidence, diversity, and emerging-pattern bonus into the final RescueCase.
5. `rescueops/slack_blocks.py` and `rescueops/slack_ai_agent.py` turn that RescueCase into the Slack card, score explanation, owner plan, rescue plan, and AI brief.

The taxonomy is not the demo output. It is the starting lens. The current Slack evidence determines which signals, phrases, scores, and actions appear for each scan.

## Optional Open-Source Reasoning

RescueOps can add a local open-source reasoning model after the evidence pipeline has built a grounded `RescueCase`.

Default model: **Qwen3 8B** through Ollama (`qwen3:8b`). Qwen3 is a strong fit because it supports reasoning mode, agentic/tool use, long context, and local deployment without paid model keys. Use `qwen3:14b` only as an optional quality upgrade on stronger hardware.

The model is not allowed to invent the case. It receives only grounded RescueOps JSON: account, current evidence, score components, root causes, actions, owners, due dates, and impact metrics. If the model returns unsupported money or an ungrounded answer, RescueOps falls back to the deterministic response.

Enable local reasoning:

```powershell
ollama pull qwen3:8b
$env:RESCUEOPS_REASONER_MODE="ollama"
$env:RESCUEOPS_LLM_ENDPOINT="http://localhost:11434/api/chat"
$env:RESCUEOPS_LLM_MODEL="qwen3:8b"
```

Optional OpenAI-compatible endpoint:

```powershell
$env:RESCUEOPS_REASONER_MODE="openai-compatible"
$env:RESCUEOPS_LLM_ENDPOINT="http://localhost:8000/v1/chat/completions"
$env:RESCUEOPS_LLM_MODEL="Qwen/Qwen3-8B"
```

Leave these variables unset for the stable deterministic demo path.

## Slack App Scopes

The example manifest in `slack/rescueops_manifest.example.yaml` includes the scopes used by the demo:

- `assistant:write` for Slack AI suggested prompts.
- `search:read.public`, `search:read.files`, and `search:read.users` for bot-token RTS.
- Optional user search scopes for slash-command RTS proof with `SLACK_USER_TOKEN`.
- `commands`, `chat:write`, `app_mentions:read`, `channels:read`, and `channels:manage` for the Slack workflow.

## Setup

From a fresh clone on Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Then configure Slack tokens in the current PowerShell session before running the Socket Mode app. Do not commit tokens.

## Runtime

```powershell
$env:SLACK_BOT_TOKEN="xoxb-..."
$env:SLACK_APP_TOKEN="xapp-..."
$env:RESCUEOPS_EVIDENCE_MODE="rts"
$env:RESCUEOPS_USE_MCP="1"
.\.venv\Scripts\python.exe -m rescueops.socket_app
```

For slash-command live RTS proof, set a user token with the required user search scopes:

```powershell
$env:SLACK_USER_TOKEN="xoxp-..."
/rescueops scan acme
```

Do not commit Slack tokens.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## One-line Pitch

RescueOps turns Slack from the place where revenue risk is discussed into the place where revenue risk is detected, explained, approved, and rescued.
