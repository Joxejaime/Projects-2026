"""LLM provider abstraction plus a mock provider with runtime fault injection.

The mock stands in for real vendors (OpenAI, Anthropic, Bedrock, ...). Real providers
would implement the same ``complete`` contract; the resilience layer does not care.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class ProviderError(Exception):
    """Upstream failure. ``retryable`` tells the retry layer whether another try may help."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class ProviderTimeout(ProviderError):
    pass


class ProviderRejected(ProviderError):
    """Upstream rejected the request itself (4xx-like). Retrying cannot help."""

    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class CircuitOpen(ProviderError):
    def __init__(self, provider: str):
        super().__init__(f"{provider}: circuit open", retryable=False)


@dataclass(frozen=True)
class Completion:
    text: str
    tokens_in: int
    tokens_out: int
    provider: str


class Provider(Protocol):
    name: str

    def complete(self, prompt: str, max_tokens: int, timeout: float) -> Completion: ...


class FaultConfig:
    """Mutable fault settings, changed at runtime through the admin endpoint."""

    def __init__(self, error_rate: float = 0.0, extra_latency: float = 0.0) -> None:
        self._lock = threading.Lock()
        self._error_rate = error_rate
        self._extra_latency = extra_latency

    def update(self, error_rate: float | None = None, extra_latency: float | None = None) -> None:
        with self._lock:
            if error_rate is not None:
                self._error_rate = min(1.0, max(0.0, error_rate))
            if extra_latency is not None:
                self._extra_latency = max(0.0, extra_latency)

    def reset(self) -> None:
        self.update(error_rate=0.0, extra_latency=0.0)

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return {"error_rate": self._error_rate, "extra_latency_ms": self._extra_latency * 1000}


class MockProvider:
    def __init__(
        self,
        name: str,
        base_latency: float = 0.05,
        jitter: float = 0.03,
        faults: FaultConfig | None = None,
        rng: random.Random | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = name
        self.base_latency = base_latency
        self.jitter = jitter
        self.faults = faults or FaultConfig()
        self._rng = rng or random.Random()
        self._sleep = sleep

    def complete(self, prompt: str, max_tokens: int, timeout: float) -> Completion:
        faults = self.faults.snapshot()
        latency = self.base_latency + self._rng.uniform(0, self.jitter) + faults["extra_latency_ms"] / 1000
        if latency > timeout:
            self._sleep(timeout)
            raise ProviderTimeout(f"{self.name}: no response within {timeout:.2f}s")
        self._sleep(latency)
        if self._rng.random() < faults["error_rate"]:
            raise ProviderError(f"{self.name}: simulated upstream 503")
        words = prompt.split()
        tokens_out = min(max_tokens, 24)
        return Completion(
            text=f"[{self.name}] mock completion for: {' '.join(words[:8])}",
            tokens_in=len(words),
            tokens_out=tokens_out,
            provider=self.name,
        )
