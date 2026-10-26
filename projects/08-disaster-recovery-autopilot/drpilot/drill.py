"""Disaster-recovery drills: break a real database on purpose and check the whole loop end to end.

Each drill starts a throwaway PostgreSQL server, the demo orders service and a responder, takes verified
snapshots, causes a disaster, and lets drpilot detect, recover, verify and write the postmortem.

    dropped-table     someone drops the orders tables. Recovery must restore the newest snapshot, pass the data
                      checks, meet RTO/RPO, and the draft must say how many writes were lost.
    poisoned-backup   a backup job without validation snapshotted data that was already wrong (order totals no
                      longer match their items). Restoring it would "work" and be wrong: recovery must skip it,
                      fall back to the older good snapshot, and the draft must name the skipped snapshot.
    corrupt-backups   the only snapshot has rotted. Recovery must refuse to restore it, give up and escalate, the
                      drill then plays the paged human who rebuilds by hand, and the draft must record the failure.

Detection here is a 20-line probe loop that posts Alertmanager-shaped alerts to the responder. It stands in for
Prometheus + Alertmanager (project 04), which do this job in a real deployment; it is not a product feature.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psycopg

from recovery import snapshots
from recovery.store import LocalStore

from . import playbooks as pb
from .engine import Responder, synthetic_alert
from .model import IncidentStore, utcnow
from .pgcluster import temporary_cluster
from .render import data_loss_window, objective_checks, suggested_actions

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "demo"))
import orders  # noqa: E402

SCENARIOS = ("dropped-table", "poisoned-backup", "corrupt-backups")
ENV_KEYS = ("DATABASE_URL", "BACKUP_STORE", "ORDERS_URL")
KEPT_ORDERS, LOST_ORDERS = 5, 2


@dataclass
class DrillResult:
    passed: bool
    incident_id: str
    postmortem: Path
    summary: list[str]


class ProbeAlerter:
    """Fires after N consecutive failed probes (dated from the first failure), resolves after M healthy ones."""

    def __init__(self, url: str, sink: Callable[[dict], object], labels: dict, annotations: dict, interval: float, failures: int = 3, successes: int = 2):
        self.url, self.sink, self.labels, self.annotations = url, sink, labels, annotations
        self.interval, self.failures, self.successes = interval, failures, successes
        self.firing, self.bad, self.good = False, 0, 0
        self.first_bad: datetime | None = None
        self.first_good: datetime | None = None
        self.fired_at: datetime | None = None
        self.stopped = threading.Event()

    def healthy(self) -> bool:
        try:
            with urllib.request.urlopen(self.url, timeout=2) as resp:  # noqa: S310  (local drill service)
                return resp.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def tick(self) -> None:
        now = utcnow()
        if self.healthy():
            self.bad, self.first_bad = 0, None
            if self.firing:
                self.good, self.first_good = self.good + 1, self.first_good or now
                if self.good >= self.successes:
                    self.sink(synthetic_alert("OrdersDataUnhealthy", "resolved", self.labels, self.annotations, self.fired_at, self.first_good))
                    self.firing, self.good, self.first_good = False, 0, None
        else:
            self.good, self.first_good = 0, None
            if not self.firing:
                self.bad, self.first_bad = self.bad + 1, self.first_bad or now
                if self.bad >= self.failures:
                    self.fired_at, self.firing, self.bad = self.first_bad, True, 0
                    self.sink(synthetic_alert("OrdersDataUnhealthy", "firing", self.labels, self.annotations, self.fired_at))

    def run(self) -> None:
        while not self.stopped.is_set():
            self.tick()
            self.stopped.wait(self.interval)


def _post_order(base: str, qty: int, price: int = 500, sku: str = "widget") -> None:
    body = json.dumps({"sku": sku, "qty": qty, "price_cents": price}).encode()
    req = urllib.request.Request(base + "/orders", data=body, method="POST", headers={"Content-Type": "application/json"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=5):  # noqa: S310
        pass


def _totals(url: str) -> list[int]:
    with psycopg.connect(url, connect_timeout=5) as conn:
        return [row[0] for row in conn.execute("SELECT total_cents FROM orders ORDER BY id")]


def run_drill(out_dir: Path, scenario: str = "dropped-table", timeout: float = 90.0, interval: float = 0.2) -> DrillResult:
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}")
    work = Path(tempfile.mkdtemp(prefix="drpilot-drill-"))
    env_before = {k: os.environ.get(k) for k in ENV_KEYS}
    alerter = httpd = None
    try:
        with temporary_cluster() as cluster:
            url = cluster.create_database("orders")
            orders.init_schema(url)
            httpd = orders.create_server("127.0.0.1", 0, url)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            store = LocalStore(work / "backups")
            os.environ.update(DATABASE_URL=url, BACKUP_STORE=str(store), ORDERS_URL=base)

            for qty in range(1, KEPT_ORDERS + 1):
                _post_order(base, qty)
            good_totals = _totals(url)
            snapshots.take(url, store, log=lambda _m: None)
            if scenario == "poisoned-backup":
                time.sleep(1.1)  # snapshot names have one-second resolution
                with psycopg.connect(url, autocommit=True) as conn:  # the silent bug: totals drift away from their items
                    conn.execute("UPDATE orders SET total_cents = total_cents + 500 WHERE id <= 2")
                snapshots.take(url, store, verify=False, log=lambda _m: None)
            if scenario == "corrupt-backups":
                for dump in (work / "backups").glob("*.dump"):
                    dump.write_bytes(b"bit rot")
            for qty in range(LOST_ORDERS):
                _post_order(base, qty + 1, sku="after-snapshot")

            responder = Responder(IncidentStore(work / "incidents"), pb.load_dir(PROJECT / "playbooks"), out_dir)
            incidents: list[str] = []
            alerter = ProbeAlerter(
                base + "/healthz",
                lambda payload: incidents.extend(responder.handle_payload(payload)),
                labels={"service": "orders", "severity": "page", "autoremediate": "true", "environment": "drill"},
                annotations={
                    "summary": f"Orders data unhealthy (drill: {scenario})",
                    "description": "Disaster-recovery drill: the orders tables were deliberately destroyed.",
                    "runbook": "docs/runbooks/orders-data-unhealthy.md",
                },
                interval=interval,
            )
            threading.Thread(target=alerter.run, daemon=True).start()
            time.sleep(interval * 3)  # healthy baseline first
            with psycopg.connect(url, autocommit=True) as conn:  # the disaster
                conn.execute("DROP TABLE order_items, orders")

            deadline = time.monotonic() + timeout
            while not incidents and time.monotonic() < deadline:
                time.sleep(interval)
            if not incidents:
                raise RuntimeError("the probe never fired; detection is broken")
            if scenario == "corrupt-backups":
                while responder.store.get(incidents[0]).recovery_state == "running" and time.monotonic() < deadline:
                    time.sleep(interval)
                orders.init_schema(url)  # the paged human rebuilds what they can
                _post_order(base, 1, sku="rebuilt-by-hand")
            incident = responder.wait_closed(incidents[0], timeout=max(1.0, deadline - time.monotonic()))
            restored = _totals(url)
    finally:
        if alerter:
            alerter.stopped.set()
        if httpd:
            httpd.shutdown()
            httpd.server_close()
        for key, value in env_before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(work, ignore_errors=True)

    checks = objective_checks(incident)
    lost = data_loss_window(incident)
    skipped = int(incident.facts.get("snapshots_skipped", 0) or 0)
    if scenario == "dropped-table":
        passed = incident.recovery_state == "succeeded" and restored == good_totals and skipped == 0 and all(c[3] == "met" for c in checks)
        data_line = f"data: {len(restored)} orders restored and intact; {LOST_ORDERS} written after the snapshot were lost (expected: RPO > 0)"
    elif scenario == "poisoned-backup":
        passed = incident.recovery_state == "succeeded" and restored == good_totals and skipped == 1 and all(c[3] == "met" for c in checks)
        data_line = f"data: newest snapshot skipped (order totals did not match items), older one restored: {len(restored)} orders, totals intact"
    else:
        followup = any(a.startswith(f"Automation '{incident.playbook}' failed") for a, _ in suggested_actions(incident))
        passed = incident.recovery_state == "failed" and restored == [500] and followup
        data_line = f"data: automation refused to restore a rotted snapshot and escalated; {KEPT_ORDERS + LOST_ORDERS} orders lost, rebuilt by hand"
    passed = passed and incident.finalized
    summary = [
        f"scenario {scenario}: incident {incident.id}, recovery {incident.recovery_state}, postmortem {incident.postmortem_path}",
        data_line,
        *(f"{name}: target {target}, observed {observed} -> {verdict}" for name, target, observed, verdict in checks),
        *([f"data loss window: {lost:.1f}s of writes"] if lost is not None else []),
        "DRILL PASSED" if passed else "DRILL FAILED",
    ]
    return DrillResult(passed, incident.id, Path(incident.postmortem_path or ""), summary)
