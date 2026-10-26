# Runbook: primary provider degraded (circuit open / high fallback share)

**Alerts:** `PrimaryProviderCircuitOpen`, `FallbackServingHighShare`  **Severity:** ticket
**User impact:** usually none; responses come from the fallback, with higher latency and cost.

## 1. Confirm (2 minutes)
- Dashboard "AI Gateway - Reliability Overview": `Circuit: primary` should read OPEN, and the
  "Provider attempts by result" panel should show `primary / error` or `primary / timeout`.
- Check the vendor's status page and your account's rate-limit / quota dashboard.
- `curl -s $GATEWAY/metrics | grep gateway_provider_calls_total`: errors, timeouts or both?
  - mostly `timeout` -> upstream is slow; see [high-latency](high-latency.md)
  - mostly `error`   -> upstream is failing; continue below

## 2. Decide
| Situation | Action |
|---|---|
| Vendor incident, fallback healthy, latency within SLO | Do nothing. Watch; the breaker re-probes every `GATEWAY_BREAKER_RECOVERY_TIMEOUT` seconds and closes itself. |
| Fallback share is high and cost is a concern | Tighten per-tenant budgets (`GATEWAY_TENANT_TOKEN_BUDGET`) and tell heavy tenants. |
| Our config caused it (bad key, wrong model name, quota) | Fix the config and roll out; the breaker recovers on its own. |
| Fallback is also erroring | Escalate: [all-providers-down](all-providers-down.md). |

## 3. Verify recovery
- Circuit state returns to CLOSED; degraded share falls under 5%.
- `gateway_provider_calls_total{provider="primary",result="success"}` is increasing.

## 4. Afterwards
- If the outage exceeded 30 minutes or burned more than 5% of the budget, write a blameless postmortem
  ([template](../postmortem-template.md)).
- Ask: did the alert fire quickly enough, and did the fallback absorb the load as designed?
