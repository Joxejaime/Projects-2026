# Runbook: all providers down / error budget burning

**Alerts:** `GatewayErrorBudgetFastBurn`, `GatewayErrorBudgetSlowBurn`, `GatewayDown`  **Severity:** page
**User impact:** requests fail with HTTP 503 `upstream_unavailable`.

## 1. Triage (first 5 minutes)
1. Acknowledge the page. Open the dashboard and note the start time.
2. Is the gateway itself healthy? `GET /healthz` and `/readyz`.
   - `/healthz` fails -> the process is down: check task/pod status and recent deploys, then **roll back**.
   - `/healthz` OK, `/readyz` 503 -> both provider circuits are open (or the instance is draining).
3. Did we deploy in the last hour? If yes, roll back first and investigate afterwards.
   - ECS: the deployment circuit breaker rolls back automatically; confirm with `aws ecs describe-services`.
   - Kubernetes: `kubectl -n ai-gateway rollout undo deploy/gateway`.

## 2. Diagnose
- `gateway_provider_calls_total` by `provider` and `result`:
  - both providers erroring -> shared cause: network egress, DNS, expired credentials, region-wide vendor incident
  - one provider erroring, circuit open on both -> check whether the fallback was overloaded by the traffic shift
- Structured logs: filter on `"msg":"circuit breaker state change"` to build the timeline.
- Egress: from a task, can it reach the provider on :443? (security group / NetworkPolicy / NAT health)

## 3. Mitigate (pick the least risky that works)
- Roll back the last change.
- Shed load: lower `GATEWAY_RATE_LIMIT_RPS` so healthy capacity serves priority tenants.
- Raise cache TTL (`GATEWAY_CACHE_TTL`) to answer repeated prompts without upstream calls.
- Communicate: post a status update every 30 minutes even if nothing has changed.

## 4. Recover and verify
- Circuits return to CLOSED after the next successful probe.
- Error ratio under SLO for 15 minutes before declaring resolved.

## 5. After
Postmortem within 5 working days ([template](../postmortem-template.md)). Add or tune an alert if
detection was slower than the 5-minute triage target.
