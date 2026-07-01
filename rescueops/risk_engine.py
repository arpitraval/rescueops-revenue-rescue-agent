from __future__ import annotations

from collections import Counter
from datetime import datetime
import re

from rescueops.data_loader import load_account
from rescueops.evidence_provider import load_account_evidence
from rescueops.models import DiscoveredSignal, Evidence, RescueAction, RescueCase
from rescueops.rescue_policy import (
    action_for_tag,
    fallback_action_tags,
    root_cause_label,
    root_cause_labels,
    tag_for_root_cause,
)
from rescueops.signal_discovery import discover_emerging_signals, emerging_pattern_bonus


HIGH_RISK_THRESHOLD = 75
MEDIUM_RISK_THRESHOLD = 45
MAX_PROTECTION_RATE = 0.49
MAX_REPORTED_MTTR_REDUCTION = 96


def scan_account(
    account_id: str,
    evidence_mode: str | None = None,
    action_token: str | None = None,
) -> RescueCase:
    account = load_account(account_id)
    evidence, evidence_source = load_account_evidence(
        account,
        mode=evidence_mode,
        action_token=action_token,
    )
    emerging_signals = discover_emerging_signals(evidence, account.name)
    score_components = calculate_score_components(evidence, emerging_signals)
    risk_score = int(score_components["risk_score"])
    root_cause_tags = infer_root_cause_tags(evidence)
    root_causes = tuple(root_cause_label(tag) for tag in root_cause_tags)
    actions = recommend_actions(root_cause_tags, account.account_id, risk_score)
    revenue_at_risk = estimate_revenue_at_risk(account.revenue_at_risk, evidence)
    evidence_window_days = calculate_evidence_window_days(evidence)
    old_time_to_diagnose = estimate_manual_diagnosis_time(evidence)
    old_time_to_plan = estimate_manual_plan_time(evidence, actions)

    metrics = {
        "revenue_at_risk": revenue_at_risk,
        "evidence_items": len(evidence),
        "evidence_source": evidence_source,
        "first_warning_days_ago": evidence_window_days,
        "old_time_to_diagnose": old_time_to_diagnose,
        "new_time_to_diagnose": "45 seconds",
        "old_time_to_plan": old_time_to_plan,
        "new_time_to_plan": "2 minutes",
        "mean_time_to_rescue_reduction_pct": calculate_reduction_pct(old_time_to_plan, "2 minutes"),
        "expected_revenue_protected": estimate_expected_revenue_protected(revenue_at_risk, risk_score),
        "score_components": score_components,
        "emerging_patterns": serialize_emerging_signals(emerging_signals),
        "root_cause_tags": list(root_cause_tags),
        "source_count": len({item.source for item in evidence}),
        "channel_count": len({item.channel for item in evidence}),
    }

    return RescueCase(
        account=account,
        risk_score=risk_score,
        risk_level=risk_level(risk_score),
        evidence=evidence,
        root_causes=root_causes,
        actions=actions,
        metrics=metrics,
    )


def calculate_score_components(
    evidence: tuple[Evidence, ...],
    emerging_signals: tuple[DiscoveredSignal, ...] | None = None,
) -> dict[str, int]:
    raw_signal_score = sum(item.weight for item in evidence)
    unique_sources = {item.source for item in evidence}
    channel_spread = {item.channel for item in evidence}
    source_bonus = len(unique_sources) * 4
    channel_bonus = len(channel_spread) * 2
    diversity_bonus = min(source_bonus + channel_bonus, 18)
    if emerging_signals is None:
        emerging_signals = discover_emerging_signals(evidence)
    pattern_bonus = emerging_pattern_bonus(emerging_signals)
    risk_score = min(raw_signal_score + diversity_bonus + pattern_bonus, 100)
    return {
        "raw_signal_score": raw_signal_score,
        "source_bonus": source_bonus,
        "channel_bonus": channel_bonus,
        "diversity_bonus": diversity_bonus,
        "emerging_pattern_bonus": pattern_bonus,
        "risk_score": risk_score,
    }


def serialize_emerging_signals(signals: tuple[DiscoveredSignal, ...]) -> list[dict[str, object]]:
    return [
        {
            "phrase": signal.phrase,
            "score": signal.score,
            "evidence_count": signal.evidence_count,
            "channels": list(signal.channels),
            "sources": list(signal.sources),
            "examples": list(signal.examples),
        }
        for signal in signals
    ]


def calculate_risk_score(evidence: tuple[Evidence, ...]) -> int:
    return calculate_score_components(evidence)["risk_score"]


def calculate_evidence_window_days(evidence: tuple[Evidence, ...]) -> int:
    timestamps = [parse_timestamp(item.timestamp) for item in evidence]
    timestamps = [item for item in timestamps if item is not None]
    if len(timestamps) < 2:
        return 0
    return max((max(timestamps) - min(timestamps)).days, 0)


def parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def estimate_manual_diagnosis_time(evidence: tuple[Evidence, ...]) -> str:
    if not evidence:
        return "0 minutes"
    hours = max(1, min(round(len(evidence) * 0.4), 8))
    return f"{hours} hour" if hours == 1 else f"{hours} hours"


def estimate_manual_plan_time(evidence: tuple[Evidence, ...], actions: tuple[RescueAction, ...]) -> str:
    if not evidence or not actions:
        return "0 minutes"
    if len(evidence) >= 8 or len(actions) >= 4:
        return "1 day"
    return "4 hours"


def calculate_reduction_pct(old_time: str, new_time: str) -> int:
    old_minutes = duration_to_minutes(old_time)
    new_minutes = duration_to_minutes(new_time)
    if old_minutes <= 0:
        return 0
    raw_reduction = round((old_minutes - new_minutes) / old_minutes * 100)
    return min(raw_reduction, MAX_REPORTED_MTTR_REDUCTION)


def duration_to_minutes(value: str) -> int:
    amount_text, unit = value.split()[:2]
    amount = int(amount_text)
    if unit.startswith("second"):
        return max(round(amount / 60), 1)
    if unit.startswith("minute"):
        return amount
    if unit.startswith("hour"):
        return amount * 60
    if unit.startswith("day"):
        return amount * 24 * 60
    return amount


def estimate_revenue_at_risk(configured_revenue: int, evidence: tuple[Evidence, ...]) -> int:
    if configured_revenue > 0:
        return configured_revenue
    detected = [amount for item in evidence for amount in extract_money_amounts(item.text)]
    return max(detected, default=0)


def extract_money_amounts(text: str) -> list[int]:
    amounts: list[int] = []
    pattern = re.compile(r"(?i)(usd\s*)?\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|m|million)?")
    for match in pattern.finditer(text):
        raw = match.group(0).lower()
        suffix = (match.group(3) or "").lower()
        if "usd" not in raw and "$" not in raw and suffix not in {"k", "m", "million"}:
            continue
        number = float(match.group(2).replace(",", ""))
        if suffix == "k":
            number *= 1_000
        elif suffix in {"m", "million"}:
            number *= 1_000_000
        amounts.append(round(number))
    return amounts


def estimate_expected_revenue_protected(revenue_at_risk: int, risk_score: int) -> int:
    protection_rate = min(MAX_PROTECTION_RATE, max(0.12, risk_score / 100 * MAX_PROTECTION_RATE))
    return round(revenue_at_risk * protection_rate)


def risk_level(score: int) -> str:
    if score >= HIGH_RISK_THRESHOLD:
        return "critical"
    if score >= MEDIUM_RISK_THRESHOLD:
        return "watch"
    return "normal"


def infer_root_cause_tags(evidence: tuple[Evidence, ...]) -> tuple[str, ...]:
    tag_counts: Counter[str] = Counter()
    known_tags = root_cause_labels()
    for item in evidence:
        tag_counts.update(tag for tag in item.tags if tag in known_tags)

    return tuple(tag for tag, _count in tag_counts.most_common())


def infer_root_causes(evidence: tuple[Evidence, ...]) -> tuple[str, ...]:
    return tuple(root_cause_label(tag) for tag in infer_root_cause_tags(evidence)[:5])


def recommend_actions(
    root_causes: tuple[str, ...],
    account_id: str = "acme",
    risk_score: int = 0,
) -> tuple[RescueAction, ...]:
    cause_tags = tuple(
        tag for tag in (tag_for_root_cause(item) for item in root_causes) if tag is not None
    )
    if not cause_tags:
        return ()

    ordered_tags: list[str] = ["rescue_room"]
    ordered_tags.extend(tag for tag in cause_tags if tag != "owner")
    ordered_tags.extend(tag for tag in fallback_action_tags() if tag not in ordered_tags)

    actions: list[RescueAction] = []
    seen_titles: set[str] = set()
    for tag in ordered_tags:
        action = action_for_tag(tag, account_id, risk_score)
        if not action or action.title in seen_titles:
            continue
        seen_titles.add(action.title)
        actions.append(action)

    return tuple(actions[:4])
