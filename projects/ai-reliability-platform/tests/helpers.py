"""Test doubles: a controllable clock and scripted providers (no real sleeping, no flakiness)."""

from __future__ import annotations

import random

from gateway.cache import TTLCache
from gateway.limits import BudgetTracker, TenantRateLimiter
from gateway.metrics import GatewayMetrics
from gateway.providers import Completion, ProviderError, ProviderRejected
from gateway.resilience import CircuitBreaker
from gateway.router import Gateway, ProviderSlot


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class ScriptedProvider:
    """Succeeds, fails, or rejects depending on ``mode``; counts every call."""

    def __init__(self, name: str, mode: str = "ok", clock: FakeClock | None = None):
        self.name = name
        self.mode = mode
        self.calls = 0
        self._clock = clock

    def complete(self, prompt: str, max_tokens: int, timeout: float) -> Completion:
        self.calls += 1
        if self._clock:
            self._clock.advance(0.01)
        if self.mode == "fail":
            raise ProviderError(f"{self.name}: boom")
        if self.mode == "reject":
            raise ProviderRejected(f"{self.name}: bad request")
        return Completion(f"{self.name}:{prompt}", tokens_in=len(prompt.split()), tokens_out=5, provider=self.name)


def make_gateway(primary="ok", fallback="ok", **overrides):
    clock = FakeClock()
    metrics = GatewayMetrics()
    p, f = ScriptedProvider("primary", primary, clock), ScriptedProvider("fallback", fallback, clock)
    slots = [
        ProviderSlot(p, CircuitBreaker("primary", failure_threshold=3, recovery_timeout=10, clock=clock)),
        ProviderSlot(f, CircuitBreaker("fallback", failure_threshold=3, recovery_timeout=10, clock=clock)),
    ]
    gateway = Gateway(
        slots,
        overrides.pop("cache", TTLCache(100, 60, clock)),
        overrides.pop("limiter", TenantRateLimiter(1000, 1000, clock=clock)),
        overrides.pop("budget", BudgetTracker(10_000, 3600, clock=clock)),
        metrics,
        clock=clock,
        sleep=clock.sleep,
        rng=random.Random(7),
        **overrides,
    )
    return gateway, p, f, clock, metrics
