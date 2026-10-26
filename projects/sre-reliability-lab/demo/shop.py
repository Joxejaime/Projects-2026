"""Demo shop-api: a tiny service with Prometheus metrics and runtime fault injection.

LAB USE ONLY. It exists so the SLOs, alerts and chaos scenarios in this repository have
something real to measure. Fault injection is per route, so a broken /checkout can be shown
not to hurt /catalog.

  GET  /checkout  /catalog   simulated work (20-60 ms)
  GET  /healthz              liveness
  GET  /metrics              Prometheus exposition
  POST /admin/faults         {"route": "/checkout", "error_rate": 0.3, "extra_latency_ms": 400}
                             {"reset": true}   (requires SHOP_ADMIN_TOKEN; absent = route disabled)
"""

from __future__ import annotations

import hmac
import json
import os
import random
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROUTES = ("/checkout", "/catalog")
BUCKETS = (0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5)  # le="0.3" is the checkout-latency SLO threshold


class State:
    def __init__(self, admin_token: str = "", rng: random.Random | None = None, sleep=time.sleep):
        self.admin_token = admin_token
        self.rng = rng or random.Random()
        self.sleep = sleep
        self.lock = threading.Lock()
        self.requests: dict[tuple[str, str], int] = {}
        self.buckets = {r: [0] * (len(BUCKETS) + 1) for r in ROUTES}
        self.sums = dict.fromkeys(ROUTES, 0.0)
        self.faults = {r: {"error_rate": 0.0, "extra_latency_ms": 0.0} for r in ROUTES}

    def record(self, route: str, code: int, seconds: float) -> None:
        with self.lock:
            self.requests[(route, str(code))] = self.requests.get((route, str(code)), 0) + 1
            idx = next((i for i, b in enumerate(BUCKETS) if seconds <= b), len(BUCKETS))
            self.buckets[route][idx] += 1
            self.sums[route] += seconds

    def render(self) -> str:
        lines = ["# HELP http_requests_total HTTP responses by route and status code.", "# TYPE http_requests_total counter"]
        with self.lock:
            for (route, code), n in sorted(self.requests.items()):
                lines.append(f'http_requests_total{{route="{route}",code="{code}"}} {n}')
            lines += [
                "# HELP http_request_duration_seconds Request latency by route.",
                "# TYPE http_request_duration_seconds histogram",
            ]
            for route in ROUTES:
                cumulative = 0
                for bound, count in zip((*BUCKETS, float("inf")), self.buckets[route], strict=True):
                    cumulative += count
                    le = "+Inf" if bound == float("inf") else format(bound, "g")
                    lines.append(f'http_request_duration_seconds_bucket{{route="{route}",le="{le}"}} {cumulative}')
                lines.append(f'http_request_duration_seconds_sum{{route="{route}"}} {self.sums[route]:.6f}')
                lines.append(f'http_request_duration_seconds_count{{route="{route}"}} {cumulative}')
        return "\n".join(lines) + "\n"

    def handle_work(self, route: str) -> int:
        started = time.monotonic()
        with self.lock:
            fault = dict(self.faults[route])
        self.sleep(self.rng.uniform(0.02, 0.06) + fault["extra_latency_ms"] / 1000)
        code = 500 if self.rng.random() < fault["error_rate"] else 200
        self.record(route, code, time.monotonic() - started)
        return code


def make_handler(state: State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args) -> None:
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict) -> None:
            self._send(code, json.dumps(obj).encode())

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in ROUTES:
                code = state.handle_work(path)
                self._json(code, {"route": path, "status": "ok" if code == 200 else "error"})
            elif path == "/healthz":
                self._json(200, {"status": "ok"})
            elif path == "/metrics":
                self._send(200, state.render().encode(), "text/plain; version=0.0.4")
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(min(length, 4096))
            if self.path != "/admin/faults" or not state.admin_token:
                return self._json(404, {"error": "not found"})
            if not hmac.compare_digest(self.headers.get("X-Admin-Token", "").encode(), state.admin_token.encode()):
                return self._json(403, {"error": "forbidden"})
            try:
                body = json.loads(raw or b"{}")
                if body.get("reset"):
                    with state.lock:
                        for fault in state.faults.values():
                            fault.update(error_rate=0.0, extra_latency_ms=0.0)
                    return self._json(200, {"faults": state.faults})
                route = body["route"]
                if route not in ROUTES:
                    raise ValueError(f"route must be one of {ROUTES}")
                error_rate = float(body.get("error_rate", state.faults[route]["error_rate"]))
                latency = float(body.get("extra_latency_ms", state.faults[route]["extra_latency_ms"]))
                if not (0 <= error_rate <= 1 and 0 <= latency <= 30000):
                    raise ValueError("error_rate must be 0-1 and extra_latency_ms 0-30000")
            except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
                return self._json(400, {"error": str(exc)})
            with state.lock:
                state.faults[route].update(error_rate=error_rate, extra_latency_ms=latency)
            return self._json(200, {"faults": state.faults})

    return Handler


def create_server(host: str, port: int, admin_token: str = "", **state_kwargs) -> tuple[ThreadingHTTPServer, State]:
    state = State(admin_token, **state_kwargs)
    httpd = ThreadingHTTPServer((host, port), make_handler(state))
    httpd.daemon_threads = True
    return httpd, state


def main() -> None:
    httpd, _ = create_server(
        os.environ.get("SHOP_HOST", "0.0.0.0"),  # noqa: S104 - container workload
        int(os.environ.get("PORT", "8081")),
        os.environ.get("SHOP_ADMIN_TOKEN", ""),
    )
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=httpd.shutdown, daemon=True).start())
    httpd.serve_forever()


if __name__ == "__main__":
    main()
