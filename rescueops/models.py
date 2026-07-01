from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Account:
    account_id: str
    name: str
    renewal_date: str
    revenue_at_risk: int
    segment: str
    owner: str


@dataclass(frozen=True)
class Evidence:
    source: str
    channel: str
    timestamp: str
    title: str
    text: str
    weight: int
    tags: tuple[str, ...]


@dataclass(frozen=True)
class DiscoveredSignal:
    phrase: str
    score: int
    evidence_count: int
    channels: tuple[str, ...]
    sources: tuple[str, ...]
    examples: tuple[str, ...]


@dataclass(frozen=True)
class RescueAction:
    title: str
    owner: str
    due: str
    reason: str


@dataclass(frozen=True)
class RescueCase:
    account: Account
    risk_score: int
    risk_level: str
    evidence: tuple[Evidence, ...]
    root_causes: tuple[str, ...]
    actions: tuple[RescueAction, ...]
    metrics: dict[str, Any]