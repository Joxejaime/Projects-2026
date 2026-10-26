"""Small thread-safe TTL + LRU cache for completed responses."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Generic, TypeVar

V = TypeVar("V")


class TTLCache(Generic[V]):
    def __init__(
        self,
        max_entries: int = 1024,
        ttl: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_entries = max_entries
        self.ttl = ttl
        self._clock = clock
        self._data: OrderedDict[str, tuple[float, V]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> V | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires_at, value = item
            if self._clock() >= expires_at:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: V) -> None:
        if self.max_entries <= 0 or self.ttl <= 0:
            return
        with self._lock:
            self._data[key] = (self._clock() + self.ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
