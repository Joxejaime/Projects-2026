# Service level objectives

| SLI | Definition | SLO (30 days) |
|---|---|---|
| Availability | `ok + cached + degraded` / (`ok + cached + degraded + failed`) | **99.5%** (error budget 0.5% = about 3h 36m of full outage) |
| Latency | p95 of `gateway_request_duration_seconds` | **< 1.5 s** |

**What counts as a bad event?** Only `failed` (HTTP 503, no provider could answer). Responses served
by the fallback provider (`degraded`) are *good* for availability, because the user got an answer,
but they are tracked separately (`gateway:degraded_ratio:rate5m`) so a long fallback period still
creates a ticket before it becomes an outage. `rate_limited` and `budget_exceeded` are client-caused
and are excluded from both numerator and denominator.

## Alerting policy

Burn rate = observed error ratio / allowed error ratio (0.5%).

| Alert | Condition | Severity | Meaning |
|---|---|---|---|
| `GatewayErrorBudgetFastBurn` | burn > 14.4 over 1h **and** 5m | page | 2% of the monthly budget gone in an hour |
| `GatewayErrorBudgetSlowBurn` | burn > 6 over 6h **and** 30m | page | 5% of the budget gone in six hours |
| `PrimaryProviderCircuitOpen` | circuit open for 1m | ticket | running on fallback: no user impact yet, but no redundancy |
| `FallbackServingHighShare` | > 25% degraded for 5m | ticket | fallback is carrying real load; check cost and latency |
| `GatewayLatencyP95High` | p95 > 1.5s for 10m | ticket | latency SLO at risk |
| `GatewayDown` | target not scraped for 1m | page | blind or down |

Each pair of windows is deliberate: the long window shows the burn is sustained, the short window
shows it is still happening, which stops alerts from firing long after a problem is fixed.

## Error budget policy (proposed)

- Budget > 50% remaining: ship normally.
- Budget < 50%: every change needs a rollback plan and a canary.
- Budget exhausted: feature work pauses; the team works on reliability until the burn stops.

Rules live in [`observability/rules/slo.yml`](../observability/rules/slo.yml).
