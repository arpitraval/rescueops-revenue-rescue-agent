from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from rescueops.models import Account, Evidence


MCP_SERVER_MODULE = "rescueops.mcp_business_server"


@dataclass
class McpToolResult:
    tool_name: str
    payload: dict[str, Any]


class McpClientError(RuntimeError):
    pass


class StdioMcpClient:
    def __init__(self) -> None:
        self._next_id = 1
        self._process = subprocess.Popen(
            [sys.executable, "-m", MCP_SERVER_MODULE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        self._request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "rescueops", "version": "0.1.0"}})
        self._notify("notifications/initialized")

    def close(self) -> None:
        if self._process.poll() is None:
            if self._process.stdin is not None:
                self._process.stdin.close()
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
        if self._process.stdout is not None:
            self._process.stdout.close()
        if self._process.stderr is not None:
            self._process.stderr.close()

    def __enter__(self) -> "StdioMcpClient":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> McpToolResult:
        response = self._request("tools/call", {"name": name, "arguments": arguments})
        content = response.get("content", [])
        if not content:
            raise McpClientError(f"MCP tool returned no content: {name}")
        raw_text = content[0].get("text", "{}")
        return McpToolResult(name, json.loads(raw_text))

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if self._process.stdin is None:
            raise McpClientError("MCP server stdin is unavailable")
        self._process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}}) + "\n")
        self._process.stdin.flush()

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._process.stdin is None or self._process.stdout is None:
            raise McpClientError("MCP server pipes are unavailable")

        request_id = self._next_id
        self._next_id += 1
        self._process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
            + "\n"
        )
        self._process.stdin.flush()

        response_line = self._process.stdout.readline()
        if not response_line:
            stderr = self._process.stderr.read() if self._process.stderr else ""
            raise McpClientError(f"MCP server stopped before responding. {stderr}".strip())

        response = json.loads(response_line)
        if "error" in response:
            raise McpClientError(response["error"].get("message", "Unknown MCP error"))
        return response["result"]


def load_mcp_business_evidence(account: Account) -> tuple[Evidence, ...]:
    with StdioMcpClient() as client:
        result = client.call_tool(
            "get_revenue_risk_signals",
            {"account_id": account.account_id},
        )

    evidence: list[Evidence] = []
    for item in result.payload.get("signals", []):
        evidence.append(
            Evidence(
                source=str(item["source"]),
                channel=str(item["channel"]),
                timestamp=str(item["timestamp"]),
                title=str(item["title"]),
                text=str(item["text"]),
                weight=int(item["weight"]),
                tags=tuple(str(tag) for tag in item.get("tags", [])),
            )
        )
    return tuple(sorted(evidence, key=lambda item: item.timestamp))

