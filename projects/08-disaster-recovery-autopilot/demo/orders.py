#!/usr/bin/env python3
"""A small orders service on PostgreSQL: the thing the lab breaks and recovers.

    GET  /healthz        200 when the orders tables exist and answer; 503 with the reason otherwise
    GET  /orders/count   {"orders": N}
    POST /orders         {"sku": "...", "qty": 2, "price_cents": 500} -> 201 {"id": N}
    GET  /metrics        orders_data_healthy 1|0 (what the Prometheus alert reads)

A connection is opened per request, so the service notices a dropped table immediately and keeps working
after the database is restored underneath it: there is nothing to reload.

    DATABASE_URL=postgresql://... python demo/orders.py --init-schema     create the tables
    DATABASE_URL=postgresql://... PORT=8090 python demo/orders.py           serve
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg

SCHEMA = Path(__file__).with_name("schema.sql")
MAX_BODY = 4096


def init_schema(dsn: str) -> None:
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute(SCHEMA.read_text())


def health(dsn: str) -> tuple[bool, str, int]:
    """(healthy, reason, order count). Healthy means the tables are there and answer a query."""
    try:
        with psycopg.connect(dsn, connect_timeout=2) as conn:
            for table in ("orders", "order_items"):
                if conn.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[0] is None:
                    return False, f"table {table} is missing", 0
            return True, "ok", conn.execute("SELECT count(*) FROM orders").fetchone()[0]
    except psycopg.Error as err:
        return False, f"database unavailable ({err.__class__.__name__})", 0


def create_order(dsn: str, sku: str, qty: int, price_cents: int) -> int:
    with psycopg.connect(dsn, connect_timeout=5) as conn, conn.transaction():
        order_id = conn.execute("INSERT INTO orders (total_cents) VALUES (%s) RETURNING id", (qty * price_cents,)).fetchone()[0]
        conn.execute("INSERT INTO order_items (order_id, sku, qty, price_cents) VALUES (%s, %s, %s, %s)", (order_id, sku, qty, price_cents))
        return order_id


def create_server(host: str, port: int, dsn: str) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def reply(self, status: int, body: dict | str, content_type: str = "application/json") -> None:
            raw = (body if isinstance(body, str) else json.dumps(body)).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):  # noqa: N802
            if self.path == "/healthz":
                ok, reason, count = health(dsn)
                return self.reply(200, {"status": "ok", "orders": count}) if ok else self.reply(503, {"status": "unhealthy", "reason": reason})
            if self.path == "/orders/count":
                ok, reason, count = health(dsn)
                return self.reply(200, {"orders": count}) if ok else self.reply(503, {"error": reason})
            if self.path == "/metrics":
                ok, _, _ = health(dsn)
                text = (
                    "# HELP orders_data_healthy 1 if the orders tables exist and answer queries.\n"
                    "# TYPE orders_data_healthy gauge\n"
                    f"orders_data_healthy {1 if ok else 0}\n"
                )
                return self.reply(200, text, "text/plain; version=0.0.4")
            return self.reply(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path != "/orders":
                return self.reply(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if 0 < length <= MAX_BODY else None
                sku, qty, price = body["sku"], body["qty"], body["price_cents"]
                if not (isinstance(sku, str) and sku and isinstance(qty, int) and qty > 0 and isinstance(price, int) and price >= 0):
                    raise ValueError("bad field")
            except (ValueError, KeyError, TypeError):
                return self.reply(400, {"error": "need sku (string), qty (int > 0) and price_cents (int >= 0)"})
            try:
                return self.reply(201, {"id": create_order(dsn, sku, qty, price)})
            except psycopg.Error as err:
                return self.reply(503, {"error": f"database unavailable ({err.__class__.__name__})"})

    return ThreadingHTTPServer((host, port), Handler)


def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL must be set", file=sys.stderr)
        return 2
    if "--init-schema" in sys.argv:
        init_schema(dsn)
        print("schema ready")
        return 0
    httpd = create_server(os.environ.get("ORDERS_HOST", "127.0.0.1"), int(os.environ.get("PORT", "8090")), dsn)
    print(f"orders service on {httpd.server_address}")
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
