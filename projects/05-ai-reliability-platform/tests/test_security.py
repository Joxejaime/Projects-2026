"""Security regressions: body-length handling, API-key authentication, the global rate ceiling."""

import json
import socket
import threading
import unittest
import urllib.error
import urllib.request

from gateway.config import Config
from gateway.server import create_server, parse_api_keys

KEY_A = "a" * 24
KEY_B = "b" * 24


def start(**overrides):
    config = Config(host="127.0.0.1", port=0, primary_latency=0.0, fallback_latency=0.0, **overrides)
    httpd, app = create_server(config)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, app, f"http://127.0.0.1:{httpd.server_address[1]}"


def chat(base, headers=None, prompt="hello"):
    req = urllib.request.Request(
        base + "/v1/chat",
        data=json.dumps({"prompt": prompt, "max_tokens": 8}).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


class ContentLengthTests(unittest.TestCase):
    def test_negative_content_length_is_rejected_not_waited_on(self):
        httpd, _, base = start(rate_limit_rps=1000, rate_limit_burst=1000)
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        with socket.create_connection(("127.0.0.1", httpd.server_address[1]), timeout=3) as sock:
            sock.sendall(b"POST /v1/chat HTTP/1.1\r\nHost: x\r\nContent-Length: -1\r\n\r\n")
            status_line = sock.recv(200).split(b"\r\n")[0]  # would raise socket.timeout if the handler hung
        self.assertIn(b"400", status_line)


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.httpd, self.app, self.base = start(
            api_keys=f"{KEY_A}:team-a,{KEY_B}:team-b", rate_limit_rps=1000, rate_limit_burst=1000
        )
        self.addCleanup(lambda: (self.httpd.shutdown(), self.httpd.server_close()))

    def test_requests_without_a_valid_key_are_refused(self):
        self.assertEqual(chat(self.base)[0], 401)
        self.assertEqual(chat(self.base, {"Authorization": "Bearer wrong-key-wrong-key-1234"})[0], 401)
        self.assertEqual(chat(self.base, {"Authorization": KEY_A})[0], 401)  # scheme is required

    def test_valid_key_works_and_the_tenant_comes_from_the_key(self):
        self.assertEqual(chat(self.base, {"Authorization": f"Bearer {KEY_A}", "X-Tenant": "someone-else"})[0], 200)
        self.assertGreater(self.app.gateway.budget.used("team-a"), 0)
        self.assertEqual(self.app.gateway.budget.used("someone-else"), 0)

    def test_rotating_the_tenant_header_no_longer_buys_a_fresh_budget(self):
        for i in range(5):
            chat(self.base, {"Authorization": f"Bearer {KEY_A}", "X-Tenant": f"bot{i}"}, prompt=f"p{i}")
        self.assertEqual(self.app.gateway.budget.used("bot0"), 0)

    def test_key_format_is_validated(self):
        with self.assertRaises(ValueError):
            parse_api_keys("short:team")
        with self.assertRaises(ValueError):
            parse_api_keys(f"{KEY_A}")
        self.assertEqual(parse_api_keys(f"{KEY_A}:team-a"), {KEY_A: "team-a"})


class GlobalRateLimitTests(unittest.TestCase):
    def test_rotating_tenant_names_cannot_exceed_the_global_ceiling(self):
        httpd, _, base = start(
            rate_limit_rps=1000, rate_limit_burst=1000, global_rate_limit_rps=0.001, global_rate_limit_burst=5
        )
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        statuses = [chat(base, {"X-Tenant": f"bot{i}"}, prompt=f"p{i}")[0] for i in range(20)]
        self.assertEqual(statuses.count(200), 5)
        self.assertEqual(statuses.count(429), 15)


if __name__ == "__main__":
    unittest.main()
