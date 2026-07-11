# RescueOps Runtime

RescueOps runs as a Slack Socket Mode worker. The worker maintains an outbound Slack connection and handles slash commands, Real-Time Search checks, and interactive Block Kit actions without requiring a public webhook URL.

## Runtime Requirements

- Python 3.11+
- Outbound internet access to Slack APIs
- Slack app with Socket Mode enabled
- Bot token with the scopes listed in `slack/rescueops_manifest.example.yaml`
- App-level token with Socket Mode permissions
- Optional user token for slash-command Real-Time Search proof

## Environment

Use `deploy/rescueops.env.example` as the template:

```bash
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-socket-mode-app-token
SLACK_USER_TOKEN=xoxp-your-user-token-for-rts-proof
RESCUEOPS_EVIDENCE_MODE=rts
RESCUEOPS_USE_MCP=1
RESCUEOPS_REASONER_MODE=deterministic
```

Real token values must be supplied through the runtime environment and should not be committed.

## Run

```bash
python -m rescueops.socket_app
```

`deploy/rescueops.service` contains an optional `systemd` unit for running the worker as a managed service.

## Slack Proof Commands

```text
/rescueops rts-check
/rescueops live acme
```

Expected live evidence label:

```text
Evidence source: Live Slack RTS + MCP business context
```
