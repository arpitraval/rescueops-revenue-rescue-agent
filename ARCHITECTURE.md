# Architecture

## Product Loop

```mermaid
flowchart LR
    subgraph slack_platform["Slack Platform"]
        workspace_signals["Workspace signals"] --> realtime_search["Real-Time Search API"]
    end

    subgraph rescueops_service["RescueOps Agent Service"]
        rts_adapter["RTS evidence adapter"] --> evidence_graph["Evidence graph"]
        evidence_graph --> rescuecase_engine["RescueCase engine"]
        rescuecase_engine --> action_planner["Action planner"]
        mcp_context["MCP business context"] --> rescuecase_engine
        signal_discovery["Signal discovery"] --> rescuecase_engine
        grounded_reasoning["Grounded reasoning layer"] --> action_planner
    end

    subgraph outcomes["Outcomes in Slack"]
        agent_response["Agent response"] --> rescue_execution["Rescue execution"]
        rescue_execution --> impact_receipt["Impact receipt"]
    end

    realtime_search --> rts_adapter
    action_planner --> agent_response
```

## Live Evidence Path

RescueOps uses Slack Real-Time Search as the primary evidence path:

1. Capability check: `rescueops/rts_search.py` calls `assistant.search.info` through `/rescueops rts-check`.
2. Live evidence scan: `/rescueops scan <account>` and `/rescueops live <account>` call `assistant.search.context` and convert live Slack snippets into weighted evidence.
3. Business enrichment: when `RESCUEOPS_USE_MCP=1`, `rescueops/mcp_client.py` calls the local MCP server for CRM, support, incident, and ownership context.
4. Demo fallback: `data/demo_workspace.json` is used only for tests, `/rescueops demo`, or when Slack credentials/access are unavailable.

Live Slack evidence, MCP context, and discovered patterns feed the same `RescueCase` pipeline, so the Slack card, score explanation, owner plan, rescue room, customer-safe update, and impact receipt are generated from the evidence returned at scan time.

## Work Risk Graph

```mermaid
flowchart TD
    A["Account"] --> B["Slack and business evidence"]
    B --> C["Risk score"]
    C --> D["Root causes"]
    D --> E["Owners"]
    E --> F["Approved actions"]
    F --> G["Protected revenue outcome"]
```

## Runtime Components

- `rescueops/rts_search.py` verifies Slack Real-Time Search with `assistant.search.info`, queries live Slack evidence with `assistant.search.context`, and converts returned snippets into evidence.
- `rescueops/evidence_provider.py` chooses live RTS, demo, hybrid, or MCP-enriched evidence modes.
- `rescueops/mcp_client.py` and `rescueops/mcp_business_server.py` implement the MCP server integration for CRM, support, Jira, and incident-style business context.
- `rescueops/signal_discovery.py` mines repeated phrases from the current evidence set so workspace-specific patterns appear in score explanations and Slack AI briefs.
- `rescueops/risk_engine.py` turns current evidence into score components, root causes, owners, rescue actions, and impact metrics.
- `rescueops/rescue_policy.py` loads policy-driven owner mappings, due dates, and action templates from `data/rescue_policy.json`.
- `rescueops/rescue_reasoner.py` optionally calls a local Qwen3/OpenAI-compatible reasoning model to rewrite case briefs, rescue plans, owner updates, and customer-safe updates from grounded `RescueCase` JSON. Guardrails strip reasoning traces and reject unsupported money claims before posting to Slack.
- `rescueops/slack_ai_agent.py` handles Slack AI assistant prompts and app-mention briefs, forwarding Slack event `action_token` into the RTS path when Slack provides it.
- `rescueops/socket_app.py` executes the Slack workflow through `/rescueops`, Block Kit buttons, channel creation, and message posting.

## Commands

```text
/rescueops rts-check
/rescueops scan acme
/rescueops live acme
/rescueops demo acme
```

`/rescueops rts-check` proves Slack RTS availability and `/rescueops live acme` demonstrates the live proof path: Live Slack RTS + MCP business context. `/rescueops scan acme` and `/rescueops live acme` run the live RTS lane and display the evidence source on the Slack card. `/rescueops demo acme` is the named deterministic fallback. `/rescueops hybrid acme` is an optional comparison mode.