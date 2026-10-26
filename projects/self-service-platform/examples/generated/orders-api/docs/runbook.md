# Runbook: orders-api

Owner: team-orders  |  Tier: standard  |  Availability target: 99.9%

## First five minutes
1. Is it up? `kubectl get pods -l app.kubernetes.io/name=orders-api` and `GET /healthz`.
2. Did something change recently? Check the last deployment and roll back first if so:
   `kubectl rollout undo deployment/orders-api`.
3. Look at logs for errors around the time the alert fired.

## Common failures
| Symptom | Check | Action |
|---|---|---|
| Pods CrashLoopBackOff | `kubectl logs --previous` | Fix config or roll back |
| Pods Pending | `kubectl describe pod` | Resource requests too high, or cluster full: ask the platform team |
| Readiness failing | `/healthz` from inside the pod | Dependency down? Check upstream service health |

## Escalation
Owning team: team-orders. Platform team for cluster-level problems.

## After an incident
Write a blameless postmortem and link it here.
