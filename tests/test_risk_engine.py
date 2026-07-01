import os
import unittest
from unittest.mock import patch

from rescueops.data_loader import load_account, load_evidence, resolve_account_id
from rescueops.evidence_provider import load_account_evidence
from rescueops.evidence_scoring import infer_tags
from rescueops.models import Evidence
from rescueops.signal_discovery import discover_emerging_signals
from rescueops.risk_engine import calculate_score_components, recommend_actions, scan_account
from rescueops.rts_search import parse_rts_response
from rescueops.slack_blocks import render_blocks


class RiskEngineTests(unittest.TestCase):
    def test_acme_is_critical_revenue_risk(self) -> None:
        case = scan_account("acme")

        self.assertEqual(case.account.name, "Acme Robotics")
        self.assertEqual(case.risk_level, "critical")
        self.assertGreaterEqual(case.risk_score, 90)
        self.assertEqual(case.metrics["revenue_at_risk"], 500000)
        self.assertEqual(case.metrics["evidence_source"], "seeded")
        self.assertEqual(case.metrics["expected_revenue_protected"], 245000)

    def test_score_components_are_explainable(self) -> None:
        case = scan_account("acme")
        components = calculate_score_components(case.evidence)

        self.assertGreater(components["raw_signal_score"], 0)
        self.assertGreater(components["diversity_bonus"], 0)
        self.assertEqual(components["risk_score"], case.risk_score)
        self.assertEqual(case.metrics["first_warning_days_ago"], 9)

    def test_second_account_proves_outputs_are_not_canned(self) -> None:
        acme = scan_account("acme")
        northstar = scan_account("northstar")

        self.assertEqual(northstar.account.name, "Northstar Health")
        self.assertNotEqual(acme.account.name, northstar.account.name)
        self.assertNotEqual(acme.metrics["revenue_at_risk"], northstar.metrics["revenue_at_risk"])
        self.assertNotEqual(acme.risk_score, northstar.risk_score)
        self.assertEqual(northstar.risk_level, "watch")
        self.assertTrue(any(item.channel == "#support-northstar" for item in northstar.evidence))

    def test_scan_discovers_emerging_patterns_from_evidence(self) -> None:
        case = scan_account("acme")

        patterns = case.metrics["emerging_patterns"]

        self.assertGreaterEqual(len(patterns), 1)
        self.assertIn("emerging_pattern_bonus", case.metrics["score_components"])
        self.assertGreaterEqual(case.metrics["score_components"]["emerging_pattern_bonus"], 0)

    def test_signal_discovery_finds_new_phrases_not_in_taxonomy(self) -> None:
        evidence = (
            Evidence(
                source="slack",
                channel="#customer-risk",
                timestamp="2026-07-01T09:00:00+05:30",
                title="Launch risk",
                text="Nimbus Labs says payroll export freeze is blocking launch readiness.",
                weight=13,
                tags=(),
            ),
            Evidence(
                source="support",
                channel="#support-nimbus",
                timestamp="2026-07-01T09:05:00+05:30",
                title="Support escalation",
                text="Payroll export freeze still blocks Nimbus Labs launch owner assignment.",
                weight=12,
                tags=(),
            ),
        )

        patterns = discover_emerging_signals(evidence, "Nimbus Labs")
        phrases = {pattern.phrase for pattern in patterns}

        self.assertIn("payroll export", phrases)
        self.assertTrue(any(pattern.evidence_count == 2 for pattern in patterns))
    def test_unknown_account_can_be_scanned_without_fixture(self) -> None:
        account = load_account("Globex Corp")

        self.assertEqual(account.account_id, "globex-corp")
        self.assertEqual(account.name, "Globex Corp")
        self.assertEqual(load_evidence("Globex Corp"), ())
        self.assertEqual(resolve_account_id("Acme Robotics"), "acme")

    def test_live_rts_can_drive_unknown_account_revenue(self) -> None:
        live_evidence = (
            Evidence(
                source="slack-rts",
                channel="#sales-globex",
                timestamp="2026-07-04T09:00:00+05:30",
                title="Live renewal signal",
                text="Globex Corp may pause the $750k renewal unless the SSO owner is assigned today.",
                weight=14,
                tags=("renewal", "sso", "owner"),
            ),
        )

        with patch("rescueops.evidence_provider.search_slack_rts", return_value=live_evidence):
            case = scan_account("Globex Corp", evidence_mode="rts")

        self.assertEqual(case.account.account_id, "globex-corp")
        self.assertEqual(case.metrics["evidence_source"], "slack-rts")
        self.assertEqual(case.metrics["revenue_at_risk"], 750000)
        self.assertGreater(case.risk_score, 0)
        self.assertTrue(case.actions)

    def test_owner_policy_can_map_to_slack_user_group(self) -> None:
        with patch.dict(os.environ, {"RESCUEOPS_OWNER_ENGINEERING_AUTH": "<!subteam^S123AUTH|auth-team>"}, clear=False):
            case = scan_account("acme")

        owners_by_title = {action.title: action.owner for action in case.actions}

        self.assertEqual(
            owners_by_title["SSO recovery owner"],
            "<!subteam^S123AUTH|auth-team>",
        )

    def test_due_dates_follow_risk_severity(self) -> None:
        critical_actions = recommend_actions(("sso",), "acme", risk_score=95)
        watch_actions = recommend_actions(("sso",), "acme", risk_score=50)

        critical_sso = next(action for action in critical_actions if action.title == "SSO recovery owner")
        watch_sso = next(action for action in watch_actions if action.title == "SSO recovery owner")

        self.assertEqual(critical_sso.due, "Today")
        self.assertEqual(watch_sso.due, "Within 24 hours")

    def test_slack_blocks_have_operational_actions(self) -> None:
        case = scan_account("acme")
        blocks = render_blocks(case)

        action_blocks = [block for block in blocks if block["type"] == "actions"]
        action_ids = [item["action_id"] for item in action_blocks[0]["elements"]]
        self.assertEqual(len(action_blocks), 1)
        self.assertEqual(
            action_ids,
            [
                "explain_score",
                "create_rescue_room",
                "assign_owner",
                "post_rescue_plan",
                "impact_receipt",
            ],
        )

    def test_hybrid_mode_falls_back_without_action_token(self) -> None:
        account = load_account("acme")
        with patch.dict(os.environ, {"RESCUEOPS_EVIDENCE_MODE": "hybrid"}, clear=False):
            evidence, source = load_account_evidence(account)

        self.assertEqual(source, "seeded-fallback")
        self.assertGreaterEqual(len(evidence), 1)

    def test_rts_parser_extracts_evidence(self) -> None:
        account = load_account("acme")
        response = {
            "results": [
                {
                    "text": "Acme Robotics may not renew because SSO has no owner.",
                    "channel": {"name": "sales-acme"},
                    "ts": "123.456",
                    "title": "renewal risk",
                }
            ]
        }

        evidence = parse_rts_response(response, account)

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].source, "slack-rts")
        self.assertIn("renewal", evidence[0].tags)
        self.assertIn("sso", evidence[0].tags)

    def test_taxonomy_detects_owner_risk(self) -> None:
        tags = infer_tags("Acme Robotics SSO escalation has no owner assigned.")

        self.assertIn("sso", tags)
        self.assertIn("owner", tags)
        self.assertIn("executive", tags)


if __name__ == "__main__":
    unittest.main()
