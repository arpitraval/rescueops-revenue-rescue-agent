from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from rescueops.models import RescueAction


POLICY_PATH = Path(__file__).resolve().parents[1] / "data" / "rescue_policy.json"


@lru_cache(maxsize=1)
def load_rescue_policy(path: str | None = None) -> dict[str, Any]:
    policy_path = Path(path) if path else POLICY_PATH
    with policy_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def root_cause_labels() -> dict[str, str]:
    return dict(load_rescue_policy()["root_causes"])


def root_cause_label(tag: str) -> str:
    return root_cause_labels().get(tag, tag.replace("_", " ").title())


def tag_for_root_cause(value: str) -> str | None:
    labels = root_cause_labels()
    if value in labels:
        return value
    reverse = {label: tag for tag, label in labels.items()}
    return reverse.get(value)


def fallback_action_tags() -> tuple[str, ...]:
    return tuple(load_rescue_policy().get("fallback_actions", ()))


def action_for_tag(
    tag: str,
    account_id: str,
    risk_score: int,
) -> RescueAction | None:
    policy = load_rescue_policy()
    raw_action = policy.get("actions", {}).get(tag)
    if not raw_action:
        return None

    rescue_channel = f"#rescue-{account_id}"
    return RescueAction(
        title=raw_action["title"].format(
            account_id=account_id,
            rescue_channel=rescue_channel,
        ),
        owner=resolve_owner(raw_action["owner"]),
        due=due_for_risk(raw_action, risk_score),
        reason=raw_action["reason"],
    )


def resolve_owner(owner_key: str) -> str:
    owner = load_rescue_policy().get("owners", {}).get(owner_key, {})
    env_name = owner.get("env")
    if env_name and os.getenv(env_name):
        return os.environ[env_name]
    return owner.get("label", owner_key.replace("_", " ").title())


def due_for_risk(action: dict[str, Any], risk_score: int) -> str:
    due_by_risk = action.get("due_by_risk", {})
    if risk_score >= 75:
        return due_by_risk.get("critical", "Today")
    if risk_score >= 45:
        return due_by_risk.get("watch", "Within 24 hours")
    return due_by_risk.get("normal", "This week")
