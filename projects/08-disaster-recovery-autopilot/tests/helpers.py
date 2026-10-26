"""Shared test helpers: a controllable clock, Alertmanager-shaped payloads, tiny playbooks."""

import json
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

T0 = datetime(2026, 10, 26, 10, 0, tzinfo=UTC)


class Clock:
    def __init__(self, start=T0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def payload(status, alertname="DiskFull", fingerprint="fp1", starts=T0, ends=None, **labels):
    labels = {"alertname": alertname, "service": "api", "severity": "page", **labels}
    return {
        "version": "4",
        "status": status,
        "alerts": [
            {
                "status": status,
                "labels": labels,
                "annotations": {"summary": f"{alertname} on api"},
                "startsAt": starts.isoformat().replace("+00:00", "Z"),
                "endsAt": ends.isoformat().replace("+00:00", "Z") if ends else "0001-01-01T00:00:00Z",
                "fingerprint": fingerprint,
            }
        ],
    }


def write_playbook(directory, name, text):
    path = Path(directory) / f"{name}.yaml"
    path.write_text(text)
    return path


OK_BOOK = """
name: disk-cleanup
match: {alertname: DiskFull}
max_attempts: 2
objectives: {rto_seconds: 300}
steps:
  - name: Clean temp
    run: ["{python}", "-c", "import json; print('cleaned'); print(json.dumps({'facts': {'freed_mb': 512}}))"]
"""

FAIL_BOOK = """
name: always-fails
match: {alertname: DiskFull}
max_attempts: 2
steps:
  - name: Broken step
    run: ["{python}", "-c", "import sys; sys.exit(3)"]
"""


def post_order(base, qty=1, price=500, sku="widget"):
    body = json.dumps({"sku": sku, "qty": qty, "price_cents": price}).encode()
    req = urllib.request.Request(base + "/orders", data=body, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())["id"]
