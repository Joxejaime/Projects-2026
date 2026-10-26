#!/usr/bin/env python3
"""Synthetic traffic with controllable failure modes (stdlib only).

Environment:
  TARGET       base URL                       (default http://app:8080)
  RPS          requests per second, total     (default 20)
  ERROR_RATE   fraction answered with HTTP 500 (default 0.0)
  SLOW_RATE    fraction delayed by SLOW_MS     (default 0.0)
  SLOW_MS      injected delay in milliseconds  (default 400)
  DURATION     seconds to run, 0 = forever     (default 0)

Needs the target to run with ENABLE_CHAOS=true for the error/slow fractions.
"""

from __future__ import annotations

import json
import os
import random
import signal
import threading
import time
import urllib.error
import urllib.request

TARGET = os.environ.get("TARGET", "http://app:8080").rstrip("/")
RPS = float(os.environ.get("RPS", "20"))
ERROR_RATE = float(os.environ.get("ERROR_RATE", "0"))
SLOW_RATE = float(os.environ.get("SLOW_RATE", "0"))
SLOW_MS = int(os.environ.get("SLOW_MS", "400"))
DURATION = float(os.environ.get("DURATION", "0"))

stop = threading.Event()
counts = {"ok": 0, "error": 0}
lock = threading.Lock()


def call(path: str, body: dict | None = None) -> int:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(TARGET + path, data=data, method="POST" if body is not None else "GET")  # noqa: S310
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status
    except urllib.error.HTTPError as err:
        return err.code
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return 0


def one_request() -> None:
    roll = random.random()
    if roll < ERROR_RATE:
        status = call("/api/simulate?status=500")
    elif roll < ERROR_RATE + SLOW_RATE:
        status = call(f"/api/simulate?delay_ms={SLOW_MS}")
    elif random.random() < 0.3:
        payload = {
            "service": random.choice(["billing", "search", "auth"]),
            "version": f"1.0.{random.randint(0, 9)}",
            "environment": "dev",
        }
        status = call("/api/deployments", payload)
    else:
        status = call("/api/deployments")
    with lock:
        counts["error" if status == 0 or status >= 500 else "ok"] += 1


def main() -> None:
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    print(
        f"loadgen target={TARGET} rps={RPS} error_rate={ERROR_RATE} slow_rate={SLOW_RATE} slow_ms={SLOW_MS}",
        flush=True,
    )
    start = time.monotonic()
    next_tick = start
    last_report = start
    interval = 1.0 / RPS
    while not stop.is_set():
        if DURATION and time.monotonic() - start >= DURATION:
            break
        threading.Thread(target=one_request, daemon=True).start()
        next_tick += interval
        delay = next_tick - time.monotonic()
        if delay > 0:
            stop.wait(delay)
        if time.monotonic() - last_report >= 30:
            with lock:
                print(f"sent ok={counts['ok']} error={counts['error']}", flush=True)
            last_report = time.monotonic()
    with lock:
        print(f"done ok={counts['ok']} error={counts['error']}", flush=True)


if __name__ == "__main__":
    main()
