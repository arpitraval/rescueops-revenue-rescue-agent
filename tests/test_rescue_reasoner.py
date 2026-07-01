import os
import unittest
from unittest.mock import patch

from rescueops.rescue_reasoner import (
    DEFAULT_REASONING_MODEL,
    build_grounding_payload,
    build_reasoning_prompt,
    call_configured_llm,
    generate_reasoned_text,
    llm_reasoning_enabled,
    strip_reasoning_traces,
)
from rescueops.risk_engine import scan_account


class RescueReasonerTests(unittest.TestCase):
    def test_reasoner_is_off_without_endpoint(self) -> None:
        with patch.dict(os.environ, {"RESCUEOPS_REASONER_MODE": "llm"}, clear=False):
            os.environ.pop("RESCUEOPS_LLM_ENDPOINT", None)

            self.assertFalse(llm_reasoning_enabled())

    def test_reasoner_keeps_fallback_without_client_or_endpoint(self) -> None:
        case = scan_account("acme")

        text = generate_reasoned_text(case, task="case_brief", fallback="deterministic fallback")

        self.assertEqual(text, "deterministic fallback")

    def test_grounded_llm_output_can_replace_fallback(self) -> None:
        case = scan_account("acme")

        text = generate_reasoned_text(
            case,
            task="customer_update",
            fallback="fallback",
            completion_client=lambda _prompt: (
                "Acme Robotics is at critical risk. "
                "Use the SSO evidence and protect USD 245,000 with the approved owner plan."
            ),
        )

        self.assertIn("Acme Robotics", text)
        self.assertIn("USD 245,000", text)

    def test_ungrounded_money_falls_back(self) -> None:
        case = scan_account("acme")

        text = generate_reasoned_text(
            case,
            task="customer_update",
            fallback="fallback",
            completion_client=lambda _prompt: "Acme Robotics has USD 999,000 at risk.",
        )

        self.assertEqual(text, "fallback")

    def test_prompt_contains_grounded_evidence_and_actions(self) -> None:
        case = scan_account("acme")

        prompt = build_reasoning_prompt(case, "rescue_plan", "draft the plan")
        payload = build_grounding_payload(case, "rescue_plan", "draft the plan")

        self.assertIn("Use only the grounded JSON facts", prompt)
        self.assertIn("Acme Robotics", prompt)
        self.assertEqual(payload["task"], "rescue_plan")
        self.assertTrue(payload["evidence"])
        self.assertTrue(payload["recommended_actions"])

    def test_reasoning_trace_is_stripped(self) -> None:
        text = strip_reasoning_traces("<think>private reasoning</think>Acme Robotics final answer")

        self.assertEqual(text, "Acme Robotics final answer")

    def test_configured_llm_uses_qwen_default_model(self) -> None:
        calls = []

        def fake_post_json(endpoint, payload, timeout):
            calls.append((endpoint, payload, timeout))
            return {"message": {"content": "Acme Robotics grounded response"}}

        with patch.dict(
            os.environ,
            {
                "RESCUEOPS_LLM_ENDPOINT": "http://localhost:11434/api/chat",
                "RESCUEOPS_REASONER_MODE": "ollama",
            },
            clear=False,
        ):
            os.environ.pop("RESCUEOPS_LLM_MODEL", None)
            with patch("rescueops.rescue_reasoner.post_json", fake_post_json):
                text = call_configured_llm("prompt")

        self.assertEqual(text, "Acme Robotics grounded response")
        self.assertEqual(calls[0][1]["model"], DEFAULT_REASONING_MODEL)


if __name__ == "__main__":
    unittest.main()