from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rescueops.models import Account, Evidence


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "demo_workspace.json"


def load_workspace(path: Path = DATA_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def normalize_account_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized[:48] or "unknown-account"


def account_name_from_id(account_id: str) -> str:
    words = re.split(r"[-_\s]+", account_id.strip())
    return " ".join(word.capitalize() for word in words if word) or "Unknown Account"


def resolve_account_id(value: str, workspace: dict[str, Any] | None = None) -> str:
    data = workspace or load_workspace()
    normalized = normalize_account_id(value)
    for account_id, account in data.get("accounts", {}).items():
        if normalized in {normalize_account_id(account_id), normalize_account_id(account.get("name", ""))}:
            return account_id
    return normalized


def load_account(account_id: str, workspace: dict[str, Any] | None = None) -> Account:
    data = workspace or load_workspace()
    resolved_id = resolve_account_id(account_id, data)
    raw_account = data.get("accounts", {}).get(resolved_id)
    if raw_account is None:
        return Account(
            account_id=resolved_id,
            name=account_name_from_id(account_id),
            renewal_date="Unknown",
            revenue_at_risk=0,
            segment="Unknown",
            owner="Unassigned",
        )

    return Account(
        account_id=resolved_id,
        name=raw_account["name"],
        renewal_date=raw_account["renewal_date"],
        revenue_at_risk=raw_account["revenue_at_risk"],
        segment=raw_account["segment"],
        owner=raw_account["owner"],
    )


def load_evidence(account_id: str, workspace: dict[str, Any] | None = None) -> tuple[Evidence, ...]:
    data = workspace or load_workspace()
    resolved_id = resolve_account_id(account_id, data)
    raw_items = data.get("evidence", {}).get(resolved_id, [])
    evidence = [
        Evidence(
            source=item["source"],
            channel=item["channel"],
            timestamp=item["timestamp"],
            title=item["title"],
            text=item["text"],
            weight=item["weight"],
            tags=tuple(item["tags"]),
        )
        for item in raw_items
    ]
    return tuple(sorted(evidence, key=lambda item: item.timestamp))
