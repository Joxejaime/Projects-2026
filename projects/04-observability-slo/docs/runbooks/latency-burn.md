# Runbook: latency SLO burn (LatencyFastBurn / LatencySlowBurn)

**What it means:** too many `/api/*` requests are taking longer than 250 ms.

## Triage
- Dashboard: compare p50/p95/p99. A p99-only rise often points at a single slow dependency or a GC/CPU
  stall; a p50 rise means broad slowness.
- Which route? `histogram_quantile(0.95, sum by (le, route) (rate(http_request_duration_seconds_bucket[5m])))`
- Saturation: CPU throttling (limits too low), too few replicas (HPA at max?), noisy neighbours.
- Recent deploy? Same rule as availability: roll back first if the timing matches.

## Mitigate
- Scale out or raise CPU limits if saturated; roll back if a release caused it; reduce expensive work.
- Slow burn (ticket) is not an emergency: capture the cause and schedule the fix.
