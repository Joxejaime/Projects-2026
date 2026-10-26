"""End-to-end tests against a real server on an ephemeral port."""

import json
import threading
import unittest
import urllib.error
import urllib.request

from gateway.config import Config
from gateway.server import create_server

ADMIN = "test-admin-token"


def request(base, method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode(), dict(resp.headers)
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode(), dict(err.headers)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = Config(
            host="127.0.0.1",
            port=0,
            admin_token=ADMIN,
            primary_latency=0.0,
            fallback_latency=0.0,
            breaker_failure_threshold=3,
            breaker_recovery_timeout=60,
            max_attempts=1,
            rate_limit_rps=1000,
            rate_limit_burst=1000,
        )
        cls.httpd, cls.app = create_server(config)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        request(self.base, "POST", "/admin/faults", {"reset": True}, {"X-Admin-Token": ADMIN})

    def chat(self, prompt, **kw):
        status, body, headers = request(self.base, "POST", "/v1/chat", {"prompt": prompt, **kw}, {"X-Tenant": "tests"})
        return status, json.loads(body), headers

    def test_health_and_ready(self):
        self.assertEqual(request(self.base, "GET", "/healthz")[0], 200)
        self.assertEqual(request(self.base, "GET", "/readyz")[0], 200)

    def test_chat_success_and_request_id_header(self):
        status, body, headers = self.chat("hello from tests one")
        self.assertEqual(status, 200)
        self.assertEqual(body["outcome"], "ok")
        self.assertIn("X-Request-Id", headers)

    def test_validation_errors(self):
        self.assertEqual(self.chat("")[0], 400)
        self.assertEqual(self.chat("hi", max_tokens=0)[0], 400)
        self.assertEqual(self.chat("hi", max_tokens=True)[0], 400)
        status, _, _ = request(self.base, "POST", "/v1/chat", {"prompt": "x"}, {"X-Tenant": "bad tenant!"})
        self.assertEqual(status, 400)
        self.assertEqual(request(self.base, "GET", "/nope")[0], 404)
        self.assertEqual(request(self.base, "GET", "/v1/chat")[0], 405)

    def test_oversized_prompt_rejected(self):
        self.assertEqual(self.chat("x" * 9000)[0], 413)

    def test_metrics_endpoint_exposes_gateway_series(self):
        self.chat("metrics probe prompt")
        status, text, headers = request(self.base, "GET", "/metrics")
        self.assertEqual(status, 200)
        self.assertIn("text/plain", headers["Content-Type"])
        for series in ("gateway_requests_total", "gateway_circuit_state", "gateway_request_duration_seconds_bucket"):
            self.assertIn(series, text)

    def test_admin_requires_token(self):
        self.assertEqual(request(self.base, "GET", "/admin/state")[0], 403)
        self.assertEqual(request(self.base, "GET", "/admin/state", headers={"X-Admin-Token": ADMIN})[0], 200)

    def test_fault_injection_triggers_fallback_then_recovers(self):
        admin = {"X-Admin-Token": ADMIN}
        request(self.base, "POST", "/admin/faults", {"provider": "primary", "error_rate": 1.0}, admin)
        status, body, _ = self.chat("fault injection prompt A")
        self.assertEqual((status, body["outcome"], body["provider"]), (200, "degraded", "fallback"))
        request(self.base, "POST", "/admin/faults", {"reset": True}, admin)
        # circuit is still closed (1 failure < threshold 3), so primary serves again immediately
        status, body, _ = self.chat("fault injection prompt B")
        self.assertEqual((status, body["outcome"]), (200, "ok"))

    def test_admin_input_validation(self):
        admin = {"X-Admin-Token": ADMIN}
        self.assertEqual(request(self.base, "POST", "/admin/faults", {"provider": "x"}, admin)[0], 400)
        self.assertEqual(
            request(self.base, "POST", "/admin/faults", {"provider": "primary", "error_rate": 7}, admin)[0], 400
        )


class AdminDisabledTests(unittest.TestCase):
    def test_admin_routes_do_not_exist_without_token(self):
        httpd, _ = create_server(Config(host="127.0.0.1", port=0))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            self.assertEqual(request(base, "GET", "/admin/state")[0], 404)
            self.assertEqual(request(base, "POST", "/admin/faults", {"reset": True})[0], 404)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
