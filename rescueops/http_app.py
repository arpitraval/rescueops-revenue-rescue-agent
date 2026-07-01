from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs

from rescueops.risk_engine import scan_account
from rescueops.slack_blocks import render_blocks


def build_slash_response(command_text: str) -> dict[str, Any]:
    parts = command_text.strip().split()
    if len(parts) != 2 or parts[0].lower() != "scan":
        return {
            "response_type": "ephemeral",
            "text": "Try `/rescueops scan acme`.",
        }

    account_id = parts[1].lower()
    case = scan_account(account_id)
    return {
        "response_type": "in_channel",
        "text": f"Revenue Rescue scan complete for {case.account.name}.",
        "blocks": render_blocks(case),
    }


def verify_slack_signature(headers: dict[str, str], body: bytes, signing_secret: str) -> bool:
    timestamp = headers.get("x-slack-request-timestamp", "")
    slack_signature = headers.get("x-slack-signature", "")

    if not timestamp or not slack_signature:
        return False

    try:
        request_time = int(timestamp)
    except ValueError:
        return False

    if abs(time.time() - request_time) > 60 * 5:
        return False

    basestring = b"v0:" + timestamp.encode("utf-8") + b":" + body
    digest = hmac.new(signing_secret.encode("utf-8"), basestring, hashlib.sha256).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, slack_signature)


class RescueOpsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json({"ok": True, "service": "rescueops"})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path != "/slack/commands":
            self.send_error(404)
            return

        body = self.rfile.read(int(self.headers.get("content-length", "0")))
        signing_secret = os.getenv("SLACK_SIGNING_SECRET")
        if signing_secret and not verify_slack_signature(dict(self.headers), body, signing_secret):
            self.send_error(401, "Invalid Slack signature")
            return

        form = parse_qs(body.decode("utf-8"))
        command_text = form.get("text", [""])[0]
        response = build_slash_response(command_text)
        self._send_json(response)

    def _send_json(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    port = int(os.getenv("PORT", "8787"))
    server = HTTPServer(("127.0.0.1", port), RescueOpsHandler)
    print(f"RescueOps listening on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

