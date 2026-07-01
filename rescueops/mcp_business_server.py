from __future__ import annotations

import json
import sys
from typing import Any

from rescueops.data_loader import load_account, load_evidence


PROTOCOL_VERSION = "2025-06-18"


TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_account_snapshot",
        "description": "Return CRM-style account metadata for a customer at risk.",
        "inputSchema": {
            "type": "object",
            "properties": {"account_id": {"type": "string"}},
            "required": ["account_id"],
        },
    },
    {
        "name": "get_revenue_risk_signals",
        "description": "Return CRM, support, Jira, and incident signals related to revenue risk.",
        "inputSchema": {
            "type": "object",
            "properties": {"account_id": {"type": "string"}},
            "required": ["account_id"],
        },
    },
    {
        "name": "get_rescue_recommendations",
        "description": "Return business-system recommended rescue actions for the account.",
        "inputSchema": {
            "type": "object",
            "properties": {"account_id": {"type": "string"}},
            "required": ["account_id"],
        },
    },
]


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    account_id = str(arguments.get("account_id", "acme")).lower()

    if name == "get_account_snapshot":
        account = load_account(account_id)
        return {
            "account_id": account.account_id,
            "name": account.name,
            "segment": account.segment,
            "renewal_date": account.renewal_date,
            "revenue_at_risk": account.revenue_at_risk,
            "crm_owner": account.owner,
        }

    if name == "get_revenue_risk_signals":
        business_sources = {"crm", "jira", "support", "incident"}
        return {
            "account_id": account_id,
            "signals": [
                {
                    "source": f"mcp-{item.source}",
                    "channel": item.channel,
                    "timestamp": item.timestamp,
                    "title": item.title,
                    "text": item.text,
                    "weight": item.weight,
                    "tags": list(item.tags),
                }
                for item in load_evidence(account_id)
                if item.source in business_sources
            ],
        }

    if name == "get_rescue_recommendations":
        account = load_account(account_id)
        return {
            "account_id": account_id,
            "recommendations": [
                {
                    "title": "Rescue coordination room",
                    "owner": "Revenue Operations",
                    "due": "Now",
                    "reason": f"{account.name} has cross-functional revenue risk.",
                },
                {
                    "title": "SSO recovery owner",
                    "owner": "Engineering Auth Lead",
                    "due": "Today",
                    "reason": "Jira and support signals show unclear ownership.",
                },
                {
                    "title": "Add executive sponsor",
                    "owner": "VP Revenue",
                    "due": "Within 24 hours",
                    "reason": "CRM expansion value is high enough to need senior coverage.",
                },
            ],
        }

    raise ValueError(f"Unknown tool: {name}")


def success(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def failure(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    message_id = message.get("id")

    if method == "initialize":
        return success(
            message_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "rescueops-business-systems", "version": "0.1.0"},
            },
        )

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return success(message_id, {"tools": TOOLS})

    if method == "tools/call":
        params = message.get("params", {})
        try:
            payload = call_tool(params["name"], params.get("arguments", {}))
        except Exception as error:  # pragma: no cover - defensive server boundary
            return failure(message_id, -32000, str(error))
        return success(
            message_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(payload, separators=(",", ":")),
                    }
                ],
                "isError": False,
            },
        )

    return failure(message_id, -32601, f"Method not found: {method}")


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            response = handle(json.loads(line))
        except json.JSONDecodeError as error:
            response = failure(None, -32700, str(error))

        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
