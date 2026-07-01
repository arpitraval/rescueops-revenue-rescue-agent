import unittest
from unittest.mock import patch

from rescueops.risk_engine import scan_account
from rescueops.slack_ai_agent import (
    build_dynamic_suggested_prompts,
    build_agent_intro_text,
    build_agent_scan_text,
    build_grounded_case_brief,
    build_suggested_prompts_payload,
    infer_account_id,
    infer_account_id_from_event,
)


class SlackAiAgentTests(unittest.TestCase):
    def test_agent_intro_uses_dynamic_case_metrics(self) -> None:
        text = build_agent_intro_text("acme")

        self.assertIn("RescueOps AI", text)
        self.assertIn("Acme Robotics", text)
        self.assertIn("100%", text)
        self.assertIn("10", text)
        self.assertIn("USD 245,000", text)

    def test_agent_scan_text_contains_dynamic_case_metrics(self) -> None:
        text = build_agent_scan_text("acme", "explain Acme risk")

        self.assertIn("RescueOps AI brief: Acme Robotics", text)
        self.assertIn("100% critical", text)
        self.assertIn("Signals analyzed", text)
        self.assertIn("USD", text)
        self.assertNotIn("seeded", text)
        self.assertNotIn("mcp", text.lower())
        self.assertNotIn("openai", text.lower())

    def test_suggested_prompts_are_dynamic(self) -> None:
        case = scan_account("acme")

        prompts = build_dynamic_suggested_prompts(case)

        prompt_text = " ".join(prompt["title"] + " " + prompt["message"] for prompt in prompts)
        self.assertIn("USD 245,000", prompt_text)
        self.assertIn("100%", prompt_text)
        self.assertIn("Acme Robotics", prompt_text)
        self.assertNotIn("seeded", prompt_text)

    def test_suggested_prompt_payload_names_account(self) -> None:
        payload = build_suggested_prompts_payload("acme")

        self.assertIn("Acme Robotics", payload["title"])
        self.assertGreaterEqual(len(payload["prompts"]), 3)

    def test_account_alias_inference(self) -> None:
        self.assertEqual(infer_account_id("please scan Acme Robotics"), "acme")
        self.assertEqual(infer_account_id("please scan Globex Corp"), "globex-corp")

    def test_assistant_event_account_inference_uses_context_strings(self) -> None:
        event = {
            "assistant_thread": {"channel_id": "C123", "thread_ts": "1.23"},
            "context": {"message": "Create a rescue brief for Northstar Health"},
        }

        self.assertEqual(infer_account_id_from_event(event), "northstar")

    def test_agent_scan_forwards_action_token_for_rts(self) -> None:
        with patch("rescueops.slack_ai_agent.scan_account") as scan:
            scan.return_value = scan_account("acme")

            text = build_agent_scan_text("acme", "scan Acme", action_token="act-123")

        scan.assert_called_once_with("acme", evidence_mode="rts", action_token="act-123")
        self.assertIn("Acme Robotics", text)

    def test_grounded_case_brief_is_grounded_in_case_context(self) -> None:
        case = scan_account("acme")

        text = build_grounded_case_brief(case, "draft rescue update")

        self.assertIn("Request understood: draft rescue update", text)
        self.assertIn("Signals analyzed", text)
        self.assertIn("Recommended rescue path", text)


if __name__ == "__main__":
    unittest.main()
