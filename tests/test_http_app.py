import unittest

from rescueops.http_app import build_slash_response


class HttpAppTests(unittest.TestCase):
    def test_scan_command_returns_blocks(self) -> None:
        response = build_slash_response("scan acme")

        self.assertEqual(response["response_type"], "in_channel")
        self.assertIn("blocks", response)
        self.assertEqual(response["blocks"][0]["text"]["text"], "Revenue Rescue: Acme Robotics")

    def test_second_account_returns_different_card(self) -> None:
        response = build_slash_response("scan northstar")

        self.assertEqual(response["response_type"], "in_channel")
        self.assertEqual(response["blocks"][0]["text"]["text"], "Revenue Rescue: Northstar Health")
        self.assertIn("USD 180,000", response["blocks"][1]["text"]["text"])

    def test_invalid_command_returns_help(self) -> None:
        response = build_slash_response("help")

        self.assertEqual(response["response_type"], "ephemeral")
        self.assertIn("/rescueops scan acme", response["text"])


if __name__ == "__main__":
    unittest.main()

