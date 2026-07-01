from __future__ import annotations

from rescueops.models import RescueCase


def render_blocks(case: RescueCase) -> list[dict]:
    account = case.account
    metrics = case.metrics
    risk_text = (
        f"*{account.name}* has a *{case.risk_score}% {case.risk_level} risk* "
        f"with *USD {metrics['revenue_at_risk']:,}* at risk."
    )

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Revenue Rescue: {account.name}",
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": risk_text},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Risk score:*\n{case.risk_score}%"},
                {"type": "mrkdwn", "text": f"*Renewal date:*\n{account.renewal_date}"},
                {"type": "mrkdwn", "text": f"*Evidence found:*\n{metrics['evidence_items']} signals"},
                {"type": "mrkdwn", "text": f"*First warning:*\n{metrics['first_warning_days_ago']} days ago"},
                {"type": "mrkdwn", "text": f"*Time to diagnose:*\n{metrics['old_time_to_diagnose']} -> {metrics['new_time_to_diagnose']}"},
                {"type": "mrkdwn", "text": f"*Expected protected:*\nUSD {metrics['expected_revenue_protected']:,}"},
                {"type": "mrkdwn", "text": f"*Evidence source:*\n{format_evidence_source(metrics.get('evidence_source', 'unknown'))}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Root causes*\n" + render_root_causes(case),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Top evidence*\n" + render_evidence(case),
            },
        },
        render_action_block(account.account_id),
    ]

    return blocks


def format_evidence_source(source: str) -> str:
    labels = {
        "seeded": "Demo workspace evidence",
        "seeded-fallback": "Demo workspace evidence",
        "slack-rts": "Live Slack RTS",
        "hybrid-rts": "Live Slack RTS + demo baseline",
        "mcp": "MCP business context",
    }
    parts = source.split("+")
    rendered = [labels.get(part, part.replace("-", " ").title()) for part in parts]
    return " + ".join(rendered)


def render_followup_blocks(text: str, account_id: str, selected_action_id: str | None = None) -> list[dict]:
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": text},
        },
        render_action_block(
            account_id,
            selected_action_id=selected_action_id,
            show_default_primary=False,
        ),
    ]


def render_action_block(
    account_id: str,
    selected_action_id: str | None = None,
    show_default_primary: bool = True,
) -> dict:
    primary_action_id = selected_action_id
    if primary_action_id is None and show_default_primary:
        primary_action_id = "create_rescue_room"

    elements = []
    for action_id, label in (
        ("explain_score", "Explain score"),
        ("create_rescue_room", "Create rescue room"),
        ("assign_owner", "Assign owner"),
        ("post_rescue_plan", "Post rescue update"),
        ("impact_receipt", "Impact receipt"),
    ):
        button = {
            "type": "button",
            "text": {"type": "plain_text", "text": label},
            "action_id": action_id,
            "value": account_id,
        }
        if action_id == primary_action_id:
            button["style"] = "primary"
        elements.append(button)

    return {
        "type": "actions",
        "elements": elements,
    }


def render_root_causes(case: RescueCase) -> str:
    if not case.root_causes:
        return "- No root cause detected yet."
    return "\n".join(f"- {item}" for item in case.root_causes)


def render_evidence(case: RescueCase) -> str:
    top_items = sorted(case.evidence, key=lambda item: item.weight, reverse=True)[:5]
    if not top_items:
        return "- No live evidence found yet."
    return "\n".join(
        f"- `{item.channel}` {item.title}: {item.text}"
        for item in top_items
    )