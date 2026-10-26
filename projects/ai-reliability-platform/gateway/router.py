"""Gateway core: rate limit -> budget -> cache -> primary (retry + breaker) -> fallback."""

from __future__ import annotations

import hashlib
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from .cache import TTLCache
from .limits import BudgetTracker, TenantRateLimiter
from .metrics import GatewayMetrics
from .providers import (
    CircuitOpen,
    Completion,
    Provider,
    ProviderError,
    ProviderRejected,
    ProviderTimeout,
)
from .resilience import CircuitBreaker, call_with_retries


class GatewayError(Exception):
    status = 500
    code = "internal_error"
    outcome = "failed"


class RateLimited(GatewayError):
    status, code, outcome = 429, "rate_limited", "rate_limited"


class BudgetExceeded(GatewayError):
    status, code, outcome = 429, "budget_exceeded", "budget_exceeded"


class AllProvidersFailed(GatewayError):
    status, code, outcome = 503, "upstream_unavailable", "failed"


@dataclass(frozen=True)
class ChatResult:
    text: str
    provider: str
    outcome: str  # ok | cached | degraded
    tokens_in: int
    tokens_out: int
    attempts: int


@dataclass
class ProviderSlot:
    provider: Provider
    breaker: CircuitBreaker


class Gateway:
    def __init__(
        self,
        slots: list[ProviderSlot],
        cache: TTLCache[Completion],
        limiter: TenantRateLimiter,
        budget: BudgetTracker,
        metrics: GatewayMetrics,
        *,
        request_timeout: float = 2.0,
        attempt_timeout: float = 0.8,
        max_attempts: int = 3,
        retry_base: float = 0.05,
        retry_cap: float = 0.4,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        if not slots:
            raise ValueError("at least one provider is required")
        self.slots = slots
        self.cache = cache
        self.limiter = limiter
        self.budget = budget
        self.metrics = metrics
        self.request_timeout = request_timeout
        self.attempt_timeout = attempt_timeout
        self.max_attempts = max_attempts
        self.retry_base = retry_base
        self.retry_cap = retry_cap
        self._clock = clock
        self._sleep = sleep
        self._rng = rng or random.Random()

    # -- public API ------------------------------------------------------------
    def ready(self) -> bool:
        """Ready while at least one provider could take traffic."""
        return any(slot.breaker.available() for slot in self.slots)

    def chat(self, tenant: str, prompt: str, max_tokens: int = 64) -> ChatResult:
        started = self._clock()
        self.metrics.inflight.inc()
        outcome = "failed"
        try:
            result = self._chat(tenant, prompt, max_tokens)
            outcome = result.outcome
            return result
        except GatewayError as exc:
            outcome = exc.outcome
            raise
        finally:
            self.metrics.inflight.dec()
            self.metrics.requests.inc(outcome=outcome)
            self.metrics.request_duration.observe(self._clock() - started, outcome=outcome)

    # -- internals -------------------------------------------------------------
    def _chat(self, tenant: str, prompt: str, max_tokens: int) -> ChatResult:
        if not self.limiter.allow(tenant):
            raise RateLimited(f"tenant {tenant!r} exceeded request rate")
        if not self.budget.has_budget(tenant):
            raise BudgetExceeded(f"tenant {tenant!r} exhausted its token budget")

        key = hashlib.sha256(f"{max_tokens}\x00{prompt}".encode()).hexdigest()
        cached = self.cache.get(key)
        if cached is not None:
            self.metrics.cache_events.inc(event="hit")
            return ChatResult(cached.text, cached.provider, "cached", 0, 0, 0)
        self.metrics.cache_events.inc(event="miss")

        deadline = self._clock() + self.request_timeout
        attempts = 0
        last_error: Exception | None = None

        for index, slot in enumerate(self.slots):
            if self._clock() >= deadline:
                break
            counter = {"n": 0}
            try:
                completion = call_with_retries(
                    lambda slot=slot, counter=counter: self._attempt(slot, prompt, max_tokens, deadline, counter),
                    attempts=self.max_attempts,
                    base_delay=self.retry_base,
                    max_delay=self.retry_cap,
                    deadline=deadline,
                    clock=self._clock,
                    sleep=self._sleep,
                    rng=self._rng,
                )
            except ProviderError as exc:
                last_error = exc
                attempts += counter["n"]
                continue
            attempts += counter["n"]
            self.cache.set(key, completion)
            self.budget.charge(tenant, completion.tokens_in + completion.tokens_out)
            self.metrics.tokens.inc(completion.tokens_in, direction="in")
            self.metrics.tokens.inc(completion.tokens_out, direction="out")
            outcome = "ok" if index == 0 else "degraded"
            return ChatResult(
                completion.text,
                completion.provider,
                outcome,
                completion.tokens_in,
                completion.tokens_out,
                attempts,
            )

        raise AllProvidersFailed(str(last_error) if last_error else "no provider available")

    def _attempt(self, slot: ProviderSlot, prompt: str, max_tokens: int, deadline: float, counter: dict) -> Completion:
        name = slot.provider.name
        if not slot.breaker.allow():
            self.metrics.provider_calls.inc(provider=name, result="circuit_open")
            raise CircuitOpen(name)
        counter["n"] += 1
        timeout = max(0.05, min(self.attempt_timeout, deadline - self._clock()))
        started = self._clock()
        try:
            completion = slot.provider.complete(prompt, max_tokens, timeout)
        except ProviderRejected:
            # The provider answered; the *request* was bad. That is not a health signal.
            slot.breaker.record_success()
            self.metrics.provider_calls.inc(provider=name, result="rejected")
            raise
        except ProviderTimeout:
            slot.breaker.record_failure()
            self.metrics.provider_calls.inc(provider=name, result="timeout")
            raise
        except ProviderError:
            slot.breaker.record_failure()
            self.metrics.provider_calls.inc(provider=name, result="error")
            raise
        slot.breaker.record_success()
        self.metrics.provider_calls.inc(provider=name, result="success")
        self.metrics.provider_latency.observe(self._clock() - started, provider=name)
        return completion
