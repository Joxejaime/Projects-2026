"""Probe watcher: turns a health endpoint into firing/resolved alerts, for setups without Prometheus.

N consecutive failed probes fire the alert, dated from the first failure (so time to detect is
honest); M consecutive healthy probes resolve it, dated from the first healthy probe.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime

from .engine import synthetic_alert
from .model import utcnow


def probe(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310  (scheme checked in Watcher)
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError):
        return False


class Watcher:
    def __init__(
        self,
        url: str,
        alertname: str,
        sink: Callable[[dict], object],
        labels: dict | None = None,
        annotations: dict | None = None,
        failures: int = 3,
        successes: int = 2,
        interval: float = 1.0,
        clock: Callable[[], datetime] = utcnow,
        check: Callable[[str], bool] = probe,
    ):
        if not url.startswith(("http://", "https://")):
            raise ValueError("watch url must be http(s)")
        self.url, self.alertname, self.sink = url, alertname, sink
        self.labels, self.annotations = labels or {}, annotations or {}
        self.failures, self.successes, self.interval = failures, successes, interval
        self.clock, self.check = clock, check
        self.firing = False
        self.first_bad: datetime | None = None
        self.first_good: datetime | None = None
        self.bad = self.good = 0
        self.fired_at: datetime | None = None
        self.stopped = threading.Event()

    def tick(self) -> None:
        now = self.clock()
        if self.check(self.url):
            self.bad, self.first_bad = 0, None
            if self.firing:
                self.good += 1
                self.first_good = self.first_good or now
                if self.good >= self.successes:
                    self.sink(synthetic_alert(self.alertname, "resolved", self.labels, self.annotations, self.fired_at, self.first_good))
                    self.firing, self.good, self.first_good = False, 0, None
        else:
            self.good, self.first_good = 0, None
            if not self.firing:
                self.bad += 1
                self.first_bad = self.first_bad or now
                if self.bad >= self.failures:
                    self.fired_at = self.first_bad
                    self.sink(synthetic_alert(self.alertname, "firing", self.labels, self.annotations, self.fired_at))
                    self.firing, self.bad = True, 0

    def run(self) -> None:
        while not self.stopped.is_set():
            self.tick()
            self.stopped.wait(self.interval)

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self.stopped.set()


def post_to(url: str, token: str | None = None) -> Callable[[dict], object]:
    """A sink that forwards synthetic alerts to a remote responder's /alerts endpoint."""

    def send(payload: dict) -> int:
        headers = {"Content-Type": "application/json"} | ({"Authorization": f"Bearer {token}"} if token else {})
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")  # noqa: S310
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                    return resp.status
            except (urllib.error.URLError, OSError):
                time.sleep(2**attempt)
        raise ConnectionError(f"could not deliver alert to {url}")

    return send
