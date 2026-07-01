import unittest

from rescueops.data_loader import load_account
from rescueops.rts_search import build_queries, check_rts_availability, search_slack_rts


class FakeSlackClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def api_call(self, method, json=None):
        self.calls.append((method, json or {}))
        return self.response


class RealTimeSearchTests(unittest.TestCase):
    def test_rts_queries_are_generated_from_taxonomy(self) -> None:
        account = load_account("northstar")

        queries = build_queries(account)

        self.assertEqual(len(queries), 3)
        self.assertTrue(all('"Northstar Health"' in query for query in queries))
        self.assertTrue(any("sso" in query.lower() for query in queries))
        self.assertTrue(any("customer-visible" in query.lower() for query in queries))

    def test_user_token_can_search_without_action_token(self) -> None:
        account = load_account("acme")
        client = FakeSlackClient(
            {
                "ok": True,
                "results": {
                    "messages": [
                        {
                            "channel_name": "sales-acme",
                            "message_ts": "2026-07-04T12:00:00",
                            "content": "Acme Robotics may not renew because SSO owner escalation is still open.",
                        }
                    ]
                },
            }
        )

        evidence = search_slack_rts(
            account,
            token="xoxp-user-token",
            client_factory=lambda _token: client,
        )

        self.assertEqual(len(client.calls), 3)
        self.assertEqual(client.calls[0][0], "assistant.search.context")
        self.assertNotIn("action_token", client.calls[0][1])
        self.assertEqual(evidence[0].source, "slack-rts")
        self.assertEqual(evidence[0].channel, "sales-acme")

    def test_bot_token_requires_action_token_before_search(self) -> None:
        account = load_account("acme")
        client = FakeSlackClient({"ok": True, "results": {"messages": []}})

        evidence = search_slack_rts(
            account,
            token="xoxb-bot-token",
            client_factory=lambda _token: client,
        )

        self.assertEqual(evidence, ())
        self.assertEqual(client.calls, [])

    def test_bot_token_sends_action_token_when_available(self) -> None:
        account = load_account("acme")
        client = FakeSlackClient(
            {
                "ok": True,
                "results": {
                    "messages": [
                        {
                            "channel_name": "incidents",
                            "message_ts": "2026-07-04T12:00:00",
                            "content": "Acme Robotics SSO incident is customer-visible and renewal risk is escalating.",
                        }
                    ]
                },
            }
        )

        evidence = search_slack_rts(
            account,
            token="xoxb-bot-token",
            action_token="act-123",
            client_factory=lambda _token: client,
        )

        self.assertEqual(client.calls[0][1]["action_token"], "act-123")
        self.assertEqual(evidence[0].source, "slack-rts")

    def test_rts_check_reports_missing_action_token_for_bot_token(self) -> None:
        status = check_rts_availability(token="xoxb-bot-token")

        self.assertFalse(status["ok"])
        self.assertEqual(status["status"], "needs_action_token")

    def test_rts_check_calls_assistant_search_info(self) -> None:
        client = FakeSlackClient({"ok": True, "is_ai_search_enabled": True})

        status = check_rts_availability(
            token="xoxp-user-token",
            client_factory=lambda _token: client,
        )

        self.assertTrue(status["ok"])
        self.assertTrue(status["enabled"])
        self.assertEqual(client.calls[0][0], "assistant.search.info")


if __name__ == "__main__":
    unittest.main()
