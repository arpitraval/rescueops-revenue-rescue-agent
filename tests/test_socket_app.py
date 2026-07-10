import os
import unittest
from unittest.mock import patch


class SocketAppTests(unittest.TestCase):
    def test_app_can_be_created_with_bot_token(self) -> None:
        with patch.dict(os.environ, {"SLACK_BOT_TOKEN": "test-bot-token"}):
            from rescueops.socket_app import create_app

            app = create_app()

        self.assertIsNotNone(app)

    def test_rescue_plan_text_contains_business_metrics(self) -> None:
        from rescueops.socket_app import build_rescue_plan_text

        text = build_rescue_plan_text("acme")

        self.assertIn("Revenue Rescue Plan: Acme Robotics", text)
        self.assertIn("USD 500,000", text)
        self.assertIn("96% reduction", text)

    def test_existing_rescue_room_does_not_repost_plan(self) -> None:
        from rescueops.socket_app import RESCUE_PLAN_POSTED, create_rescue_room

        class ExistingRoomClient:
            def __init__(self) -> None:
                self.posts = []

            def conversations_list(self, **_kwargs):
                return {"channels": [{"name": "rescue-acme", "id": "C_RESCUE"}]}

            def chat_postMessage(self, **kwargs):
                self.posts.append(kwargs)

        RESCUE_PLAN_POSTED.discard("acme")
        client = ExistingRoomClient()

        message = create_rescue_room(client, "acme")

        self.assertIn("Rescue room is ready", message)
        self.assertEqual(client.posts, [])
    def test_owner_update_contains_checkpoint(self) -> None:
        from rescueops.socket_app import build_owner_update_text

        text = build_owner_update_text("acme")

        self.assertIn("Owners assigned for Acme Robotics", text)
        self.assertIn("Revenue Operations", text)
        self.assertIn("Engineering Auth Lead", text)
        self.assertIn("Next checkpoint", text)

    def test_customer_update_is_safe(self) -> None:
        from rescueops.socket_app import build_customer_update_text

        text = build_customer_update_text("acme")

        self.assertIn("Customer-safe rescue update", text)
        self.assertIn("sso reliability", text.lower())
        self.assertIn("Revenue Operations", text)

    def test_score_explanation_is_auditable(self) -> None:
        from rescueops.socket_app import build_score_explanation_text

        text = build_score_explanation_text("acme")

        self.assertIn("Why RescueOps scored Acme Robotics", text)
        self.assertIn("Signal score", text)
        self.assertIn("Diversity bonus", text)
        self.assertIn("Top weighted evidence", text)

    def test_impact_receipt_contains_outcome_metrics(self) -> None:
        from rescueops.socket_app import build_impact_receipt_text

        text = build_impact_receipt_text("acme")

        self.assertIn("RescueOps Impact Receipt", text)
        self.assertIn("USD 245,000", text)
        self.assertIn("Mean Time To Rescue", text)
        self.assertIn("Case status", text)

    def test_case_state_can_close_and_reopen(self) -> None:
        from rescueops.socket_app import close_case, is_case_closed, reopen_case

        reopen_case("acme")
        self.assertFalse(is_case_closed("acme"))

        close_case("acme")
        self.assertTrue(is_case_closed("acme"))

        reopen_case("acme")
        self.assertFalse(is_case_closed("acme"))

    def test_audit_followup_appends_without_replacing_original(self) -> None:
        from rescueops.socket_app import post_audit_followup

        calls = []

        def respond(**kwargs):
            calls.append(kwargs)

        post_audit_followup(respond, "Preserve this audit message.", "acme")

        self.assertEqual(calls[0]["response_type"], "in_channel")
        self.assertFalse(calls[0]["replace_original"])
        self.assertFalse(calls[0]["delete_original"])
        self.assertIn("blocks", calls[0])

    def test_audit_followup_highlights_clicked_button(self) -> None:
        from rescueops.socket_app import post_audit_followup

        calls = []

        def respond(**kwargs):
            calls.append(kwargs)

        post_audit_followup(
            respond,
            "Explain this score.",
            "acme",
            selected_action_id="explain_score",
        )

        buttons = calls[0]["blocks"][1]["elements"]
        styles = {button["action_id"]: button.get("style") for button in buttons}

        self.assertEqual(styles["explain_score"], "primary")
        self.assertIsNone(styles["create_rescue_room"])

    def test_terminal_followup_has_no_action_buttons(self) -> None:
        from rescueops.socket_app import post_terminal_followup

        calls = []

        def respond(**kwargs):
            calls.append(kwargs)

        post_terminal_followup(respond, "Case closed.")

        self.assertEqual(calls[0]["response_type"], "in_channel")
        self.assertFalse(calls[0]["replace_original"])
        self.assertEqual(len(calls[0]["blocks"]), 1)
        self.assertEqual(calls[0]["blocks"][0]["type"], "section")


    def test_rts_check_text_explains_status(self) -> None:
        from rescueops.socket_app import build_rts_check_text

        with patch("rescueops.socket_app.check_rts_availability") as check:
            check.return_value = {
                "ok": True,
                "enabled": True,
                "status": "ai_search_enabled",
                "detail": "Slack Real-Time Search is reachable.",
            }

            text = build_rts_check_text()

        self.assertIn("Real-Time Search check", text)
        self.assertIn("ai_search_enabled", text)
        self.assertIn("Semantic AI search enabled: *yes*", text)

    def test_forced_live_scan_reports_fallback_when_rts_unavailable(self) -> None:
        from rescueops.risk_engine import scan_account
        from rescueops.socket_app import build_scan_response_text

        case = scan_account("acme", evidence_mode="rts")
        text = build_scan_response_text(case, forced_live=True)

        self.assertIn("RTS live scan", text)
        self.assertIn("demo", text.lower())

if __name__ == "__main__":
    unittest.main()
