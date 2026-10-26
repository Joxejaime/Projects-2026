#!/usr/bin/env python3
"""Build the Grafana dashboard JSON from code so panels stay consistent and reviewable.

    python3 build_dashboard.py           # write dashboards/release-tracker-slo.json
    python3 build_dashboard.py --check   # fail if the committed JSON is stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).parent / "dashboards" / "release-tracker-slo.json"
DS = {"type": "prometheus", "uid": "prometheus"}
SEL = 'job="release-tracker",route=~"/api/.*"'
BUDGET = "slo:availability_error_budget:ratio{service=\"release-tracker\"}"


def target(expr: str, legend: str = "", ref: str = "A") -> dict:
    return {"datasource": DS, "expr": expr, "legendFormat": legend, "refId": ref}


def panel(pid: int, title: str, kind: str, x: int, y: int, w: int, h: int, targets: list[dict], **extra) -> dict:
    base = {
        "id": pid,
        "title": title,
        "type": kind,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": targets,
    }
    base.update(extra)
    return base


def thresholds(*steps: tuple[str, float | None]) -> dict:
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in steps]}


def build() -> dict:
    burn = lambda window: f'slo:availability_error_ratio:rate{window}{{service="release-tracker"}} / {BUDGET}'  # noqa: E731
    panels = [
        panel(
            1, "Availability SLI (1h)", "stat", 0, 0, 6, 5,
            [target('1 - slo:availability_error_ratio:rate1h{service="release-tracker"}')],
            fieldConfig={"defaults": {"unit": "percentunit", "decimals": 3,
                                      "thresholds": thresholds(("red", None), ("orange", 0.99), ("green", 0.995))}, "overrides": []},
        ),
        panel(
            2, "Error-budget burn rate (1h)", "stat", 6, 0, 6, 5,
            [target(burn("1h"))],
            fieldConfig={"defaults": {"unit": "none", "decimals": 2,
                                      "thresholds": thresholds(("green", None), ("orange", 1), ("red", 6))}, "overrides": []},
            description="1.0 = spending budget exactly as fast as the SLO allows. 14.4 on 1h and 5m pages.",
        ),
        panel(
            3, "p95 latency, /api (1h)", "stat", 12, 0, 6, 5,
            [target(f'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{{SEL}}}[1h])))')],
            fieldConfig={"defaults": {"unit": "s", "decimals": 3,
                                      "thresholds": thresholds(("green", None), ("orange", 0.25), ("red", 0.5))}, "overrides": []},
        ),
        panel(
            4, "Firing alerts", "table", 18, 0, 6, 5,
            [target('ALERTS{alertstate="firing"}', ref="A")],
            options={"showHeader": True},
            transformations=[{"id": "organize", "options": {"excludeByName": {"Time": True, "__name__": True, "Value": True, "alertstate": True}}}],
        ),
        panel(
            5, "Request rate by route and status", "timeseries", 0, 5, 12, 8,
            [target('sum by (route, status) (rate(http_requests_total{job="release-tracker"}[1m]))', "{{route}} {{status}}")],
            fieldConfig={"defaults": {"unit": "reqps"}, "overrides": []},
        ),
        panel(
            6, "Latency percentiles, /api", "timeseries", 12, 5, 12, 8,
            [
                target(f'histogram_quantile({q}, sum by (le) (rate(http_request_duration_seconds_bucket{{{SEL}}}[5m])))', f"p{int(q * 100)}", ref)
                for q, ref in ((0.5, "A"), (0.95, "B"), (0.99, "C"))
            ],
            fieldConfig={"defaults": {"unit": "s"}, "overrides": []},
        ),
        panel(
            7, "Availability burn rate by window", "timeseries", 0, 13, 24, 9,
            [target(burn("5m"), "5m", "A"), target(burn("1h"), "1h", "B"), target(burn("6h"), "6h", "C")],
            fieldConfig={"defaults": {"unit": "none", "custom": {"thresholdsStyle": {"mode": "line"}},
                                      "thresholds": thresholds(("transparent", None), ("orange", 6), ("red", 14.4))}, "overrides": []},
            description="Lines mark the 6x and 14.4x paging thresholds defined in prometheus/rules/slo-alerts.yml.",
        ),
    ]
    return {
        "uid": "release-tracker-slo",
        "title": "release-tracker: SLOs and golden signals",
        "tags": ["slo", "portfolio"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "10s",
        "time": {"from": "now-1h", "to": "now"},
        "panels": panels,
    }


def main() -> int:
    body = json.dumps(build(), indent=2) + "\n"
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != body:
            print("STALE dashboard JSON; run build_dashboard.py")
            return 1
        print("OK: dashboard JSON is up to date")
        return 0
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(body)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
