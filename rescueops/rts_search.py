from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any, Callable

from rescueops.evidence_scoring import estimate_weight, infer_tags, load_risk_taxonomy
from rescueops.models import Account, Evidence


ClientFactory = Callable[[str], Any]


def build_queries(account: Account) -> tuple[str, ...]:
    taxonomy = load_risk_taxonomy()
    search_config = taxonomy.get("search", {})
    signal_patterns = {
        signal["tag"]: tuple(signal.get("patterns", ()))
        for signal in taxonomy.get("signals", ())
    }
    max_queries = int(search_config.get("max_queries", 3))
    intents = tuple(search_config.get("intents", ())) or default_search_intents(signal_patterns)

    queries: list[str] = []
    for intent in intents[:max_queries]:
        terms: list[str] = list(intent.get("terms", ()))
        for tag in intent.get("tags", ()):
            terms.extend(signal_patterns.get(tag, ())[:2])
        query_terms = " ".join(dedupe_terms(terms)[:8])
        queries.append(f'"{account.name}" {query_terms}'.strip())

    return tuple(queries) or (f'"{account.name}" risk',)


def default_search_intents(signal_patterns: dict[str, tuple[str, ...]]) -> tuple[dict[str, object], ...]:
    return tuple(
        {"name": tag, "tags": (tag,), "terms": patterns[:1]}
        for tag, patterns in signal_patterns.items()
    )


def dedupe_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        normalized = " ".join(str(term).split()).lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(str(term))
    return deduped


def resolve_rts_token(token: str | None = None) -> str | None:
    return token or os.getenv("SLACK_USER_TOKEN") or os.getenv("SLACK_BOT_TOKEN")


def resolve_action_token(action_token: str | None = None) -> str | None:
    return action_token or os.getenv("SLACK_ACTION_TOKEN")


def make_web_client(token: str, client_factory: ClientFactory | None = None) -> Any:
    if client_factory:
        return client_factory(token)

    from slack_sdk import WebClient

    return WebClient(token=token)


def check_rts_availability(
    token: str | None = None,
    action_token: str | None = None,
    client_factory: ClientFactory | None = None,
) -> dict[str, object]:
    token = resolve_rts_token(token)
    action_token = resolve_action_token(action_token)

    if not token:
        return {
            "ok": False,
            "enabled": False,
            "status": "missing_token",
            "detail": "Set SLACK_USER_TOKEN for slash-command checks or SLACK_BOT_TOKEN for app/assistant event checks.",
        }

    if token.startswith("xoxb-") and not action_token:
        return {
            "ok": False,
            "enabled": False,
            "status": "needs_action_token",
            "detail": "Bot-token Real-Time Search requires the action_token Slack sends with app/assistant events.",
        }

    try:
        from slack_sdk.errors import SlackApiError
        client = make_web_client(token, client_factory)
    except ImportError:
        return {
            "ok": False,
            "enabled": False,
            "status": "missing_slack_sdk",
            "detail": "Install slack_bolt/slack_sdk before calling Slack Real-Time Search.",
        }

    payload: dict[str, Any] = {}
    if action_token:
        payload["action_token"] = action_token

    try:
        response = client.api_call("assistant.search.info", json=payload)
    except SlackApiError as error:
        slack_error = error.response.get("error", "unknown_error")
        return {
            "ok": False,
            "enabled": False,
            "status": slack_error,
            "detail": f"Slack rejected assistant.search.info with: {slack_error}",
        }

    is_ok = bool(response.get("ok"))
    is_ai_search_enabled = bool(response.get("is_ai_search_enabled"))
    status = "ai_search_enabled" if is_ai_search_enabled else "api_reachable_ai_search_disabled"
    return {
        "ok": is_ok,
        "enabled": is_ai_search_enabled,
        "status": status if is_ok else response.get("error", "unknown_error"),
        "detail": (
            "Slack Real-Time Search is reachable; semantic AI search is enabled."
            if is_ai_search_enabled
            else "Slack Real-Time Search is reachable, but semantic AI search is not enabled for this workspace."
        ),
    }


def search_slack_rts(
    account: Account,
    token: str | None = None,
    action_token: str | None = None,
    limit_per_query: int = 5,
    client_factory: ClientFactory | None = None,
) -> tuple[Evidence, ...]:
    token = resolve_rts_token(token)
    action_token = resolve_action_token(action_token)

    if not token:
        return ()

    # Slack bot-token RTS calls require an action_token from a Slack event.
    if token.startswith("xoxb-") and not action_token:
        return ()

    try:
        from slack_sdk.errors import SlackApiError
        client = make_web_client(token, client_factory)
    except ImportError:
        return ()

    evidence: list[Evidence] = []

    for query in build_queries(account):
        payload: dict[str, Any] = {
            "query": query,
            "limit": min(limit_per_query, 20),
            "content_types": ["messages", "files"],
            "channel_types": ["public_channel", "private_channel"],
            "include_context_messages": True,
            "include_bots": False,
            "sort": "timestamp",
            "sort_dir": "desc",
        }
        if action_token:
            payload["action_token"] = action_token

        try:
            response = client.api_call("assistant.search.context", json=payload)
        except SlackApiError:
            continue

        evidence.extend(parse_rts_response(dict(response), account))

    return dedupe_evidence(evidence)


def parse_rts_response(response: dict[str, Any], account: Account) -> list[Evidence]:
    items = list(_walk_text_items(response))
    evidence: list[Evidence] = []

    for index, item in enumerate(items):
        text = item["text"].strip()
        if not text or account.name.lower() not in text.lower():
            continue

        tags = infer_tags(text)
        evidence.append(
            Evidence(
                source="slack-rts",
                channel=item.get("channel") or "Slack RTS",
                timestamp=item.get("timestamp") or "live-search",
                title=item.get("title") or f"Live Slack signal {index + 1}",
                text=text,
                weight=estimate_weight(text, tags),
                tags=tags,
            )
        )

    return evidence


def _walk_text_items(value: Any) -> Iterable[dict[str, str]]:
    if isinstance(value, dict):
        text = _first_string(value, ("text", "snippet", "summary", "content"))
        if text:
            yield {
                "text": text,
                "channel": _channel_name(value),
                "timestamp": _first_string(value, ("ts", "timestamp", "created_at", "message_ts", "date_created")),
                "title": _first_string(value, ("title", "name")),
            }

        for nested in value.values():
            yield from _walk_text_items(nested)

    elif isinstance(value, list):
        for nested in value:
            yield from _walk_text_items(nested)


def _first_string(value: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str):
            return candidate
        if isinstance(candidate, int):
            return str(candidate)
    return ""


def _channel_name(value: dict[str, Any]) -> str:
    channel = value.get("channel")
    if isinstance(channel, str):
        return channel
    if isinstance(channel, dict):
        return _first_string(channel, ("name", "id"))
    return _first_string(value, ("channel_name", "channel_id"))


def dedupe_evidence(items: list[Evidence]) -> tuple[Evidence, ...]:
    seen: set[tuple[str, str]] = set()
    deduped: list[Evidence] = []
    for item in items:
        key = (item.channel, item.text)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return tuple(sorted(deduped, key=lambda item: item.timestamp))
