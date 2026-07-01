from __future__ import annotations

import re
from typing import Any

from slack_bolt import App
from slack_sdk.errors import SlackApiError

from rescueops.data_loader import load_workspace, normalize_account_id, resolve_account_id
from rescueops.models import RescueCase
from rescueops.rescue_reasoner import generate_reasoned_text
from rescueops.risk_engine import scan_account
from rescueops.slack_blocks import format_evidence_source


ACCOUNT_ALIASES = {
    "acme": "acme",
    "acme robotics": "acme",
}

SIGNAL_SCOPE = "Slack conversations and connected business context"
EVENT_ID_KEYS = {
    "app_id",
    "bot_id",
    "channel_id",
    "enterprise_id",
    "team",
    "thread_ts",
    "ts",
    "user",
}


def infer_account_id(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    for alias, account_id in ACCOUNT_ALIASES.items():
        if alias in normalized:
            return account_id

    known_account = infer_known_account_from_text(text)
    if known_account:
        return known_account

    cleaned = re.sub(r"<@[^>]+>", " ", text)
    cleaned = re.sub(
        r"\b(scan|analyze|analyse|rescue|risk|account|please|for|the|customer|company|create|brief|draft|update|summary|status|about)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[^a-zA-Z0-9 ._-]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    return resolve_account_id(cleaned)


def infer_known_account_from_text(text: str) -> str | None:
    normalized_text = normalize_account_id(text)
    for account_id, account in load_workspace().get("accounts", {}).items():
        candidates = {
            normalize_account_id(account_id),
            normalize_account_id(account.get("name", "")),
        }
        if any(candidate and candidate in normalized_text for candidate in candidates):
            return account_id
    return None


def infer_account_id_from_event(event: dict[str, Any]) -> str | None:
    for candidate in walk_event_strings(event):
        account_id = infer_account_id(candidate)
        if account_id:
            return account_id
    return None


def walk_event_strings(value: Any, parent_key: str = "") -> tuple[str, ...]:
    if parent_key in EVENT_ID_KEYS:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        strings: list[str] = []
        for key, nested in value.items():
            strings.extend(walk_event_strings(nested, str(key)))
        return tuple(strings)
    if isinstance(value, list):
        strings = []
        for nested in value:
            strings.extend(walk_event_strings(nested, parent_key))
        return tuple(strings)
    return ()


def build_case_context(case: RescueCase) -> dict[str, Any]:
    top_evidence = sorted(case.evidence, key=lambda item: item.weight, reverse=True)[:6]
    return {
        "account": {
            "id": case.account.account_id,
            "name": case.account.name,
            "segment": case.account.segment,
            "renewal_date": case.account.renewal_date,
            "revenue_at_risk": case.account.revenue_at_risk,
        },
        "risk": {
            "score": case.risk_score,
            "level": case.risk_level,
            "signal_scope": SIGNAL_SCOPE,
            "evidence_items": case.metrics["evidence_items"],
            "expected_revenue_protected": case.metrics["expected_revenue_protected"],
            "mean_time_to_rescue_reduction_pct": case.metrics["mean_time_to_rescue_reduction_pct"],
            "evidence_source": case.metrics.get("evidence_source", "unknown"),
        },
        "root_causes": list(case.root_causes),
        "emerging_patterns": case.metrics.get("emerging_patterns", []),
        "recommended_actions": [
            {
                "title": action.title,
                "owner": action.owner,
                "due": action.due,
                "reason": action.reason,
            }
            for action in case.actions
        ],
        "top_evidence": [
            {
                "source": item.source,
                "channel": item.channel,
                "title": item.title,
                "text": item.text,
                "weight": item.weight,
                "tags": list(item.tags),
            }
            for item in top_evidence
        ],
    }


def build_dynamic_suggested_prompts(case: RescueCase) -> list[dict[str, str]]:
    protected = case.metrics["expected_revenue_protected"]
    root_cause = case.root_causes[0] if case.root_causes else "the highest-risk account signal"
    first_action = case.actions[0] if case.actions else None

    prompts = [
        {
            "title": f"Protect USD {protected:,}",
            "message": (
                f"Scan {case.account.name}, explain the {case.risk_score}% "
                f"{case.risk_level} risk, and recommend how to protect USD {protected:,}."
            ),
        },
        {
            "title": f"Explain {case.metrics['evidence_items']} signals",
            "message": (
                f"Explain the evidence chain for {case.account.name} and focus on: {root_cause}."
            ),
        },
        {
            "title": "Draft rescue update",
            "message": (
                f"Draft a customer-safe rescue update for {case.account.name} "
                f"with owner, checkpoint, and next action."
            ),
        },
    ]

    if first_action:
        prompts.append(
            {
                "title": f"Approve {first_action.owner}",
                "message": (
                    f"Turn the top recommendation for {case.account.name} into an "
                    f"approved Slack action owned by {first_action.owner}."
                ),
            }
        )

    return prompts[:4]


def build_agent_intro_text(account_id: str = "acme") -> str:
    case = scan_account(account_id)
    return (
        f"*RescueOps AI is watching {case.account.name}.*\n"
        f"Current risk: *{case.risk_score}% {case.risk_level}* | "
        f"Signals: *{case.metrics['evidence_items']}* | "
        f"Protectable: *USD {case.metrics['expected_revenue_protected']:,}*.\n"
        "Pick a suggested prompt or ask for a rescue brief, evidence chain, owner plan, or customer-safe update."
    )


def build_agent_scan_text(
    account_id: str,
    user_request: str = "scan account risk",
    action_token: str | None = None,
) -> str:
    case = scan_account(account_id, evidence_mode="rts", action_token=action_token)
    return build_grounded_case_brief(case, user_request)


def build_grounded_case_brief(case: RescueCase, user_request: str) -> str:
    context = build_case_context(case)
    top_causes = "\n".join(f"- {cause}" for cause in case.root_causes[:3])
    top_actions = "\n".join(
        f"- {action.title} | owner: {action.owner} | due: {action.due}"
        for action in case.actions[:3]
    )
    top_evidence = "\n".join(
        f"- `{item['channel']}` {item['title']}: {item['text']}"
        for item in context["top_evidence"][:3]
    )
    emerging_patterns = "\n".join(
        f"- {item['phrase']} | seen in {item['evidence_count']} signals"
        for item in context["emerging_patterns"][:3]
    ) or "- No repeated emerging pattern yet; using weighted evidence only."
    fallback = (
        f"*RescueOps AI brief: {case.account.name}*\n"
        f"Request understood: {user_request.strip() or 'scan account risk'}\n\n"
        f"*Decision*\n"
        f"{case.account.name} is at *{case.risk_score}% {case.risk_level} risk* "
        f"with *USD {case.metrics['revenue_at_risk']:,}* exposed and "
        f"*USD {case.metrics['expected_revenue_protected']:,}* expected protectable.\n\n"
        f"*Context analyzed*\n"
        f"- Signals analyzed: {case.metrics['evidence_items']} across Slack and business context\n"
        f"- Evidence source: {format_evidence_source(case.metrics.get('evidence_source', 'unknown'))}\n"
        f"- Renewal date: {case.account.renewal_date}\n"
        f"- Mean Time To Rescue: {case.metrics['old_time_to_plan']} -> {case.metrics['new_time_to_plan']}\n\n"
        f"*Why now*\n{top_causes}\n\n"
        f"*Evidence highlights*\n{top_evidence}\n\n"
        f"*Emerging patterns discovered*\n{emerging_patterns}\n\n"
        f"*Recommended rescue path*\n{top_actions}\n\n"
        "Next: approve the rescue workflow from the Slack card."
    )
    return generate_reasoned_text(
        case,
        task="case_brief",
        fallback=fallback,
        user_request=user_request,
    )


def build_suggested_prompts_payload(account_id: str = "acme") -> dict[str, Any]:
    case = scan_account(account_id)
    return {
        "title": f"RescueOps prompts for {case.account.name}",
        "prompts": build_dynamic_suggested_prompts(case),
    }


def register_ai_handlers(app: App) -> None:
    @app.event("assistant_thread_started")
    def handle_assistant_thread_started(ack, event, client, logger) -> None:
        ack()
        thread = event.get("assistant_thread", {})
        channel_id = thread.get("channel_id")
        thread_ts = thread.get("thread_ts")
        if not channel_id or not thread_ts:
            return

        account_id = infer_account_id_from_event(event) or "acme"
        prompt_payload = build_suggested_prompts_payload(account_id)
        try:
            client.api_call(
                "assistant.threads.setSuggestedPrompts",
                json={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    **prompt_payload,
                },
            )
        except SlackApiError as error:
            logger.info("Could not set assistant prompts: %s", error.response.get("error"))

        try:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=build_agent_intro_text(account_id),
            )
        except SlackApiError as error:
            logger.info("Could not post assistant intro: %s", error.response.get("error"))

    @app.event("assistant_thread_context_changed")
    def handle_assistant_context_changed(ack) -> None:
        ack()

    @app.event("app_mention")
    def handle_app_mention(event: dict[str, Any], say) -> None:
        text = event.get("text", "")
        account_id = infer_account_id(text)
        if not account_id:
            say("Mention an account, for example `Acme Robotics`, and I can generate a live RescueOps brief.")
            return
        say(build_agent_scan_text(account_id, text, action_token=event.get("action_token")))
