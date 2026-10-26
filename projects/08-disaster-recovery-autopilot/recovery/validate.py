"""Recovery validation: is the data actually right, not merely reachable?

A restore that exits 0 and a service that answers /healthz prove very little. These checks look at the data:

    schema       the expected tables exist
    row counts   equal what the snapshot's manifest recorded (catches truncated or tampered restores)
    orphans      no order item points at a missing order
    totals       every order's total equals the sum of its items (a business invariant no health check sees)
    write path   (optional) the service accepts a new order after recovery, and the row really lands

Used three ways: on the live database before taking a snapshot (never snapshot data that is already
wrong), on a scratch database before trusting a snapshot, and on the live database after a restore.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

import psycopg

from .pg import RecoveryError, connect

TABLES = ("orders", "order_items")
SMOKE_SKU = "__recovery-smoke__"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def table_counts(conn: psycopg.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}  # noqa: S608  (fixed table names)


def validate(url: str, manifest: dict | None = None, smoke_url: str | None = None) -> tuple[list[Check], dict]:
    """Run every check against the database at `url`. Returns the checks and the facts they measured."""
    checks: list[Check] = []
    facts: dict = {}
    try:
        conn = connect(url)
    except RecoveryError as err:
        return [Check("connect", False, str(err))], facts
    with conn:
        checks.append(Check("connect", True, "database reachable"))
        missing = [t for t in TABLES if conn.execute("SELECT to_regclass(%s)", (f"public.{t}",)).fetchone()[0] is None]
        if missing:
            checks.append(Check("schema", False, f"missing tables: {', '.join(missing)}"))
            return checks, facts
        checks.append(Check("schema", True, f"tables present: {', '.join(TABLES)}"))

        counts = table_counts(conn)
        facts |= {f"rows_{t}": n for t, n in counts.items()}
        if manifest is None:
            checks.append(Check("row counts", True, ", ".join(f"{t}={n}" for t, n in counts.items()) + " (no manifest to compare)"))
        else:
            expected = manifest.get("tables", {})
            wrong = {t: (counts[t], expected.get(t)) for t in TABLES if counts[t] != expected.get(t)}
            if wrong:
                detail = "differ from manifest: " + ", ".join(f"{t} has {got}, manifest says {want}" for t, (got, want) in wrong.items())
            else:
                detail = "match manifest: " + ", ".join(f"{t}={n}" for t, n in counts.items())
            checks.append(Check("row counts", not wrong, detail))

        orphans = conn.execute("SELECT count(*) FROM order_items i LEFT JOIN orders o ON o.id = i.order_id WHERE o.id IS NULL").fetchone()[0]
        checks.append(Check("orphans", orphans == 0, "no order item without an order" if orphans == 0 else f"{orphans} order item(s) point at a missing order"))

        bad_totals = conn.execute(
            "SELECT count(*) FROM orders o WHERE o.total_cents <> COALESCE((SELECT sum(i.qty * i.price_cents) FROM order_items i WHERE i.order_id = o.id), 0)"
        ).fetchone()[0]
        if bad_totals:
            checks.append(Check("totals", False, f"{bad_totals} order(s) whose total differs from their items"))
        else:
            checks.append(Check("totals", True, "every order total equals the sum of its items"))

    if smoke_url:
        checks.append(_smoke(url, smoke_url))
    return checks, facts


def _smoke(url: str, service_url: str) -> Check:
    """Write through the service's own API, confirm the row is in the database, then remove it."""
    if not service_url.startswith(("http://", "https://")):
        return Check("write path", False, f"refusing non-HTTP url {service_url!r}")
    body = json.dumps({"sku": SMOKE_SKU, "qty": 1, "price_cents": 1}).encode()
    req = urllib.request.Request(service_url.rstrip("/") + "/orders", data=body, method="POST", headers={"Content-Type": "application/json"})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            status, created = resp.status, json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError) as err:
        return Check("write path", False, f"POST /orders failed: {err}")
    if status != 201 or "id" not in created:
        return Check("write path", False, f"POST /orders answered {status}")
    with connect(url) as conn:
        found = conn.execute("SELECT count(*) FROM order_items WHERE order_id = %s AND sku = %s", (created["id"], SMOKE_SKU)).fetchone()[0]
        conn.execute("DELETE FROM order_items WHERE order_id = %s", (created["id"],))
        conn.execute("DELETE FROM orders WHERE id = %s", (created["id"],))
    if found != 1:
        return Check("write path", False, f"service said it stored order {created['id']} but the database has no such row")
    return Check("write path", True, f"order {created['id']} written through the service, found in the database, removed")


def format_checks(checks: list[Check]) -> str:
    return "\n".join(f"{'PASS' if c.ok else 'FAIL'}  {c.name}: {c.detail}" for c in checks)
