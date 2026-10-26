# Runbook: checkout latency burn

**Alerts:** `CheckoutLatencyFastBurn` / `ModerateBurn` (page), `SlowBurn` / `Drift` (ticket)
**SLO:** 99% of `/checkout` requests complete within 300 ms over 30 days (`slo/shop-api.yaml`)

## What makes this different from an availability page
Nothing is failing; users are waiting. The availability SLO can look perfectly healthy while this fires.
(`make chaos-latency` demonstrates exactly that.)

## 1. Scope it
- Share of requests over 300 ms: `1 - sum(rate(http_request_duration_seconds_bucket{route="/checkout",le="0.3"}[5m])) / sum(rate(http_request_duration_seconds_count{route="/checkout"}[5m]))`
- Whole distribution or a tail? Compare p50 with p95. A shifted p50 means everything is slow
  (CPU, a slow dependency, GC); a fat tail means a subset (one instance, one customer, lock contention).
- `/catalog` slow too? Then look at shared infrastructure first.

## 2. Mitigate
| Evidence | Action |
|---|---|
| Recent deploy | Roll back |
| CPU saturated | Scale out |
| Downstream dependency slow | Lower its timeout, serve cached or degraded data, escalate to its owner |
| One instance slow | Replace it |

## 3. Note on thresholds
The SLO threshold (`le="0.3"`) must match a real histogram bucket. If you change the threshold, change the
service's bucket boundaries in the same pull request, or the SLI silently stops measuring what you think.

## 4. After
Postmortem if paged; record budget consumed; consider whether 300 ms still reflects what users need.
