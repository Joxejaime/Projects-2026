import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path

import yaml

from slogen import cli
from slogen.model import load_slo_file, parse_duration
from slogen.policies import POLICIES
from slogen.rules import build_document, error_ratio_expr, render
from slogen.simulate import Incident, budget_consumed, budget_report, simulate

ROOT = Path(__file__).resolve().parent.parent
SLO_FILE = ROOT / "slo" / "shop-api.yaml"

VALID = """
service: demo-svc
owner: team-demo
slos:
  - name: api-availability
    sli: {type: availability, metric: http_requests_total, selector: 'job="api"', bad: 'code=~"5.."'}
    objective: 99.9
  - name: api-latency
    sli: {type: latency, metric: http_request_duration_seconds, threshold_seconds: 0.5}
    objective: 99
    window: 7d
"""


def write_tmp(text: str) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)  # noqa: SIM115
    tmp.write(text)
    tmp.close()
    return Path(tmp.name)


class ModelTests(unittest.TestCase):
    def test_duration_parsing(self):
        self.assertEqual(parse_duration("30d"), 30 * 86400)
        self.assertEqual(parse_duration("90m"), 5400)
        for bad in ("30", "d", "1.5h", "-1d", "30days"):
            with self.subTest(bad), self.assertRaises(ValueError):
                parse_duration(bad)

    def test_repository_slo_file_is_valid(self):
        slos, errors = load_slo_file(SLO_FILE)
        self.assertEqual(errors, [])
        self.assertEqual([s.name for s in slos], ["checkout-availability", "checkout-latency", "catalog-availability"])

    def test_valid_file_defaults(self):
        slos, errors = load_slo_file(write_tmp(VALID))
        self.assertEqual(errors, [])
        self.assertEqual(slos[0].window, "30d")
        self.assertAlmostEqual(slos[0].error_budget, 0.001)
        self.assertEqual(slos[1].window_seconds, 7 * 86400)

    def test_validation_errors(self):
        cases = {
            "service: Bad Name\nslos: [{name: a, sli: {type: availability, metric: m, bad: 'code=\"5\"'}, objective: 99}]": "service",
            "service: s\nslos: []": "non-empty",
            "service: s\nslos: [{name: a, sli: {type: weird, metric: m}, objective: 99}]": "sli.type",
            "service: s\nslos: [{name: a, sli: {type: availability, metric: m}, objective: 99}]": "sli.bad",
            "service: s\nslos: [{name: a, sli: {type: latency, metric: m}, objective: 99}]": "threshold_seconds",
            "service: s\nslos: [{name: a, sli: {type: availability, metric: 'bad metric!', bad: 'c=\"5\"'}, objective: 99}]": "metric",
            "service: s\nslos: [{name: a, sli: {type: availability, metric: m, bad: 'c=\"5\"'}, objective: 100}]": "objective",
            "service: s\nslos: [{name: a, sli: {type: availability, metric: m, bad: 'c=\"5\"'}, objective: 99, window: forever}]": "duration",
            "service: s\nslos: [{name: a, sli: {type: availability, metric: m, selector: 'x}{y', bad: 'c=\"5\"'}, objective: 99}]": "selector",
        }
        for text, expected in cases.items():
            with self.subTest(expected):
                _, errors = load_slo_file(write_tmp(text))
                self.assertTrue(any(expected in e for e in errors), errors)

    def test_duplicate_names_rejected(self):
        text = VALID.replace("api-latency", "api-availability")
        _, errors = load_slo_file(write_tmp(text))
        self.assertTrue(any("duplicate" in e for e in errors))


class RuleGenerationTests(unittest.TestCase):
    def setUp(self):
        self.slos, _ = load_slo_file(SLO_FILE)
        self.doc = build_document(self.slos)

    def rules(self, kind):
        return [r for g in self.doc["groups"] for r in g["rules"] if kind in r]

    def test_expressions(self):
        avail, latency = self.slos[0], self.slos[1]
        self.assertEqual(
            error_ratio_expr(avail, "5m"),
            'sum(rate(http_requests_total{route="/checkout",code=~"5.."}[5m])) / sum(rate(http_requests_total{route="/checkout"}[5m]))',
        )
        self.assertEqual(
            error_ratio_expr(latency, "1h"),
            '1 - (sum(rate(http_request_duration_seconds_bucket{route="/checkout",le="0.3"}[1h])) '
            '/ sum(rate(http_request_duration_seconds_count{route="/checkout"}[1h])))',
        )

    def test_burn_rate_thresholds_follow_the_error_budget(self):
        alerts = {a["alert"]: a for a in self.rules("alert")}
        # 99.9% objective -> budget 0.001 -> thresholds are burn_rate * 0.001
        expected = {"FastBurn": 0.0144, "ModerateBurn": 0.006, "SlowBurn": 0.003, "Drift": 0.001}
        for policy, threshold in expected.items():
            expr = alerts[f"CheckoutAvailability{policy}"]["expr"]
            found = [float(x) for x in re.findall(r"> ([0-9.]+)", expr)]
            self.assertEqual(found, [threshold, threshold], expr)
        # 99.0% latency objective -> budget 0.01
        self.assertIn("> 0.144", alerts["CheckoutLatencyFastBurn"]["expr"])

    def test_alert_set_and_severities(self):
        alerts = self.rules("alert")
        self.assertEqual(len(alerts), len(self.slos) * len(POLICIES))
        severities = {a["alert"]: a["labels"]["severity"] for a in alerts}
        self.assertEqual(severities["CheckoutAvailabilityFastBurn"], "page")
        self.assertEqual(severities["CheckoutAvailabilitySlowBurn"], "ticket")
        for alert in alerts:
            self.assertIn("summary", alert["annotations"])
            self.assertEqual(alert["labels"]["service"], "shop-api")

    def test_every_alert_references_a_recording_rule_that_exists(self):
        recorded = {(r["record"], r["labels"]["slo"]) for r in self.rules("record")}
        for alert in self.rules("alert"):
            slo = alert["labels"]["slo"]
            for name in re.findall(r"(slo:sli_error:ratio_rate\w+)\{", alert["expr"]):
                self.assertIn((name, slo), recorded, f"{alert['alert']} uses undefined {name}")

    def test_runbook_links_point_at_files_that_exist(self):
        for alert in self.rules("alert"):
            runbook = alert["annotations"].get("runbook")
            if runbook:
                self.assertTrue((ROOT / runbook).exists(), f"{alert['alert']}: {runbook} missing")

    def test_rendering_is_deterministic_valid_yaml(self):
        first, second = render(self.slos, "slo/shop-api.yaml"), render(self.slos, "slo/shop-api.yaml")
        self.assertEqual(first, second)
        self.assertEqual(yaml.safe_load(first), self.doc)
        self.assertTrue(first.startswith("# GENERATED"))

    def test_committed_generated_file_is_current(self):
        committed = (ROOT / "generated" / "shop-api.rules.yml").read_text()
        self.assertEqual(committed, render(self.slos, "slo/shop-api.yaml"), "run `make generate`")


class SimulationTests(unittest.TestCase):
    def by_name(self, results):
        return {r.policy.name: r for r in results}

    def test_moderate_incident_pages_fast_burn_only(self):
        r = self.by_name(simulate(99.9, "30d", Incident(start=10, duration=30, error_ratio=0.05)))
        self.assertTrue(r["FastBurn"].fired)
        self.assertEqual(r["FastBurn"].detection_delay, 18)
        for slow in ("ModerateBurn", "SlowBurn", "Drift"):
            self.assertFalse(r[slow].fired, slow)

    def test_total_outage_pages_within_a_few_minutes(self):
        r = self.by_name(simulate(99.9, "30d", Incident(0, 60, 1.0)))
        self.assertLessEqual(r["FastBurn"].detection_delay, 3)

    def test_tiny_blip_never_alerts(self):
        results = simulate(99.9, "30d", Incident(0, 5, 0.005))
        self.assertFalse(any(r.fired for r in results))

    def test_slow_leak_only_creates_tickets(self):
        # 0.4% errors is a 4x burn: below the 6x page thresholds, above the 3x ticket threshold
        r = self.by_name(simulate(99.9, "30d", Incident(0, 2 * 1440, 0.004)))
        self.assertFalse(r["FastBurn"].fired)
        self.assertFalse(r["ModerateBurn"].fired)
        self.assertTrue(r["SlowBurn"].fired)

    def test_alerts_clear_after_the_incident_ends(self):
        r = self.by_name(simulate(99.9, "30d", Incident(0, 30, 0.05)))
        self.assertIsNotNone(r["FastBurn"].resolved_after_end)
        self.assertLess(r["FastBurn"].resolved_after_end, 10)

    def test_budget_arithmetic(self):
        # 5% errors for 30 minutes against 99.9%/30d: 0.05*30 / (43200*0.001) = 3.47% of the budget
        consumed = budget_consumed(Incident(0, 30, 0.05), 0.001, 43200)
        self.assertAlmostEqual(consumed, 0.034722, places=5)

    def test_budget_report(self):
        r = budget_report(99.9, "30d", good=9_995_000, total=10_000_000)
        self.assertAlmostEqual(r["budget_consumed"], 0.5)
        self.assertTrue(r["met"])
        self.assertAlmostEqual(r["full_outage_minutes_allowed"], 43.2)
        self.assertFalse(budget_report(99.9, "30d", good=9_980_000, total=10_000_000)["met"])
        exact = budget_report(99.9, "30d", good=9_990_000, total=10_000_000)  # exactly on the objective
        self.assertTrue(exact["met"])
        self.assertEqual(exact["budget_remaining"], 0.0)
        self.assertLess(budget_report(99.9, "30d", good=9_970_000, total=10_000_000)["budget_remaining"], -1)  # overspent
        with self.assertRaises(ValueError):
            budget_report(99.9, "30d", good=11, total=10)


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_check_ok_and_failure(self):
        self.assertEqual(self.run_cli("check", str(SLO_FILE))[0], 0)
        bad = write_tmp("service: s\nslos: []")
        code, _, err = self.run_cli("check", str(bad))
        self.assertEqual(code, 1)
        self.assertIn("ERROR", err)

    def test_generate_and_stale_detection(self):
        out = Path(tempfile.mkdtemp()) / "rules.yml"
        self.assertEqual(self.run_cli("generate", str(SLO_FILE), "-o", str(out))[0], 0)
        self.assertEqual(self.run_cli("generate", str(SLO_FILE), "-o", str(out), "--check")[0], 0)
        out.write_text(out.read_text() + "# drift\n")
        self.assertEqual(self.run_cli("generate", str(SLO_FILE), "-o", str(out), "--check")[0], 1)

    def test_simulate_and_budget_commands(self):
        code, out, _ = self.run_cli("simulate", "--objective", "99.9", "--duration", "30", "--error-ratio", "0.05")
        self.assertEqual(code, 0)
        self.assertIn("FastBurn", out)
        self.assertIn("3.47%", out)
        code, out, _ = self.run_cli("budget", "--objective", "99.9", "--good", "9995000", "--total", "10000000")
        self.assertIn("50.0%", out)
        self.assertEqual(self.run_cli("budget", "--objective", "99.9", "--good", "5", "--total", "1")[0], 2)


if __name__ == "__main__":
    unittest.main()
