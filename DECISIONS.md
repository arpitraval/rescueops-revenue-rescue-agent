# Decisions

## Category

Primary category: New Slack Agent using the Real-Time Search (RTS) API.

Reason: the project is about finding live risk signals across Slack before they become formal CRM or support updates. The app verifies RTS with `assistant.search.info` and pulls live evidence with `assistant.search.context`.

## Product name

RescueOps for Slack.

## Demo wedge

Revenue Rescue for Slack.

This is narrower and more concrete than a general agent. The money, urgency, workflow, and Slack-native impact are clear in under 30 seconds.

## Signature metric

Mean Time To Rescue.

The demo shows the time from first hidden warning signal to an approved rescue plan, using live Slack RTS evidence plus MCP business context when enabled.

## Why not a generic chatbot

Generic chatbots answer questions. RescueOps runs an outcome loop:

detect -> diagnose -> recommend -> approve -> execute -> verify.

## Why this is different

Most teams will build assistants that summarize or answer. RescueOps presents an operational system with business metrics, evidence, actions, and a defensible before/after impact.

## Why optional open-source reasoning

The score should stay explainable and testable, but rescue plans need language judgment because every customer thread is different. RescueOps therefore keeps search, scoring, evidence weighting, owners, and metrics deterministic, then optionally lets Qwen3 8B rewrite the final Slack brief from grounded case JSON.

This gives the demo a stronger AI layer without making the workflow depend on a paid model key or trusting an LLM to invent facts.
## Why Qwen stays in scope

Qwen is not the qualifying hackathon technology by itself. RescueOps qualifies through Slack Real-Time Search as the primary capability, with Slack AI surfaces and MCP server integration as supporting capabilities. The open-source model is only an optional grounded writing layer that turns the current `RescueCase` into clearer rescue communication after Slack evidence, scoring, owners, and actions are already computed.
