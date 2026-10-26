import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "demo"))
import shop  # noqa: E402  (demo service)

from chaos import runner  # noqa: E402

TOKEN = "test-token"


def call(base, method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()


class DemoServiceFixture(unittest.TestCase):
    def start(self, token=TOKEN):
        httpd, state = shop.create_server("127.0.0.1", 0, token)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        return f"http://127.0.0.1:{httpd.server_address[1]}", state


class DemoServiceTests(DemoServiceFixture):
    def test_metrics_expose_the_series_the_slos_use(self):
        base, _ = self.start()
        call(base, "GET", "/checkout")
        _, text = call(base, "GET", "/metrics")
        self.assertIn('http_requests_total{route="/checkout",code="200"} 1', text)
        self.assertIn('http_request_duration_seconds_bucket{route="/checkout",le="0.3"}', text)  # the latency SLO bucket
        self.assertIn('http_request_duration_seconds_count{route="/checkout"} 1', text)

    def test_faults_are_per_route(self):
        base, _ = self.start()
        headers = {"X-Admin-Token": TOKEN}
        call(base, "POST", "/admin/faults", {"route": "/checkout", "error_rate": 1.0}, headers)
        self.assertEqual(call(base, "GET", "/checkout")[0], 500)
        self.assertEqual(call(base, "GET", "/catalog")[0], 200)
        call(base, "POST", "/admin/faults", {"reset": True}, headers)
        self.assertEqual(call(base, "GET", "/checkout")[0], 200)

    def test_admin_requires_token_and_validates(self):
        base, _ = self.start()
        self.assertEqual(call(base, "POST", "/admin/faults", {"reset": True})[0], 403)
        headers = {"X-Admin-Token": TOKEN}
        self.assertEqual(call(base, "POST", "/admin/faults", {"route": "/nope"}, headers)[0], 400)
        self.assertEqual(call(base, "POST", "/admin/faults", {"route": "/checkout", "error_rate": 3}, headers)[0], 400)

    def test_admin_absent_without_token(self):
        base, _ = self.start(token="")
        self.assertEqual(call(base, "POST", "/admin/faults", {"reset": True})[0], 404)


class RunnerHelperTests(unittest.TestCase):
    def test_compute_stats(self):
        samples = [runner.Sample(0, True, 0.1)] * 8 + [runner.Sample(0, False, 0.5)] * 2
        stats = runner.compute_stats(samples, slow_ms=300)
        self.assertEqual((stats.n, stats.error_ratio, stats.slow_ratio), (10, 0.2, 0.2))
        self.assertEqual(runner.compute_stats([], 300).n, 0)

    def test_server_side_ratio_from_scrapes(self):
        def metrics(ok, err, fast, total):
            return (
                f'http_requests_total{{route="/checkout",code="200"}} {ok}\n'
                f'http_requests_total{{route="/checkout",code="500"}} {err}\n'
                f'http_requests_total{{route="/catalog",code="500"}} 999\n'
                f'http_request_duration_seconds_bucket{{route="/checkout",le="0.3"}} {fast}\n'
                f'http_request_duration_seconds_count{{route="/checkout"}} {total}\n'
            )

        def parse(text):
            series = {}
            for line in text.splitlines():
                m = runner.METRIC_RE.match(line)
                labels = dict(runner.LABEL_RE.findall(m.group(2)))
                series[(m.group(1), tuple(sorted(labels.items())))] = float(m.group(3))
            return series

        before, after = parse(metrics(100, 0, 100, 100)), parse(metrics(170, 30, 120, 200))
        self.assertAlmostEqual(runner.server_bad_ratio(before, after, "/checkout", "availability", 300), 0.30)
        self.assertAlmostEqual(runner.server_bad_ratio(before, after, "/checkout", "latency", 300), 0.80)
        self.assertIsNone(runner.server_bad_ratio(before, before, "/checkout", "availability", 300))


class ExperimentTests(DemoServiceFixture):
    def scenario(self, base, **overrides):
        s = {
            "name": "test",
            "hypothesis": "h",
            "target": {
                "base_url": base,
                "path": "/checkout",
                "rps": 30,
                "control_path": "/catalog",
                "control_rps": 10,
                "admin_token": TOKEN,
            },  # fmt: skip
            "steady_state": {"duration_seconds": 1.5, "max_error_ratio": 0.01, "max_slow_ratio": 0.01},
            "injection": {"fault": {"route": "/checkout", "error_rate": 0.4}, "duration_seconds": 3},
            "abort": {"error_ratio_above": 0.9, "check_window_seconds": 2},
            "recovery": {"max_seconds": 8, "error_ratio_below": 0.01, "check_window_seconds": 1},
            "expect": {"sli": "availability", "objective": 99.9, "alerts": ["X"]},
        }
        s.update(overrides)
        return s

    def test_hypothesis_held_and_faults_cleared(self):
        base, state = self.start()
        report = runner.run_experiment(self.scenario(base), log=lambda *_: None)
        self.assertEqual(report["verdict"], "HYPOTHESIS_HELD", report)
        self.assertEqual(report["exit_code"], 0)
        self.assertTrue(all(report["checks"].values()))
        self.assertGreater(report["phases"]["injection"]["error_ratio"], 0.2)
        self.assertEqual(report["phases"]["control_during_fault"]["error_ratio"], 0.0)
        self.assertTrue(report["projection"]["if_sustained"]["FastBurn"]["fires"])
        self.assertEqual(state.faults["/checkout"]["error_rate"], 0.0)  # left clean
        self.assertIn("## Checks", runner.to_markdown(report))

    def test_guardrail_aborts_and_still_cleans_up(self):
        base, state = self.start()
        scenario = self.scenario(base)
        scenario["injection"]["fault"]["error_rate"] = 1.0
        scenario["abort"]["error_ratio_above"] = 0.5
        report = runner.run_experiment(scenario, log=lambda *_: None)
        self.assertEqual((report["verdict"], report["exit_code"]), ("ABORTED", 2))
        self.assertTrue(report["phases"]["injection"]["aborted"])
        self.assertLess(report["phases"]["injection"]["seconds"], 3)  # stopped early
        self.assertEqual(state.faults["/checkout"]["error_rate"], 0.0)

    def test_failed_precondition_never_injects(self):
        base, state = self.start()
        scenario = self.scenario(base)
        scenario["steady_state"]["max_error_ratio"] = -1  # impossible: the system can never be "steady"
        report = runner.run_experiment(scenario, log=lambda *_: None)
        self.assertEqual((report["verdict"], report["exit_code"]), ("PRECONDITION_FAILED", 3))
        self.assertNotIn("injection", report["phases"])
        self.assertEqual(state.faults["/checkout"]["error_rate"], 0.0)

    def test_hypothesis_fails_when_fault_has_no_effect(self):
        base, _ = self.start()
        scenario = self.scenario(base)
        scenario["injection"]["fault"] = {"route": "/checkout", "error_rate": 0.0}  # nothing injected
        report = runner.run_experiment(scenario, log=lambda *_: None)
        self.assertEqual(report["verdict"], "HYPOTHESIS_FAILED")
        self.assertFalse(report["checks"]["fault visible to clients"])

    def test_latency_scenario_shows_slow_but_not_failing(self):
        base, _ = self.start()
        scenario = self.scenario(base)
        scenario["injection"]["fault"] = {"route": "/checkout", "error_rate": 0.0, "extra_latency_ms": 400}
        scenario["expect"] = {"sli": "latency", "objective": 99.0, "error_ratio_at_most": 0.01}
        report = runner.run_experiment(scenario, log=lambda *_: None)
        self.assertEqual(report["verdict"], "HYPOTHESIS_HELD", report)
        self.assertEqual(report["phases"]["injection"]["error_ratio"], 0.0)
        self.assertGreater(report["phases"]["injection"]["slow_ratio"], 0.9)
        self.assertGreater(report["server_side_sli_bad_ratio"], 0.9)


if __name__ == "__main__":
    unittest.main()
