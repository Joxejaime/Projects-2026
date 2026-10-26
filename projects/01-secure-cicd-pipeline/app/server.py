"""release-tracker: a small, dependency-free HTTP service used across this portfolio.

It records deployments (who shipped what, where) and exposes the operational
surface a real service needs: liveness/readiness probes, Prometheus metrics,
structured JSON logs and graceful shutdown.

It is intentionally stdlib-only: nothing to pin, nothing to patch, and a very
small attack surface for the container image. The same service is reused by the
Terraform (02), Kubernetes/GitOps (03) and observability (04) projects.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

VERSION = os.environ.get("APP_VERSION", "dev")
MAX_BODY_BYTES = 8 * 1024
MAX_RECORDS = 1000
ENVIRONMENTS = {"dev", "staging", "prod"}
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload, separators=(",", ":"))


log = logging.getLogger("release-tracker")
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())
log.addHandler(_handler)
log.setLevel(logging.INFO)
log.propagate = False


class Metrics:
    """Minimal Prometheus text-format registry (counter + histogram)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, str], int] = {}
        self._hist_buckets: dict[str, list[int]] = {}
        self._hist_sum: dict[str, float] = {}
        self._hist_count: dict[str, int] = {}
        self.deployments_recorded = 0
        self.started = time.time()

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        with self._lock:
            key = (method, route, str(status))
            self._requests[key] = self._requests.get(key, 0) + 1
            buckets = self._hist_buckets.setdefault(route, [0] * len(LATENCY_BUCKETS))
            for i, bound in enumerate(LATENCY_BUCKETS):
                if seconds <= bound:
                    buckets[i] += 1
            self._hist_sum[route] = self._hist_sum.get(route, 0.0) + seconds
            self._hist_count[route] = self._hist_count.get(route, 0) + 1

    def render(self) -> str:
        lines = [
            "# HELP http_requests_total Total HTTP requests by method, route and status.",
            "# TYPE http_requests_total counter",
        ]
        with self._lock:
            for (method, route, status), value in sorted(self._requests.items()):
                lines.append(
                    f'http_requests_total{{method="{method}",route="{route}",status="{status}"}} {value}'
                )
            lines += [
                "# HELP http_request_duration_seconds HTTP request latency by route.",
                "# TYPE http_request_duration_seconds histogram",
            ]
            for route in sorted(self._hist_buckets):
                for bound, value in zip(LATENCY_BUCKETS, self._hist_buckets[route], strict=True):
                    lines.append(
                        f'http_request_duration_seconds_bucket{{route="{route}",le="{bound}"}} {value}'
                    )
                lines.append(
                    f'http_request_duration_seconds_bucket{{route="{route}",le="+Inf"}} {self._hist_count[route]}'
                )
                lines.append(f'http_request_duration_seconds_sum{{route="{route}"}} {self._hist_sum[route]:.6f}')
                lines.append(f'http_request_duration_seconds_count{{route="{route}"}} {self._hist_count[route]}')
            lines += [
                "# HELP deployments_recorded_total Deployment records accepted.",
                "# TYPE deployments_recorded_total counter",
                f"deployments_recorded_total {self.deployments_recorded}",
                "# HELP app_info Build information.",
                "# TYPE app_info gauge",
                f'app_info{{version="{VERSION}"}} 1',
                "# HELP process_start_time_seconds Start time of the process since unix epoch.",
                "# TYPE process_start_time_seconds gauge",
                f"process_start_time_seconds {self.started:.0f}",
            ]
        return "\n".join(lines) + "\n"


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.deployments: list[dict] = []
        self.ready = True
        self.metrics = Metrics()
        # Fault injection for observability demos. Off unless explicitly enabled.
        self.chaos_enabled = os.environ.get("ENABLE_CHAOS", "false").lower() == "true"


def validate_deployment(data: object) -> tuple[dict | None, str | None]:
    if not isinstance(data, dict):
        return None, "body must be a JSON object"
    service = data.get("service")
    version = data.get("version")
    environment = data.get("environment")
    if not isinstance(service, str) or not 1 <= len(service) <= 64:
        return None, "service must be a string of 1-64 characters"
    if not isinstance(version, str) or not 1 <= len(version) <= 64:
        return None, "version must be a string of 1-64 characters"
    if environment not in ENVIRONMENTS:
        return None, f"environment must be one of {sorted(ENVIRONMENTS)}"
    return {"service": service, "version": version, "environment": environment}, None


def make_handler(state: State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "release-tracker"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: object) -> None:  # silence default access log
            return

        # --- helpers -------------------------------------------------
        def _send(self, status: int, body: bytes, content_type: str, route: str, started: float) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Request-Id", self._request_id)
            self.end_headers()
            self.wfile.write(body)
            elapsed = time.perf_counter() - started
            state.metrics.observe(self.command, route, status, elapsed)
            if route not in ("/healthz", "/readyz", "/metrics"):
                log.info(
                    "request",
                    extra={
                        "fields": {
                            "request_id": self._request_id,
                            "method": self.command,
                            "route": route,
                            "status": status,
                            "duration_ms": round(elapsed * 1000, 2),
                        }
                    },
                )

        def _json(self, status: int, payload: object, route: str, started: float) -> None:
            self._send(status, json.dumps(payload).encode(), "application/json", route, started)

        # --- routing -------------------------------------------------
        def _dispatch(self) -> None:
            started = time.perf_counter()
            self._request_id = self.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == "/healthz" and self.command == "GET":
                return self._json(200, {"status": "ok"}, "/healthz", started)
            if path == "/readyz" and self.command == "GET":
                if state.ready:
                    return self._json(200, {"status": "ready"}, "/readyz", started)
                return self._json(503, {"status": "shutting_down"}, "/readyz", started)
            if path == "/metrics" and self.command == "GET":
                return self._send(
                    200, state.metrics.render().encode(), "text/plain; version=0.0.4", "/metrics", started
                )
            if path == "/api/deployments" and self.command == "GET":
                with state.lock:
                    items = list(reversed(state.deployments))[:50]
                return self._json(200, {"items": items, "count": len(items)}, "/api/deployments", started)
            if path == "/api/deployments" and self.command == "POST":
                return self._create_deployment(started)
            if path == "/api/simulate" and self.command == "GET":
                return self._simulate(query, started)
            return self._json(404, {"error": "not found"}, "unmatched", started)

        def _create_deployment(self, started: float) -> None:
            route = "/api/deployments"
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self._json(400, {"error": "invalid Content-Length"}, route, started)
            if length <= 0 or length > MAX_BODY_BYTES:
                # The body is left unread, so the connection must not be reused (HTTP/1.1 keep-alive).
                self.close_connection = True
                status = 413 if length > MAX_BODY_BYTES else 400
                return self._json(status, {"error": "invalid body size"}, route, started)
            try:
                data = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._json(400, {"error": "body is not valid JSON"}, route, started)
            record, error = validate_deployment(data)
            if error or record is None:
                return self._json(422, {"error": error}, route, started)
            record["id"] = uuid.uuid4().hex[:12]
            record["recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            with state.lock:
                state.deployments.append(record)
                del state.deployments[:-MAX_RECORDS]
                state.metrics.deployments_recorded += 1
            return self._json(201, record, route, started)

        def _simulate(self, query: dict[str, list[str]], started: float) -> None:
            """Fault injection (ENABLE_CHAOS=true): ?status=500&delay_ms=250."""
            route = "/api/simulate"
            if not state.chaos_enabled:
                return self._json(404, {"error": "not found"}, "unmatched", started)
            try:
                status = int(query.get("status", ["200"])[0])
                delay_ms = min(int(query.get("delay_ms", ["0"])[0]), 5000)
            except ValueError:
                return self._json(400, {"error": "status and delay_ms must be integers"}, route, started)
            if status not in (200, 400, 500, 502, 503):
                return self._json(400, {"error": "unsupported status"}, route, started)
            if delay_ms > 0:
                time.sleep(delay_ms / 1000)
            return self._json(status, {"simulated": True, "status": status}, route, started)

        def do_GET(self) -> None:
            self._dispatch()

        def do_POST(self) -> None:
            self._dispatch()

        def do_PUT(self) -> None:
            self._dispatch()

        def do_DELETE(self) -> None:
            self._dispatch()

    return Handler


def build_server(host: str, port: int, state: State | None = None) -> tuple[ThreadingHTTPServer, State]:
    state = state or State()
    server = ThreadingHTTPServer((host, port), make_handler(state))
    server.daemon_threads = True
    return server, state


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")  # noqa: S104 - container workload, bound by the platform
    port = int(os.environ.get("PORT", "8080"))
    server, state = build_server(host, port)

    def shutdown(signum: int, _frame: object) -> None:
        log.info("shutdown signal received", extra={"fields": {"signal": signum}})
        state.ready = False  # fail readiness first so load balancers drain us
        grace = float(os.environ.get("SHUTDOWN_GRACE_SECONDS", "5"))
        threading.Timer(grace, server.shutdown).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    log.info("listening", extra={"fields": {"host": host, "port": port, "version": VERSION}})
    server.serve_forever()
    log.info("stopped")


if __name__ == "__main__":
    main()
