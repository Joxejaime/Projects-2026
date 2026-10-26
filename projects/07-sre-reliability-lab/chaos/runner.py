#!/usr/bin/env python3
"""Chaos experiment runner: steady state -> inject fault -> recover, with a safety abort.

An experiment is a YAML file (see chaos/scenarios/). The runner drives steady traffic at the
target, measures client-side error and latency ratios in sliding windows, injects the fault
through the demo service's admin API, and ALWAYS clears the fault when it finishes or is
interrupted. It reports whether the hypothesis held and projects what the observed error
ratio would mean for the SLO if it were sustained (using slogen's burn-rate simulator).

Exit codes: 0 hypothesis held | 1 hypothesis failed | 2 aborted by guardrail | 3 precondition failed
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from slogen.simulate import Incident, simulate  # noqa: E402

EXIT_HELD, EXIT_FAILED, EXIT_ABORTED, EXIT_PRECONDITION = 0, 1, 2, 3


@dataclass(frozen=True)
class Sample:
    t: float
    ok: bool
    latency: float


@dataclass(frozen=True)
class Stats:
    n: int
    error_ratio: float
    slow_ratio: float
    p50_ms: float
    p95_ms: float

    def as_dict(self) -> dict:
        return {k: round(v, 4) if isinstance(v, float) else v for k, v in self.__dict__.items()}


def compute_stats(samples: list[Sample], slow_ms: float) -> Stats:
    if not samples:
        return Stats(0, 0.0, 0.0, 0.0, 0.0)
    lat = sorted(s.latency for s in samples)

    def pct(p: float) -> float:
        return lat[min(len(lat) - 1, round(p * (len(lat) - 1)))] * 1000

    return Stats(
        n=len(samples),
        error_ratio=sum(not s.ok for s in samples) / len(samples),
        slow_ratio=sum(s.latency * 1000 > slow_ms for s in samples) / len(samples),
        p50_ms=pct(0.5),
        p95_ms=pct(0.95),
    )


class Traffic:
    """Open-loop request generator that records every outcome."""

    def __init__(self, url: str, rps: float, timeout: float = 5.0):
        self.url, self.rps, self.timeout = url, rps, timeout
        self.samples: deque[Sample] = deque()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _one(self) -> None:
        started = time.monotonic()
        try:
            with urllib.request.urlopen(self.url, timeout=self.timeout) as resp:  # noqa: S310
                resp.read()
                ok = 200 <= resp.status < 400
        except urllib.error.HTTPError:
            ok = False
        except Exception:  # noqa: BLE001
            ok = False
        done = time.monotonic()
        with self._lock:
            self.samples.append(Sample(done, ok, done - started))

    def _run(self) -> None:
        with ThreadPoolExecutor(max_workers=max(8, int(self.rps * 3))) as pool:
            begin, i = time.monotonic(), 0
            while not self._stop.is_set():
                pool.submit(self._one)
                i += 1
                self._stop.wait(max(0.0, begin + i / self.rps - time.monotonic()))

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def since(self, t0: float, t1: float | None = None) -> list[Sample]:
        with self._lock:
            return [s for s in self.samples if s.t >= t0 and (t1 is None or s.t < t1)]


def admin(base: str, token: str, payload: dict) -> None:
    req = urllib.request.Request(  # noqa: S310
        base + "/admin/faults",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-Admin-Token": token},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
        resp.read()


METRIC_RE = re.compile(r"^(http_requests_total|http_request_duration_seconds_(?:bucket|count))\{([^}]*)\}\s+([0-9.eE+-]+)$")
LABEL_RE = re.compile(r'(\w+)="([^"]*)"')


def scrape(base: str) -> dict:
    """Read the service's own /metrics and keep the series the SLIs are built from."""
    with urllib.request.urlopen(base + "/metrics", timeout=5) as resp:  # noqa: S310
        text = resp.read().decode()
    series: dict = {}
    for line in text.splitlines():
        match = METRIC_RE.match(line)
        if match:
            labels = dict(LABEL_RE.findall(match.group(2)))
            series[(match.group(1), tuple(sorted(labels.items())))] = float(match.group(3))
    return series


def server_bad_ratio(before: dict, after: dict, route: str, sli: str, slow_ms: float) -> float | None:
    """Bad-event ratio for ``route`` between two scrapes, computed the same way the SLO rules do."""

    def delta(name: str, **labels) -> float:
        total = 0.0
        for (metric, items), value in after.items():
            d = dict(items)
            if metric == name and d.get("route") == route and all(d.get(k) == v for k, v in labels.items()):
                total += value - before.get((metric, items), 0.0)
        return total

    if sli == "latency":
        count = delta("http_request_duration_seconds_count")
        good = delta("http_request_duration_seconds_bucket", le=format(slow_ms / 1000, "g"))
        return None if count <= 0 else 1 - good / count
    total, bad = 0.0, 0.0
    for (metric, items), value in after.items():
        d = dict(items)
        if metric == "http_requests_total" and d.get("route") == route:
            inc = value - before.get((metric, items), 0.0)
            total += inc
            bad += inc if d.get("code", "").startswith("5") else 0.0
    return None if total <= 0 else bad / total


def run_experiment(scenario: dict, log=print) -> dict:
    target = scenario["target"]
    base = target["base_url"].rstrip("/")
    token = target.get("admin_token", "")
    ss, inj, ab, rec = scenario["steady_state"], scenario["injection"], scenario["abort"], scenario["recovery"]
    slow_ms = float(scenario.get("slow_threshold_ms", 300))
    expect = scenario.get("expect", {})
    sli = expect.get("sli", "availability")
    traffic = Traffic(base + target["path"], float(target["rps"]))
    control_path = target.get("control_path")
    control = Traffic(base + control_path, float(target.get("control_rps", 5))) if control_path else None
    report: dict = {
        "name": scenario["name"],
        "hypothesis": scenario["hypothesis"].strip(),
        "phases": {},
        "recovery_window_seconds": rec["check_window_seconds"],
    }

    def signal_of(stats: Stats) -> float:
        return stats.slow_ratio if sli == "latency" else stats.error_ratio

    try:
        admin(base, token, {"reset": True})
        traffic.start()
        if control:
            control.start()

        # 1. steady state must hold before we touch anything
        t0 = time.monotonic()
        time.sleep(ss["duration_seconds"])
        steady = compute_stats(traffic.since(t0), slow_ms)
        report["phases"]["steady_state"] = steady.as_dict()
        log(f"steady state : {steady.as_dict()}")
        if steady.error_ratio > ss["max_error_ratio"] or steady.slow_ratio > ss["max_slow_ratio"]:
            report.update(verdict="PRECONDITION_FAILED", exit_code=EXIT_PRECONDITION)
            return report

        # 2. inject, watching the abort condition once per second
        fault = dict(inj["fault"])
        scrape_before = scrape(base)
        admin(base, token, fault)
        t_inject = time.monotonic()
        log(f"injected     : {fault}")
        aborted = False
        while time.monotonic() - t_inject < inj["duration_seconds"]:
            time.sleep(1)
            window = compute_stats(traffic.since(time.monotonic() - ab["check_window_seconds"]), slow_ms)
            if window.n >= 5 and window.error_ratio > ab["error_ratio_above"]:
                aborted = True
                log(f"ABORT        : error ratio {window.error_ratio:.2f} exceeded {ab['error_ratio_above']}")
                break
        t_clear = time.monotonic()
        scrape_after = scrape(base)
        admin(base, token, {"reset": True})
        during = compute_stats(traffic.since(t_inject, t_clear), slow_ms)
        report["phases"]["injection"] = {**during.as_dict(), "seconds": round(t_clear - t_inject, 1), "aborted": aborted}
        log(f"during fault : {report['phases']['injection']}")
        server_signal = server_bad_ratio(scrape_before, scrape_after, target["path"], sli, slow_ms)
        report["server_side_sli_bad_ratio"] = None if server_signal is None else round(server_signal, 4)
        log(f"server-side SLI bad ratio during fault: {report['server_side_sli_bad_ratio']}")
        control_ok = True
        if control:
            control_stats = compute_stats(control.since(t_inject, t_clear), slow_ms)
            report["phases"]["control_during_fault"] = {**control_stats.as_dict(), "path": control_path}
            control_ok = control_stats.n > 0 and control_stats.error_ratio <= ss["max_error_ratio"]
            log(f"control route: {report['phases']['control_during_fault']}")

        # 3. recovery: how long until the last few seconds look healthy again?
        recovered_after = None
        while time.monotonic() - t_clear < rec["max_seconds"]:
            time.sleep(1)
            window = compute_stats(traffic.since(time.monotonic() - rec["check_window_seconds"]), slow_ms)
            if window.n >= 5 and window.error_ratio <= rec["error_ratio_below"] and window.slow_ratio <= ss["max_slow_ratio"]:
                recovered_after = round(time.monotonic() - t_clear, 1)
                break
        after = compute_stats(traffic.since(t_clear), slow_ms)
        report["phases"]["recovery"] = {**after.as_dict(), "recovered_after_seconds": recovered_after}
        log(f"recovery     : {report['phases']['recovery']}")

        # 4. verdict + SLO projection
        observed = signal_of(during)
        report["observed_signal"] = round(observed, 4)
        report["projection"] = project(scenario, observed)
        checks = {
            "fault visible to clients": observed > 0.001,
            "fault visible in the server-side SLI": server_signal is not None and server_signal > 0.001,
            "control route unaffected": control_ok,
            "recovered within the limit": recovered_after is not None,
        }
        if "error_ratio_at_most" in expect:
            checks[f"client error ratio <= {expect['error_ratio_at_most']}"] = during.error_ratio <= expect["error_ratio_at_most"]
        report["checks"] = checks
        if aborted:
            report.update(verdict="ABORTED", exit_code=EXIT_ABORTED)
        elif all(checks.values()):
            report.update(verdict="HYPOTHESIS_HELD", exit_code=EXIT_HELD)
        else:
            failed = [name for name, ok in checks.items() if not ok]
            report.update(verdict="HYPOTHESIS_FAILED", exit_code=EXIT_FAILED, reason="failed checks: " + "; ".join(failed))
        return report
    finally:
        traffic.stop()
        if control:
            control.stop()
        try:
            admin(base, token, {"reset": True})  # never leave a fault behind
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: could not clear faults: {exc}", file=sys.stderr)


def project(scenario: dict, observed_ratio: float) -> dict:
    """What would this error/slow ratio do to the SLO if it persisted for 6 hours?"""
    expect = scenario.get("expect", {})
    objective = float(expect.get("objective", 99.9))
    budget = 1 - objective / 100
    results = simulate(objective, "30d", Incident(0, 360, min(1.0, observed_ratio)), tail_minutes=0)
    return {
        "objective": objective,
        "burn_rate": round(observed_ratio / budget, 1),
        "if_sustained": {
            r.policy.name: {"fires": r.fired, "after_minutes": r.detection_delay, "severity": r.policy.severity} for r in results
        },
        "expected_alerts": expect.get("alerts", []),
    }


def to_markdown(report: dict) -> str:
    p = report["phases"]
    lines = [
        f"# Chaos experiment: {report['name']}",
        "",
        f"**Verdict:** `{report['verdict']}`" + (f" ({report['reason']})" if report.get("reason") else ""),
        "",
        "## Hypothesis",
        report["hypothesis"],
        "",
        "## Measurements (client-side)",
        "| Phase | Requests | Error ratio | Slow ratio | p50 | p95 |",
        "|---|---|---|---|---|---|",
    ]
    rows = (
        ("steady_state", "Steady state"),
        ("injection", "During fault"),
        ("control_during_fault", "Control route during fault"),
        ("recovery", "After clearing"),
    )
    for key, label in rows:
        if key in p:
            s = p[key]
            if key == "control_during_fault":
                label += f" (`{s['path']}`)"
            lines.append(
                f"| {label} | {s['n']} | {s['error_ratio']:.1%} | {s['slow_ratio']:.1%} | {s['p50_ms']:.0f} ms | {s['p95_ms']:.0f} ms |"
            )
    server_ratio = report.get("server_side_sli_bad_ratio")
    if server_ratio is not None:
        lines += [
            "",
            f"Server-side SLI bad-event ratio during the fault (from the service's own `/metrics`): **{server_ratio:.1%}**.",
        ]
    if "recovery" in p:
        rec = p["recovery"]["recovered_after_seconds"]
        window = report.get("recovery_window_seconds", "?")
        outcome = f"{rec:.1f} s after the fault was cleared" if rec is not None else "did not recover within the limit"
        lines += [
            "",
            f"Recovery: {outcome}. The recovery check uses a {window} s sliding window, so it cannot report "
            "less than that: the fault itself is removed instantly.",
        ]
    if "checks" in report:
        lines += ["", "## Checks"] + [f"- {'PASS' if ok else 'FAIL'}: {name}" for name, ok in report["checks"].items()]
    if "projection" in report:
        pr = report["projection"]
        lines += [
            "",
            "## SLO projection",
            f"Observed bad-event ratio during the fault: **{report['observed_signal']:.1%}**, a burn rate of "
            f"**{pr['burn_rate']}x** against a {pr['objective']:g}% objective.",
            "If it persisted, the alert policies would behave as follows (simulated, one-minute resolution):",
            "",
            "| Policy | Severity | Fires | After |",
            "|---|---|---|---|",
        ]
        for name, r in pr["if_sustained"].items():
            fires = "yes" if r["fires"] else "no"
            after = f"{r['after_minutes']} min" if r["fires"] else "-"
            lines.append(f"| {name} | {r['severity']} | {fires} | {after} |")
        if pr["expected_alerts"]:
            lines += ["", f"Alerts the scenario expects to fire in the compose stack: {', '.join(pr['expected_alerts'])}."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario")
    parser.add_argument("--url", help="override target.base_url")
    parser.add_argument("--report", help="write a Markdown report here")
    parser.add_argument("--json", help="write the raw JSON result here")
    args = parser.parse_args(argv)
    scenario = yaml.safe_load(Path(args.scenario).read_text())
    if args.url:
        scenario["target"]["base_url"] = args.url
    report = run_experiment(scenario)
    print(f"\nVERDICT: {report['verdict']}")
    if args.report and "projection" in report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(to_markdown(report))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
