"""Minimal, dependency-free Prometheus metrics (text exposition format 0.0.4).

Implemented by hand on purpose: the gateway has zero runtime dependencies, which keeps
the container image small and the supply-chain surface tiny. For a larger service you
would use ``prometheus_client``; the exposition format is identical.
"""

from __future__ import annotations

import threading
from bisect import bisect_left

DEFAULT_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def _escape(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(names: tuple[str, ...], values: tuple[str, ...], extra: tuple = ()) -> str:
    pairs = list(zip(names, values, strict=True)) + list(extra)
    if not pairs:
        return ""
    return "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in pairs) + "}"


def _number(value: float) -> str:
    if value == float("inf"):
        return "+Inf"
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


class _Metric:
    kind = "untyped"

    def __init__(self, name: str, documentation: str, labelnames: tuple[str, ...] = ()):
        self.name = name
        self.documentation = documentation
        self.labelnames = tuple(labelnames)
        self._lock = threading.Lock()

    def _key(self, labels: dict) -> tuple[str, ...]:
        if set(labels) != set(self.labelnames):
            raise ValueError(f"{self.name}: expected labels {self.labelnames}, got {tuple(labels)}")
        return tuple(str(labels[n]) for n in self.labelnames)

    def _header(self) -> list[str]:
        return [f"# HELP {self.name} {self.documentation}", f"# TYPE {self.name} {self.kind}"]


class Counter(_Metric):
    kind = "counter"

    def __init__(self, name, documentation, labelnames=()):
        super().__init__(name, documentation, labelnames)
        self._values: dict[tuple[str, ...], float] = {}
        if not self.labelnames:
            self._values[()] = 0.0

    def inc(self, amount: float = 1.0, **labels) -> None:
        if amount < 0:
            raise ValueError("counters can only increase")
        key = self._key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def value(self, **labels) -> float:
        with self._lock:
            return self._values.get(self._key(labels), 0.0)

    def render(self) -> list[str]:
        with self._lock:
            items = sorted(self._values.items())
        lines = self._header()
        for key, val in items:
            lines.append(f"{self.name}{_labels(self.labelnames, key)} {_number(val)}")
        return lines


class Gauge(_Metric):
    kind = "gauge"

    def __init__(self, name, documentation, labelnames=()):
        super().__init__(name, documentation, labelnames)
        self._values: dict[tuple[str, ...], float] = {}
        if not self.labelnames:
            self._values[()] = 0.0

    def set(self, value: float, **labels) -> None:
        key = self._key(labels)
        with self._lock:
            self._values[key] = float(value)

    def inc(self, amount: float = 1.0, **labels) -> None:
        key = self._key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, **labels) -> None:
        self.inc(-amount, **labels)

    def value(self, **labels) -> float:
        with self._lock:
            return self._values.get(self._key(labels), 0.0)

    def render(self) -> list[str]:
        with self._lock:
            items = sorted(self._values.items())
        lines = self._header()
        for key, val in items:
            lines.append(f"{self.name}{_labels(self.labelnames, key)} {_number(val)}")
        return lines


class Histogram(_Metric):
    kind = "histogram"

    def __init__(self, name, documentation, labelnames=(), buckets=DEFAULT_BUCKETS):
        super().__init__(name, documentation, labelnames)
        self.buckets = tuple(sorted(buckets))
        # per label set: [non-cumulative bucket counts (+Inf last), sum]
        self._data: dict[tuple[str, ...], list] = {}

    def observe(self, value: float, **labels) -> None:
        key = self._key(labels)
        idx = bisect_left(self.buckets, value)
        with self._lock:
            entry = self._data.setdefault(key, [[0] * (len(self.buckets) + 1), 0.0])
            entry[0][idx] += 1
            entry[1] += value

    def count(self, **labels) -> int:
        with self._lock:
            entry = self._data.get(self._key(labels))
            return sum(entry[0]) if entry else 0

    def render(self) -> list[str]:
        with self._lock:
            items = sorted((k, (list(v[0]), v[1])) for k, v in self._data.items())
        lines = self._header()
        for key, (counts, total) in items:
            cumulative = 0
            for bound, c in zip(self.buckets + (float("inf"),), counts, strict=True):
                cumulative += c
                lbl = _labels(self.labelnames, key, (("le", _number(bound)),))
                lines.append(f"{self.name}_bucket{lbl} {cumulative}")
            lines.append(f"{self.name}_sum{_labels(self.labelnames, key)} {_number(total)}")
            lines.append(f"{self.name}_count{_labels(self.labelnames, key)} {cumulative}")
        return lines


class Registry:
    def __init__(self) -> None:
        self._metrics: list[_Metric] = []

    def register(self, metric):
        self._metrics.append(metric)
        return metric

    def render(self) -> str:
        lines: list[str] = []
        for metric in self._metrics:
            lines.extend(metric.render())
        return "\n".join(lines) + "\n"


class GatewayMetrics:
    """All metrics emitted by the gateway, defined in one place so dashboards and
    alert rules (observability/) have a single contract to follow."""

    def __init__(self, registry: Registry | None = None) -> None:
        self.registry = registry or Registry()
        r = self.registry.register
        self.requests = r(
            Counter(
                "gateway_requests_total",
                "Chat requests by final outcome (ok, cached, degraded, rate_limited, budget_exceeded, failed).",
                ("outcome",),
            )
        )
        self.request_duration = r(
            Histogram(
                "gateway_request_duration_seconds",
                "End-to-end chat request latency.",
                ("outcome",),
                buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
            )
        )
        self.provider_calls = r(
            Counter(
                "gateway_provider_calls_total",
                "Upstream provider attempts by result.",
                ("provider", "result"),
            )
        )
        self.provider_latency = r(
            Histogram(
                "gateway_provider_latency_seconds",
                "Latency of individual upstream provider attempts.",
                ("provider",),
                buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0),
            )
        )
        self.circuit_state = r(
            Gauge(
                "gateway_circuit_state",
                "Circuit breaker state per provider (0=closed, 1=half_open, 2=open).",
                ("provider",),
            )
        )
        self.circuit_transitions = r(
            Counter(
                "gateway_circuit_transitions_total",
                "Circuit breaker state transitions.",
                ("provider", "to"),
            )
        )
        self.cache_events = r(Counter("gateway_cache_events_total", "Response cache events.", ("event",)))
        self.tokens = r(Counter("gateway_tokens_total", "Tokens processed, by direction.", ("direction",)))
        self.inflight = r(Gauge("gateway_inflight_requests", "Chat requests currently in flight."))
        self.http_requests = r(
            Counter(
                "gateway_http_requests_total",
                "HTTP responses by route and status code.",
                ("route", "code"),
            )
        )
