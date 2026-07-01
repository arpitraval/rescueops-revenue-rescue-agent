import os
import unittest
from unittest.mock import patch

from rescueops.data_loader import load_account
from rescueops.evidence_provider import load_account_evidence
from rescueops.mcp_client import StdioMcpClient, load_mcp_business_evidence
from rescueops.risk_engine import scan_account


class McpIntegrationTests(unittest.TestCase):
    def test_mcp_server_lists_business_tools(self) -> None:
        with StdioMcpClient() as client:
            result = client._request("tools/list", {})

        tool_names = {tool["name"] for tool in result["tools"]}
        self.assertIn("get_account_snapshot", tool_names)
        self.assertIn("get_revenue_risk_signals", tool_names)

    def test_mcp_client_loads_business_evidence(self) -> None:
        account = load_account("acme")

        evidence = load_mcp_business_evidence(account)

        self.assertGreaterEqual(len(evidence), 1)
        self.assertTrue(any(item.source.startswith("mcp-") for item in evidence))

    def test_scan_can_be_enriched_with_mcp(self) -> None:
        with patch.dict(os.environ, {"RESCUEOPS_USE_MCP": "1"}, clear=False):
            case = scan_account("acme")

        self.assertIn("+mcp", case.metrics["evidence_source"])
        self.assertTrue(any(item.source.startswith("mcp-") for item in case.evidence))

    def test_mcp_mode_uses_business_integration(self) -> None:
        account = load_account("acme")

        with patch.dict(os.environ, {}, clear=False):
            evidence, source = load_account_evidence(account, mode="mcp")

        self.assertEqual(source, "seeded+mcp")
        self.assertTrue(any(item.source.startswith("mcp-") for item in evidence))


if __name__ == "__main__":
    unittest.main()
