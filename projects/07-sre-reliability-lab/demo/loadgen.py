#!/usr/bin/env python3
"""Steady background traffic for the compose lab: 70% /checkout, 30% /catalog."""

import argparse
import random
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def hit(url: str) -> None:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
            resp.read()
    except Exception:  # noqa: BLE001 - 5xx and timeouts are expected during experiments
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8081")
    parser.add_argument("--rps", type=float, default=20)
    parser.add_argument("--duration", type=float, default=0, help="seconds; 0 = run forever")
    args = parser.parse_args()
    rng = random.Random(1)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=32) as pool:
        i = 0
        while args.duration == 0 or time.monotonic() - started < args.duration:
            route = "/checkout" if rng.random() < 0.7 else "/catalog"
            pool.submit(hit, args.url + route)
            i += 1
            time.sleep(max(0, started + i / args.rps - time.monotonic()))


if __name__ == "__main__":
    main()
