"""Per-tenant protection: request rate limiting and token (cost) budgets."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable


class TokenBucket:
    def __init__(self, rate: float, capacity: float, clock: Callable[[], float] = time.monotonic):
        self.rate = rate
        self.capacity = capacity
        self._clock = clock
        self._tokens = capacity
        self._updated = clock()

    def allow(self, cost: float = 1.0) -> bool:
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
        self._updated = now
        if self._tokens >= cost:
            self._tokens -= cost
            return True
        return False


class TenantRateLimiter:
    """One token bucket per tenant. Tenant count is bounded (LRU) so a client that
    invents tenant names cannot grow memory without limit."""

    def __init__(
        self,
        rate: float,
        burst: float,
        max_tenants: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.rate, self.burst, self.max_tenants, self._clock = rate, burst, max_tenants, clock
        self._buckets: OrderedDict[str, TokenBucket] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, tenant: str) -> bool:
        with self._lock:
            bucket = self._buckets.get(tenant)
            if bucket is None:
                bucket = TokenBucket(self.rate, self.burst, self._clock)
                self._buckets[tenant] = bucket
                if len(self._buckets) > self.max_tenants:
                    self._buckets.popitem(last=False)
            else:
                self._buckets.move_to_end(tenant)
            return bucket.allow()


class BudgetTracker:
    """Fixed-window token budget per tenant: a guardrail against runaway LLM spend.

    ``has_budget`` is checked before calling a provider; ``charge`` records actual usage
    afterwards, so a tenant can overshoot by at most one request.
    """

    def __init__(
        self,
        tokens_per_window: int,
        window_seconds: float = 3600.0,
        max_tenants: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.limit = tokens_per_window
        self.window = window_seconds
        self.max_tenants = max_tenants
        self._clock = clock
        self._usage: OrderedDict[str, tuple[float, int]] = OrderedDict()
        self._lock = threading.Lock()

    def _current(self, tenant: str) -> int:
        started, used = self._usage.get(tenant, (self._clock(), 0))
        if self._clock() - started >= self.window:
            return 0
        return used

    def has_budget(self, tenant: str) -> bool:
        with self._lock:
            return self._current(tenant) < self.limit

    def charge(self, tenant: str, tokens: int) -> None:
        with self._lock:
            now = self._clock()
            started, used = self._usage.get(tenant, (now, 0))
            if now - started >= self.window:
                started, used = now, 0
            self._usage[tenant] = (started, used + tokens)
            self._usage.move_to_end(tenant)
            if len(self._usage) > self.max_tenants:
                self._usage.popitem(last=False)

    def used(self, tenant: str) -> int:
        with self._lock:
            return self._current(tenant)
