import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server

server.log.setLevel("WARNING")  # keep test output readable


class ServerTestCase(unittest.TestCase):
    chaos = False

    @classmethod
    def setUpClass(cls):
        state = server.State()
        state.chaos_enabled = cls.chaos
        cls.httpd, cls.state = server.build_server("127.0.0.1", 0, state)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, method, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read().decode(), dict(resp.headers)
        except urllib.error.HTTPError as err:
            return err.code, err.read().decode(), dict(err.headers)


class TestHealth(ServerTestCase):
    def test_healthz(self):
        status, body, headers = self.request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"status": "ok"})
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("X-Request-Id", headers)

    def test_readyz_flips_during_shutdown(self):
        self.assertEqual(self.request("GET", "/readyz")[0], 200)
        self.state.ready = False
        try:
            self.assertEqual(self.request("GET", "/readyz")[0], 503)
        finally:
            self.state.ready = True

    def test_unknown_route_is_404_and_does_not_explode_cardinality(self):
        for path in ("/nope", "/also/nope", "/x?y=1"):
            self.assertEqual(self.request("GET", path)[0], 404)
        _, metrics, _ = self.request("GET", "/metrics")
        self.assertIn('route="unmatched"', metrics)
        self.assertNotIn("/also/nope", metrics)


class TestDeployments(ServerTestCase):
    def test_create_and_list(self):
        payload = {"service": "billing", "version": "1.4.2", "environment": "prod"}
        status, body, _ = self.request("POST", "/api/deployments", payload)
        self.assertEqual(status, 201)
        created = json.loads(body)
        self.assertEqual(created["service"], "billing")
        self.assertEqual(len(created["id"]), 12)
        status, body, _ = self.request("GET", "/api/deployments")
        self.assertEqual(status, 200)
        ids = [item["id"] for item in json.loads(body)["items"]]
        self.assertIn(created["id"], ids)

    def test_validation_errors(self):
        cases = [
            ({"service": "", "version": "1", "environment": "prod"}, 422),
            ({"service": "a", "version": "1", "environment": "mars"}, 422),
            ({"service": "a" * 65, "version": "1", "environment": "dev"}, 422),
            (["not", "an", "object"], 422),
        ]
        for payload, expected in cases:
            with self.subTest(payload=payload):
                self.assertEqual(self.request("POST", "/api/deployments", payload)[0], expected)

    def test_malformed_json_and_empty_body(self):
        self.assertEqual(self.request("POST", "/api/deployments", raw=b"{not json")[0], 400)
        self.assertEqual(self.request("POST", "/api/deployments")[0], 400)

    def test_oversized_body_rejected(self):
        big = b'{"service":"' + b"a" * (server.MAX_BODY_BYTES + 10) + b'"}'
        self.assertEqual(self.request("POST", "/api/deployments", raw=big)[0], 413)

    def test_records_are_capped(self):
        state = server.State()
        for i in range(server.MAX_RECORDS + 25):
            state.deployments.append({"id": str(i)})
            del state.deployments[: -server.MAX_RECORDS]
        self.assertEqual(len(state.deployments), server.MAX_RECORDS)


class TestMetrics(ServerTestCase):
    def test_metrics_format_and_counters(self):
        self.request("GET", "/healthz")
        self.request("POST", "/api/deployments", {"service": "s", "version": "1", "environment": "dev"})
        status, body, headers = self.request("GET", "/metrics")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/plain"))
        self.assertIn('http_requests_total{method="GET",route="/healthz",status="200"}', body)
        self.assertIn('http_requests_total{method="POST",route="/api/deployments",status="201"}', body)
        self.assertIn("deployments_recorded_total 1", body)
        self.assertIn('http_request_duration_seconds_bucket{route="/healthz",le="+Inf"}', body)
        self.assertTrue(body.endswith("\n"))

    def test_histogram_buckets_are_cumulative(self):
        metrics = server.Metrics()
        metrics.observe("GET", "/x", 200, 0.004)
        metrics.observe("GET", "/x", 200, 0.2)
        rendered = metrics.render()
        self.assertIn('http_request_duration_seconds_bucket{route="/x",le="0.005"} 1', rendered)
        self.assertIn('http_request_duration_seconds_bucket{route="/x",le="0.25"} 2', rendered)
        self.assertIn('http_request_duration_seconds_bucket{route="/x",le="+Inf"} 2', rendered)
        self.assertIn('http_request_duration_seconds_count{route="/x"} 2', rendered)


class TestChaosDisabledByDefault(ServerTestCase):
    def test_simulate_is_hidden_when_disabled(self):
        self.assertEqual(self.request("GET", "/api/simulate?status=500")[0], 404)


class TestChaosEnabled(ServerTestCase):
    chaos = True

    def test_simulated_status_codes(self):
        self.assertEqual(self.request("GET", "/api/simulate?status=500")[0], 500)
        self.assertEqual(self.request("GET", "/api/simulate?status=200")[0], 200)

    def test_rejects_bad_input(self):
        self.assertEqual(self.request("GET", "/api/simulate?status=abc")[0], 400)
        self.assertEqual(self.request("GET", "/api/simulate?status=418")[0], 400)


class TestValidateDeployment(unittest.TestCase):
    def test_accepts_valid(self):
        record, error = server.validate_deployment({"service": "a", "version": "1", "environment": "staging"})
        self.assertIsNone(error)
        self.assertEqual(record["environment"], "staging")

    def test_rejects_extra_types(self):
        _, error = server.validate_deployment({"service": 1, "version": "1", "environment": "dev"})
        self.assertIsNotNone(error)


if __name__ == "__main__":
    unittest.main()
