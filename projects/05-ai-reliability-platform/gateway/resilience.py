"""Resilience primitives: circuit breaker and retry with exponential backoff + full jitter."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from enum import IntEnum
from typing import TypeVar

T = TypeVar("T")


class CircuitState(IntEnum):
    CLOSED = 0
    HALF_OPEN = 1
    OPEN = 2


class CircuitBreaker:
    """Consecutive-failure circuit breaker with a half-open probe phase.

    CLOSED    -> calls flow; ``failure_threshold`` consecutive failures trip it OPEN.
    OPEN      -> calls are rejected immediately until ``recovery_timeout`` elapses.
    HALF_OPEN -> up to ``half_open_max_calls`` probe calls are allowed; one success closes
                 the circuit, one failure re-opens it.

    Callers must pair every ``allow()`` that returned True with exactly one
    ``record_success()`` or ``record_failure()``.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 15.0,
        half_open_max_calls: int = 1,
        clock: Callable[[], float] = time.monotonic,
        on_state_change: Callable[[str, CircuitState, CircuitState], None] | None = None,
    ) -> None:
        if failure_threshold < 1 or half_open_max_calls < 1:
            raise ValueError("thresholds must be >= 1")
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self._clock = clock
        self._on_state_change = on_state_change
        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._half_open_inflight = 0

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    def available(self) -> bool:
        """Non-mutating check used for readiness: could a call be attempted right now?"""
        with self._lock:
            if self._state is CircuitState.OPEN:
                return self._clock() - self._opened_at >= self.recovery_timeout
            return True

    def allow(self) -> bool:
        with self._lock:
            if self._state is CircuitState.OPEN:
                if self._clock() - self._opened_at < self.recovery_timeout:
                    return False
                self._transition(CircuitState.HALF_OPEN)
                self._half_open_inflight = 0
            if self._state is CircuitState.HALF_OPEN:
                if self._half_open_inflight >= self.half_open_max_calls:
                    return False
                self._half_open_inflight += 1
            return True

    def record_success(self) -> None:
        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._half_open_inflight = max(0, self._half_open_inflight - 1)
                self._failures = 0
                self._transition(CircuitState.CLOSED)
            elif self._state is CircuitState.CLOSED:
                self._failures = 0

    def record_failure(self) -> None:
        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._half_open_inflight = max(0, self._half_open_inflight - 1)
                self._open()
            elif self._state is CircuitState.CLOSED:
                self._failures += 1
                if self._failures >= self.failure_threshold:
                    self._open()

    # -- internals (lock held) -------------------------------------------------
    def _open(self) -> None:
        self._opened_at = self._clock()
        self._transition(CircuitState.OPEN)

    def _transition(self, new: CircuitState) -> None:
        old, self._state = self._state, new
        if old is not new and self._on_state_change:
            self._on_state_change(self.name, old, new)


def call_with_retries(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.05,
    max_delay: float = 0.5,
    retryable: Callable[[Exception], bool] = lambda exc: bool(getattr(exc, "retryable", False)),
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
    on_retry: Callable[[int, Exception, float], None] | None = None,
) -> T:
    """Call ``fn`` with up to ``attempts`` tries.

    Uses exponential backoff with *full jitter* (sleep ~ U(0, min(cap, base * 2**n))),
    which avoids synchronized retry storms. A retry is skipped when the error is not
    retryable or when sleeping would exceed the caller's overall ``deadline``.
    """
    rng = rng or random.Random()
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - we re-raise below
            last_exc = exc
            if attempt == attempts - 1 or not retryable(exc):
                raise
            delay = rng.uniform(0, min(max_delay, base_delay * (2**attempt)))
            if deadline is not None and clock() + delay >= deadline:
                raise
            if on_retry:
                on_retry(attempt + 1, exc, delay)
            sleep(delay)
    assert last_exc is not None  # pragma: no cover - loop always returns or raises
    raise last_exc
