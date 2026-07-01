from __future__ import annotations

import os

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

from rescueops.data_loader import resolve_account_id
from rescueops.rescue_reasoner import generate_reasoned_text
from rescueops.risk_engine import scan_account
from rescueops.rts_search import check_rts_availability
from rescueops.slack_ai_agent import register_ai_handlers
from rescueops.slack_blocks import format_evidence_source, render_blocks, render_followup_blocks


CLOSED_CASES: set[str] = set()


def scan_for_workflow(account_id: str, evidence_mode: str | None = None):
    mode = evidence_mode or os.getenv("RESCUEOPS_EVIDENCE_MODE") or "rts"
    return scan_account(account_id, evidence_mode=mode)


def source_uses_live_rts(source: str) -> bool:
    return "slack-rts" in source or "hybrid-rts" in source


def build_command_help_text() -> str:
    return (
        "*RescueOps commands*\n"
        "- `/rescueops scan acme` - run the live Slack Real-Time Search workflow for any account name.\n"
        "- `/rescueops live acme` - alias for the live RTS workflow.\n"
        "- `/rescueops demo acme` - run the deterministic demo scenario only when needed.\n"
        "- `/rescueops hybrid acme` - merge live RTS with demo baseline evidence.\n"
        "- `/rescueops rts-check` - verify whether Slack RTS is reachable in this workspace."
    )


def build_scan_response_text(case, forced_live: bool = False) -> str:
    source = case.metrics.get("evidence_source", "unknown")
    source_label = format_evidence_source(source)
    if forced_live and not source_uses_live_rts(source):
        return (
            f"RTS live scan for {case.account.name} could not read live Slack evidence yet; "
            f"showing {source_label}. Run `/rescueops rts-check` for the exact blocker."
        )
    if source_uses_live_rts(source):
        return f"Live RTS Revenue Rescue scan complete for {case.account.name}. Evidence source: {source_label}."
    return f"Revenue Rescue scan complete for {case.account.name}. Evidence source: {source_label}."


def build_rts_check_text(action_token: str | None = None) -> str:
    status = check_rts_availability(action_token=action_token)
    ready = "ready" if status.get("ok") else "not ready"
    enabled = "yes" if status.get("enabled") else "no"
    return (
        "*RescueOps Real-Time Search check*\n"
        f"API status: *{ready}*\n"
        f"Slack status code: `{status.get('status')}`\n"
        f"Semantic AI search enabled: *{enabled}*\n"
        f"Detail: {status.get('detail')}\n\n"
        "Live proof path: run `/rescueops live acme` with `SLACK_USER_TOKEN`, or mention the app from an app/assistant event so Slack supplies an action token."
    )


def build_rescue_plan_text(account_id: str) -> str:
    case = scan_for_workflow(account_id)
    actions = "\n".join(
        f"- {action.title} | owner: {action.owner} | due: {action.due}"
        for action in case.actions
    ) or "- No rescue action recommended until live evidence is found."
    causes = "\n".join(f"- {cause}" for cause in case.root_causes) or "- No root cause detected yet."
    fallback = (
        f"*Revenue Rescue Plan: {case.account.name}*\n"
        f"Risk: *{case.risk_score}% {case.risk_level}*\n"
        f"Revenue at risk: *USD {case.metrics['revenue_at_risk']:,}*\n"
        f"Expected protected revenue: *USD {case.metrics['expected_revenue_protected']:,}*\n"
        f"Mean Time To Rescue: *{case.metrics['old_time_to_plan']} -> {case.metrics['new_time_to_plan']}* "
        f"({case.metrics['mean_time_to_rescue_reduction_pct']}% reduction)\n"
        f"Evidence source: *{format_evidence_source(case.metrics.get('evidence_source', 'unknown'))}*\n\n"
        f"*Root causes*\n{causes}\n\n"
        f"*Approved actions*\n{actions}"
    )
    return generate_reasoned_text(case, task="rescue_plan", fallback=fallback)

def build_owner_update_text(account_id: str) -> str:
    case = scan_for_workflow(account_id)
    if not case.actions:
        return (
            f"*Owner assignment pending for {case.account.name}*\n"
            "No live evidence-backed rescue action is ready yet. Run `/rescueops rts-check` and rescan when RTS is available."
        )

    action_lines = "\n".join(
        f"- {action.owner} owns `{action.title}` | due: {action.due}"
        for action in case.actions[:4]
    )
    first_due = case.actions[0].due
    fallback = (
        f"*Owners assigned for {case.account.name}*\n"
        f"{action_lines}\n"
        f"Next checkpoint: {first_due}.\n"
        f"Outcome target: protect *USD {case.metrics['expected_revenue_protected']:,}* of expected revenue."
    )
    return generate_reasoned_text(case, task="owner_update", fallback=fallback)

def build_customer_update_text(account_id: str) -> str:
    case = scan_for_workflow(account_id)
    primary_cause = case.root_causes[0] if case.root_causes else "the latest customer risk signal"
    top_action = case.actions[0] if case.actions else None
    top_evidence = sorted(case.evidence, key=lambda item: item.weight, reverse=True)[:1]
    evidence_hint = top_evidence[0].title if top_evidence else "live Slack evidence is still pending"

    if top_action:
        action_sentence = f"{top_action.owner} is driving `{top_action.title}` with checkpoint: {top_action.due}."
    else:
        action_sentence = "The team is waiting for live evidence before naming an accountable owner."

    fallback = (
        f"*Customer-safe rescue update posted for {case.account.name}*\n"
        f"We identified {primary_cause.lower()} from {evidence_hint}. "
        f"{action_sentence} "
        f"Coordination is happening in #rescue-{account_id}."
    )
    return generate_reasoned_text(case, task="customer_update", fallback=fallback)

def build_score_explanation_text(account_id: str) -> str:
    case = scan_for_workflow(account_id)
    components = case.metrics["score_components"]
    evidence_lines = "\n".join(
        f"- `{item.channel}` {item.title} | weight {item.weight} | source {item.source}"
        for item in sorted(case.evidence, key=lambda item: item.weight, reverse=True)[:5]
    )
    pattern_lines = render_emerging_pattern_lines(case)
    return (
        f"*Why RescueOps scored {case.account.name} at {case.risk_score}%*\n"
        f"Evidence source: *{format_evidence_source(case.metrics.get('evidence_source', 'unknown'))}*\n"
        f"Signal score: *{components['raw_signal_score']}* from {case.metrics['evidence_items']} evidence items.\n"
        f"Diversity bonus: *{components['diversity_bonus']}* because the risk appears across "
        f"{case.metrics['source_count']} systems and {case.metrics['channel_count']} channels.\n"
        f"Emerging pattern bonus: *{components['emerging_pattern_bonus']}* from repeated phrases discovered in the scanned messages.\n"
        f"Final score is capped at *100%* to keep the risk scale readable.\n\n"
        f"*Top weighted evidence*\n{evidence_lines}\n\n"
        f"*Emerging patterns discovered*\n{pattern_lines}\n\n"
        f"*Result*\n{case.risk_level.title()} revenue risk with *USD {case.metrics['revenue_at_risk']:,}* exposed."
    )


def render_emerging_pattern_lines(case) -> str:
    patterns = case.metrics.get("emerging_patterns", [])
    if not patterns:
        return "- No repeated emerging pattern yet; using weighted evidence only."
    return "\n".join(
        f"- {item['phrase']} | {item['evidence_count']} signals | score {item['score']}"
        for item in patterns[:3]
    )


def build_impact_receipt_text(account_id: str) -> str:
    case = scan_for_workflow(account_id)
    owners = ", ".join(dict.fromkeys(action.owner for action in case.actions[:4]))
    next_checkpoint = case.actions[0].due if case.actions else "No checkpoint scheduled yet"
    return (
        f"*RescueOps Impact Receipt: {case.account.name}*\n"
        f"Revenue at risk found: *USD {case.metrics['revenue_at_risk']:,}*\n"
        f"Expected protected revenue: *USD {case.metrics['expected_revenue_protected']:,}*\n"
        f"Signals converted into action: *{case.metrics['evidence_items']}*\n"
        f"Evidence source: *{format_evidence_source(case.metrics.get('evidence_source', 'unknown'))}*\n"
        f"Diagnosis time: *{case.metrics['old_time_to_diagnose']} -> {case.metrics['new_time_to_diagnose']}*\n"
        f"Rescue plan time: *{case.metrics['old_time_to_plan']} -> {case.metrics['new_time_to_plan']}*\n"
        f"Mean Time To Rescue reduction: *{case.metrics['mean_time_to_rescue_reduction_pct']}%*\n"
        f"Owners activated: {owners or 'No owner activated yet'}\n"
        f"Next checkpoint: {next_checkpoint}.\n"
        f"Case status: *Closed. New scans create a fresh RescueOps case.*"
    )


def find_channel_id(client, channel_name: str) -> str | None:
    cursor = None
    while True:
        result = client.conversations_list(types="public_channel", limit=200, cursor=cursor)
        for channel in result.get("channels", []):
            if channel.get("name") == channel_name:
                return channel.get("id")
        cursor = result.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            return None


def get_or_create_rescue_room(client, account_id: str) -> tuple[str | None, str | None]:
    channel_name = f"rescue-{account_id}"
    channel_id = find_channel_id(client, channel_name)
    if channel_id:
        return channel_id, None

    try:
        result = client.conversations_create(name=channel_name, is_private=False)
        return result["channel"]["id"], None
    except SlackApiError as error:
        slack_error = error.response.get("error", "unknown_error")
        if slack_error == "missing_scope":
            return None, "I need the `channels:manage` bot scope. Add it, reinstall, then restart me."
        return None, f"Could not create #{channel_name}: {slack_error}"


def create_rescue_room(client, account_id: str) -> str:
    channel_id, error = get_or_create_rescue_room(client, account_id)
    if error:
        return error
    if not channel_id:
        return "Could not resolve the rescue channel."

    client.chat_postMessage(channel=channel_id, text=build_rescue_plan_text(account_id))
    return f"Created <#{channel_id}> and posted the approved rescue plan."


def assign_owner(client, account_id: str) -> str:
    channel_id, error = get_or_create_rescue_room(client, account_id)
    if error:
        return error
    if not channel_id:
        return "Could not resolve the rescue channel."

    client.chat_postMessage(channel=channel_id, text=build_owner_update_text(account_id))
    return f"Assigned owners and posted the ownership update in <#{channel_id}>."


def close_case(account_id: str) -> None:
    CLOSED_CASES.add(account_id)


def reopen_case(account_id: str) -> None:
    CLOSED_CASES.discard(account_id)


def is_case_closed(account_id: str) -> bool:
    return account_id in CLOSED_CASES


def build_closed_case_text(account_id: str) -> str:
    case = scan_for_workflow(account_id)
    return (
        f"*RescueOps case already closed: {case.account.name}*\n"
        f"The impact receipt is the final audit record for this rescue. "
        f"Run `/rescueops scan {account_id}` to create a fresh case from current evidence."
    )


def render_terminal_blocks(message: str) -> list[dict]:
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": message},
        }
    ]


def post_audit_followup(
    respond,
    message: str,
    account_id: str,
    selected_action_id: str | None = None,
) -> None:
    respond(
        response_type="in_channel",
        replace_original=False,
        delete_original=False,
        text=message,
        blocks=render_followup_blocks(message, account_id, selected_action_id=selected_action_id),
    )


def post_terminal_followup(respond, message: str) -> None:
    respond(
        response_type="in_channel",
        replace_original=False,
        delete_original=False,
        text=message,
        blocks=render_terminal_blocks(message),
    )


def post_private_error(respond, message: str) -> None:
    respond(
        response_type="ephemeral",
        replace_original=False,
        delete_original=False,
        text=message,
    )


def create_app() -> App:
    app = App(token=os.environ["SLACK_BOT_TOKEN"], token_verification_enabled=False)
    register_ai_handlers(app)

    @app.command("/rescueops")
    def rescueops_command(ack, respond, command) -> None:
        ack()
        text = command.get("text", "").strip()
        parts = text.split()
        if not parts or parts[0].lower() == "help":
            respond(response_type="ephemeral", text=build_command_help_text())
            return

        command_name = parts[0].lower()
        if command_name in {"rts-check", "status"}:
            respond(response_type="in_channel", text=build_rts_check_text())
            return

        account_query = " ".join(parts[1:]).strip()
        if not account_query or command_name not in {"scan", "live", "rts", "demo", "hybrid"}:
            respond(response_type="ephemeral", text=build_command_help_text())
            return

        account_id = resolve_account_id(account_query)
        reopen_case(account_id)
        if command_name == "demo":
            evidence_mode = "seeded"
        elif command_name == "hybrid":
            evidence_mode = "hybrid"
        elif command_name in {"live", "rts"}:
            evidence_mode = "rts"
        else:
            evidence_mode = os.getenv("RESCUEOPS_EVIDENCE_MODE") or "rts"
        forced_live = evidence_mode == "rts"
        case = scan_account(account_id, evidence_mode=evidence_mode)
        respond(
            response_type="in_channel",
            text=build_scan_response_text(case, forced_live=forced_live),
            blocks=render_blocks(case),
        )

    @app.action("explain_score")
    @app.action("create_rescue_room")
    @app.action("assign_owner")
    @app.action("post_rescue_plan")
    @app.action("impact_receipt")
    def handle_action(ack, respond, body, client) -> None:
        ack()
        action = body["actions"][0]
        action_id = action["action_id"]
        account_id = action.get("value", "acme")

        if is_case_closed(account_id):
            message = build_closed_case_text(account_id)
            try:
                post_terminal_followup(respond, message)
            except SlackApiError as error:
                slack_error = error.response.get("error", "unknown_error")
                post_private_error(respond, f"Could not post the RescueOps update: {slack_error}")
            return

        if action_id == "explain_score":
            message = build_score_explanation_text(account_id)
            terminal = False
        elif action_id == "create_rescue_room":
            message = create_rescue_room(client, account_id)
            terminal = False
        elif action_id == "assign_owner":
            message = assign_owner(client, account_id)
            terminal = False
        elif action_id == "impact_receipt":
            message = build_impact_receipt_text(account_id)
            close_case(account_id)
            terminal = True
        else:
            message = build_customer_update_text(account_id)
            terminal = False

        try:
            if terminal:
                post_terminal_followup(respond, message)
            else:
                post_audit_followup(respond, message, account_id, selected_action_id=action_id)
        except SlackApiError as error:
            slack_error = error.response.get("error", "unknown_error")
            post_private_error(respond, f"Could not post the RescueOps update: {slack_error}")

    return app


def main() -> None:
    app = create_app()
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    print("RescueOps Socket Mode app is running.")
    handler.start()


if __name__ == "__main__":
    main()
