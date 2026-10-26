# Runbook: availability SLO burn (AvailabilityFastBurn / MediumBurn / SlowBurn / BudgetLeak)

**What it means:** more `/api/*` requests are failing with 5xx than the SLO allows, and have been for a
sustained period. Page-level alerts mean the monthly budget will be gone within days at this rate.

## 1. Confirm and size it (2 minutes)
- Open the Grafana dashboard "release-tracker: SLOs and golden signals". Is the burn-rate panel above 1?
- Which route and status? In Prometheus:
  `sum by (route, status) (rate(http_requests_total{job="release-tracker",status=~"5.."}[5m]))`
- Is it one instance or all? Group by `instance`.

## 2. What changed?
- A deploy in the last hour? Compare `app_info{version}` across instances. If the error start matches a
  rollout: **roll back first, investigate second** (`argocd app rollback` / revert the promotion PR, or
  redeploy the previous image tag).
- Dependency or config change? Check recent merges and infrastructure changes.

## 3. Look at the evidence
- Logs are JSON, one line per request: filter `"status":500` and group by `route`; use `request_id`
  to follow a single request.
- Restarts: `changes(process_start_time_seconds[15m])`. Frequent restarts also trip `CrashLooping`.
- Saturation: CPU/memory in the platform (ECS service metrics or `kubectl top pods`); HPA at max?

## 4. Mitigate
- Roll back the bad release, scale out if saturated, or shed the failing route if there is a safe way.
- Communicate: post status in the incident channel with impact, start time, and next update time.

## 5. After
- Confirm the alert resolves (both windows drop below threshold).
- Write a blameless postmortem for every page (`docs/postmortem-template.md`); file follow-ups.
