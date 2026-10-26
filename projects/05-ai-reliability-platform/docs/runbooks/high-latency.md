# Runbook: high latency

**Alert:** `GatewayLatencyP95High`  **Severity:** ticket (page if combined with error-budget burn)

## 1. Locate the slowness
Compare two histograms on the dashboard:
- `gateway_request_duration_seconds` (what users feel) vs
- `gateway_provider_latency_seconds` (time inside upstream calls).

| Pattern | Likely cause |
|---|---|
| Both high | Upstream provider is slow |
| Request high, provider normal | Retries and backoff, queueing in the gateway, or CPU saturation |
| High only for `outcome="degraded"` | Fallback is slower than primary by design; consider whether it is carrying too much traffic |

## 2. Check saturation
- `gateway_inflight_requests` climbing steadily means we cannot keep up; scale out
  (ECS: raise `max_count`; Kubernetes: check the HPA) and look at CPU.

## 3. Check retry amplification
- A high `primary / timeout` rate with `max_attempts=3` can triple upstream load and make a slow
  provider slower. Lower `GATEWAY_MAX_ATTEMPTS` or `GATEWAY_ATTEMPT_TIMEOUT` temporarily.
- The total request deadline (`GATEWAY_REQUEST_TIMEOUT`) bounds worst-case latency regardless.

## 4. Verify
p95 under 1.5s for 15 minutes and `gateway_inflight_requests` stable.
