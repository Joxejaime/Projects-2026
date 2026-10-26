#!/usr/bin/env python3
"""Tiny open-loop load generator (standard library only).

Sends ``--rps`` requests per second for ``--duration`` seconds using a thread pool and
prints status / outcome counts and latency percentiles. Prompts are unique by default
so the response cache does not hide upstream behaviour; use ``--repeat-ratio`` to mix
in repeated prompts.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor


def one_request(url: str, tenant: str, prompt: str) -> tuple[int, str, float]:
    body = json.dumps({"prompt": prompt, "max_tokens": 32}).encode()
    req = urllib.request.Request(
        url + "/v1/chat",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Tenant": tenant},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read())
            return resp.status, payload.get("outcome", "?"), time.perf_counter() - started
    except urllib.error.HTTPError as err:
        try:
            outcome = json.loads(err.read()).get("error", "error")
        except Exception:  # noqa: BLE001
            outcome = "error"
        return err.code, outcome, time.perf_counter() - started
    except Exception:  # noqa: BLE001
        return 0, "connection_error", time.perf_counter() - started


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(round(pct / 100 * (len(sorted_values) - 1))))
    return sorted_values[idx]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--rps", type=float, default=10)
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--tenants", type=int, default=5, help="spread load across N tenants")
    parser.add_argument("--repeat-ratio", type=float, default=0.0, help="fraction of requests that reuse a prompt")
    args = parser.parse_args()

    results: list[tuple[int, str, float]] = []
    lock = threading.Lock()
    rng = random.Random(42)

    def task(i: int) -> None:
        repeated = rng.random() < args.repeat_ratio
        prompt = f"repeat prompt {rng.randint(0, 9)}" if repeated else f"unique prompt {i} {time.time_ns()}"
        res = one_request(args.url, f"tenant-{i % args.tenants}", prompt)
        with lock:
            results.append(res)

    total = int(args.rps * args.duration)
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(8, int(args.rps * 2))) as pool:
        for i in range(total):
            target = started + i / args.rps
            delay = target - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            pool.submit(task, i)
    elapsed = time.perf_counter() - started

    latencies = sorted(r[2] for r in results)
    by_status = Counter(r[0] for r in results)
    by_outcome = Counter(r[1] for r in results)
    ok = sum(c for s, c in by_status.items() if 200 <= s < 300)
    print(f"requests={len(results)} elapsed={elapsed:.1f}s success_ratio={ok / max(1, len(results)):.4f}")
    print("status  :", dict(sorted(by_status.items())))
    print("outcome :", dict(sorted(by_outcome.items())))
    p50, p95, p99 = (percentile(latencies, p) * 1000 for p in (50, 95, 99))
    worst = (latencies[-1] if latencies else 0) * 1000
    mean = (statistics.fmean(latencies) if latencies else 0) * 1000
    print(f"latency : p50={p50:.0f}ms p95={p95:.0f}ms p99={p99:.0f}ms max={worst:.0f}ms mean={mean:.0f}ms")


if __name__ == "__main__":
    main()
