"""HTTP front end (standard library only).

Routes
  POST /v1/chat        chat completion through the resilient gateway
  GET  /healthz        liveness  - process is up
  GET  /readyz         readiness - at least one provider can take traffic and we are not draining
  GET  /metrics        Prometheus exposition
  GET  /admin/state    (lab only) fault + circuit state
  POST /admin/faults   (lab only) inject provider errors / latency at runtime

Admin routes do not exist unless GATEWAY_ADMIN_TOKEN is set, and then require the
``X-Admin-Token`` header. Never set it on an internet-facing deployment.
"""

from __future__ import annotations

import hmac
import json
import logging
import re
import signal
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from .cache import TTLCache
from .config import Config
from .limits import BudgetTracker, TenantRateLimiter, TokenBucket
from .logging_setup import configure
from .metrics import GatewayMetrics
from .providers import FaultConfig, MockProvider
from .resilience import CircuitBreaker, CircuitState
from .router import Gateway, GatewayError, ProviderSlot

log = logging.getLogger("gateway.http")

TENANT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MAX_BODY_BYTES = 64 * 1024
MAX_PROMPT_CHARS = 8000
KNOWN_ROUTES = {"/v1/chat", "/healthz", "/readyz", "/metrics", "/admin/faults", "/admin/state"}


@dataclass
class App:
    config: Config
    gateway: Gateway
    metrics: GatewayMetrics
    faults: dict[str, FaultConfig]
    draining: threading.Event = field(default_factory=threading.Event)
    keys: dict[str, str] = field(default_factory=dict)  # api key -> tenant; empty = unauthenticated lab mode
    global_bucket: TokenBucket | None = None
    global_lock: threading.Lock = field(default_factory=threading.Lock)

    def global_allow(self) -> bool:
        if self.global_bucket is None:
            return True
        with self.global_lock:
            return self.global_bucket.allow()

    def tenant_for_key(self, supplied: str) -> str | None:
        """Constant-time lookup: compare against every key so timing does not reveal which one matched."""
        found = None
        for key, tenant in self.keys.items():
            if hmac.compare_digest(supplied.encode(), key.encode()):
                found = tenant
        return found


def parse_api_keys(raw: str) -> dict[str, str]:
    keys: dict[str, str] = {}
    for entry in filter(None, (part.strip() for part in raw.split(","))):
        key, sep, tenant = entry.partition(":")
        if not sep or len(key) < 16 or not TENANT_RE.match(tenant):
            raise ValueError("GATEWAY_API_KEYS entries must look like '<key of 16+ chars>:<tenant>'")
        keys[key] = tenant
    return keys


def build_app(config: Config, *, sleep=time.sleep, rng=None) -> App:
    metrics = GatewayMetrics()
    faults = {"primary": FaultConfig(), "fallback": FaultConfig()}

    def on_state_change(provider: str, old: CircuitState, new: CircuitState) -> None:
        metrics.circuit_state.set(int(new), provider=provider)
        metrics.circuit_transitions.inc(provider=provider, to=new.name.lower())
        log.warning(
            "circuit breaker state change",
            extra={"provider": provider, "from_state": old.name, "to_state": new.name},
        )

    slots = []
    for name, latency in (("primary", config.primary_latency), ("fallback", config.fallback_latency)):
        provider = MockProvider(
            name, base_latency=latency, jitter=latency * 0.3, faults=faults[name], sleep=sleep, rng=rng
        )
        breaker = CircuitBreaker(
            name,
            failure_threshold=config.breaker_failure_threshold,
            recovery_timeout=config.breaker_recovery_timeout,
            on_state_change=on_state_change,
        )
        metrics.circuit_state.set(0, provider=name)
        slots.append(ProviderSlot(provider, breaker))

    gateway = Gateway(
        slots,
        TTLCache(config.cache_max_entries, config.cache_ttl),
        TenantRateLimiter(config.rate_limit_rps, config.rate_limit_burst),
        BudgetTracker(config.tenant_token_budget, config.budget_window_seconds),
        metrics,
        request_timeout=config.request_timeout,
        attempt_timeout=config.attempt_timeout,
        max_attempts=config.max_attempts,
        retry_base=config.retry_base,
        retry_cap=config.retry_cap,
        sleep=sleep,
        rng=rng,
    )
    bucket = None
    if config.global_rate_limit_rps > 0:
        bucket = TokenBucket(config.global_rate_limit_rps, config.global_rate_limit_burst, time.monotonic)
    return App(config, gateway, metrics, faults, keys=parse_api_keys(config.api_keys), global_bucket=bucket)


class BadRequest(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "bad_request"):
        super().__init__(message)
        self.status, self.code = status, code


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = f"ai-gateway/{__version__}"
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args) -> None:  # we emit structured logs instead
            pass

        # -- plumbing ------------------------------------------------------------
        def do_GET(self) -> None:  # noqa: N802
            self._handle("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._handle("POST")

        def _handle(self, method: str) -> None:
            started = time.monotonic()
            route = self.path.split("?", 1)[0]
            self.request_id = (self.headers.get("X-Request-Id") or uuid.uuid4().hex[:16])[:64]
            self.log_fields: dict = {}
            try:
                status = self._dispatch(method, route)
            except BadRequest as exc:
                status = self._json(exc.status, {"error": exc.code, "message": str(exc)})
            except Exception:  # noqa: BLE001
                log.exception("unhandled error", extra={"request_id": self.request_id})
                status = self._json(500, {"error": "internal_error", "message": "unexpected error"})
            app.metrics.http_requests.inc(route=route if route in KNOWN_ROUTES else "other", code=str(status))
            log.info(
                "request",
                extra={
                    "request_id": self.request_id,
                    "method": method,
                    "route": route if route in KNOWN_ROUTES else "other",
                    "status": status,
                    "duration_ms": round((time.monotonic() - started) * 1000, 1),
                    **self.log_fields,
                },
            )

        def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> int:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Request-Id", self.request_id)
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return status

        def _json(self, status: int, payload: dict, extra: dict | None = None) -> int:
            payload = {**payload, "request_id": self.request_id}
            return self._send(status, json.dumps(payload).encode(), "application/json", extra)

        def _read_json(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise BadRequest("invalid Content-Length") from None
            if length < 0:
                # int() accepts "-1"; rfile.read(-1) would then block until the client closes the connection.
                self.close_connection = True
                raise BadRequest("invalid Content-Length")
            if length > MAX_BODY_BYTES:
                self.close_connection = True
                raise BadRequest("request body too large", 413, "payload_too_large")
            raw = self.rfile.read(length) if length else b""
            try:
                data = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                raise BadRequest("body must be valid JSON") from None
            if not isinstance(data, dict):
                raise BadRequest("body must be a JSON object")
            return data

        def _require_admin(self) -> None:
            token = app.config.admin_token
            if not token:
                raise BadRequest("not found", 404, "not_found")
            supplied = self.headers.get("X-Admin-Token", "")
            if not hmac.compare_digest(supplied.encode(), token.encode()):
                raise BadRequest("invalid admin token", 403, "forbidden")

        # -- routing -------------------------------------------------------------
        def _dispatch(self, method: str, route: str) -> int:
            if route == "/healthz" and method == "GET":
                return self._json(200, {"status": "ok", "version": __version__})
            if route == "/readyz" and method == "GET":
                ready = app.gateway.ready() and not app.draining.is_set()
                return self._json(200 if ready else 503, {"status": "ready" if ready else "not_ready"})
            if route == "/metrics" and method == "GET":
                return self._send(200, app.metrics.registry.render().encode(), "text/plain; version=0.0.4")
            if route == "/v1/chat" and method == "POST":
                return self._chat()
            if route == "/admin/state" and method == "GET":
                self._require_admin()
                return self._json(200, self._state())
            if route == "/admin/faults" and method == "POST":
                self._require_admin()
                return self._set_faults()
            if route in KNOWN_ROUTES:
                return self._json(405, {"error": "method_not_allowed", "message": f"{method} not allowed"})
            return self._json(404, {"error": "not_found", "message": "unknown route"})

        def _chat(self) -> int:
            if app.keys:
                supplied = self.headers.get("Authorization", "")
                tenant = app.tenant_for_key(supplied[7:]) if supplied.startswith("Bearer ") else None
                if tenant is None:
                    self.close_connection = True  # the body is left unread; do not reuse the connection
                    raise BadRequest("missing or invalid API key", 401, "unauthorized")
            else:
                tenant = self.headers.get("X-Tenant", "anonymous")
                if not TENANT_RE.match(tenant):
                    raise BadRequest("X-Tenant must match [A-Za-z0-9_.-]{1,64}")
            if not app.global_allow():
                self.close_connection = True
                self.log_fields["outcome"] = "rate_limited"
                message = "gateway is over its global request rate"
                return self._json(429, {"error": "rate_limited", "message": message}, {"Retry-After": "1"})
            body = self._read_json()
            prompt = body.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                raise BadRequest("'prompt' must be a non-empty string")
            if len(prompt) > MAX_PROMPT_CHARS:
                raise BadRequest(f"'prompt' exceeds {MAX_PROMPT_CHARS} characters", 413, "payload_too_large")
            max_tokens = body.get("max_tokens", 64)
            if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 512:
                raise BadRequest("'max_tokens' must be an integer between 1 and 512")
            self.log_fields["tenant"] = tenant
            try:
                result = app.gateway.chat(tenant, prompt, max_tokens)
            except GatewayError as exc:
                self.log_fields["outcome"] = exc.outcome
                headers = {"Retry-After": "1"} if exc.status in (429, 503) else None
                return self._json(exc.status, {"error": exc.code, "message": str(exc)}, headers)
            self.log_fields.update(outcome=result.outcome, provider=result.provider)
            return self._json(
                200,
                {
                    "text": result.text,
                    "provider": result.provider,
                    "outcome": result.outcome,
                    "attempts": result.attempts,
                    "usage": {"tokens_in": result.tokens_in, "tokens_out": result.tokens_out},
                },
            )

        def _state(self) -> dict:
            return {
                "faults": {name: cfg.snapshot() for name, cfg in app.faults.items()},
                "circuits": {slot.provider.name: slot.breaker.state.name.lower() for slot in app.gateway.slots},
            }

        def _set_faults(self) -> int:
            body = self._read_json()
            if body.get("reset") is True:
                for cfg in app.faults.values():
                    cfg.reset()
                return self._json(200, self._state())
            provider = body.get("provider")
            if provider not in app.faults:
                raise BadRequest(f"'provider' must be one of {sorted(app.faults)}")
            error_rate = body.get("error_rate")
            latency_ms = body.get("extra_latency_ms")
            for label, value, upper in (("error_rate", error_rate, 1.0), ("extra_latency_ms", latency_ms, 60000.0)):
                if value is not None and (
                    isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= upper
                ):
                    raise BadRequest(f"'{label}' must be a number between 0 and {upper:g}")
            app.faults[provider].update(
                error_rate=None if error_rate is None else float(error_rate),
                extra_latency=None if latency_ms is None else float(latency_ms) / 1000.0,
            )
            log.warning(
                "fault injected", extra={"provider": provider, "error_rate": error_rate, "extra_latency_ms": latency_ms}
            )
            return self._json(200, self._state())

    return Handler


def create_server(config: Config, **app_kwargs) -> tuple[ThreadingHTTPServer, App]:
    app = build_app(config, **app_kwargs)
    httpd = ThreadingHTTPServer((config.host, config.port), make_handler(app))
    httpd.daemon_threads = True
    return httpd, app


def main() -> None:
    config = Config.from_env()
    configure(config.log_level)
    httpd, app = create_server(config)

    def shutdown(signum, _frame) -> None:
        log.info("shutdown requested", extra={"signal": signum, "grace_seconds": config.shutdown_grace})

        def drain_then_stop() -> None:
            app.draining.set()  # /readyz -> 503 so the load balancer stops sending traffic
            time.sleep(config.shutdown_grace)
            httpd.shutdown()

        threading.Thread(target=drain_then_stop, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    log.info("gateway listening", extra={"host": config.host, "port": httpd.server_address[1], "version": __version__})
    httpd.serve_forever()
    httpd.server_close()
    log.info("gateway stopped")


if __name__ == "__main__":
    main()
