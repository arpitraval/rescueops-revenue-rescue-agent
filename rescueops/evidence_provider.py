from __future__ import annotations

import os

from rescueops.data_loader import load_evidence
from rescueops.mcp_client import McpClientError, load_mcp_business_evidence
from rescueops.models import Account, Evidence
from rescueops.rts_search import search_slack_rts


EvidenceSource = tuple[tuple[Evidence, ...], str]


def load_account_evidence(
    account: Account,
    mode: str | None = None,
    action_token: str | None = None,
) -> EvidenceSource:
    selected_mode = (mode or os.getenv("RESCUEOPS_EVIDENCE_MODE") or "seeded").lower()
    seeded = load_evidence(account.account_id)
    use_mcp = os.getenv("RESCUEOPS_USE_MCP", "0") == "1" or selected_mode == "mcp"

    if selected_mode == "seeded":
        return enrich_with_mcp(account, seeded, "seeded") if use_mcp else (seeded, "seeded")

    if selected_mode == "mcp":
        return enrich_with_mcp(account, seeded, "seeded")

    live = search_slack_rts(account, action_token=action_token)

    if selected_mode == "rts":
        evidence, source = (live, "slack-rts") if live else (seeded, "seeded-fallback")
        return enrich_with_mcp(account, evidence, source) if use_mcp else (evidence, source)

    if selected_mode == "hybrid":
        if not live:
            return enrich_with_mcp(account, seeded, "seeded-fallback") if use_mcp else (seeded, "seeded-fallback")
        hybrid = merge_evidence(seeded, live)
        return enrich_with_mcp(account, hybrid, "hybrid-rts") if use_mcp else (hybrid, "hybrid-rts")

    return enrich_with_mcp(account, seeded, "seeded") if use_mcp else (seeded, "seeded")


def merge_evidence(seeded: tuple[Evidence, ...], live: tuple[Evidence, ...]) -> tuple[Evidence, ...]:
    seen: set[tuple[str, str]] = set()
    merged: list[Evidence] = []
    for item in (*live, *seeded):
        key = (item.channel, item.text)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return tuple(sorted(merged, key=lambda item: item.timestamp))


def enrich_with_mcp(
    account: Account,
    evidence: tuple[Evidence, ...],
    source: str,
) -> EvidenceSource:
    try:
        mcp_evidence = load_mcp_business_evidence(account)
    except McpClientError:
        return evidence, f"{source}+mcp-unavailable"

    if not mcp_evidence:
        return evidence, f"{source}+mcp-empty"
    return merge_evidence(evidence, mcp_evidence), f"{source}+mcp"
