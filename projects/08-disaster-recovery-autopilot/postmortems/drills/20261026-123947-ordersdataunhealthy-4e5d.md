# Postmortem: Orders data unhealthy (drill: poisoned-backup)

> **Status: DRAFT, generated automatically** by drpilot on 2026-10-26T12:39:49.074Z. Facts below come from
> the alert, the responder's timeline and the recovery steps. Sections marked TODO need a human, and
> the draft is not finished until they are filled in and the document is reviewed.

| | |
|---|---|
| Incident | `20261026-123947-ordersdataunhealthy-4e5d` |
| Service | orders |
| Severity | page |
| Alert | `OrdersDataUnhealthy` |
| Impact | 2026-10-26T12:39:47.041Z to 2026-10-26T12:39:48.060Z (1.0s) |
| Automated recovery | succeeded (verified) |

## Summary

`OrdersDataUnhealthy` fired for **orders** at 2026-10-26T12:39:47.452Z. Outcome: service was recovered automatically by playbook `orders-restore-from-snapshot`. Impact lasted 1.0s.

Alert description: Disaster-recovery drill: the orders tables were deliberately destroyed.

**TODO (human):** one or two sentences a non-engineer could follow: who was affected and how.

## Key times

| Measure | Value |
|---|---|
| Time to detect (impact start to alert) | 0.4s |
| Time to mitigate (alert to verified recovery) | 1.6s |
| Time to recover (impact start to service restored) | 2.0s |
| Total impact (impact start to alert resolved) | 1.0s |

Automated recovery counts only once consecutive health probes pass, so it can finish slightly after the alert resolved.

## Recovery objectives

| Objective | Target | Observed | Result |
|---|---|---|---|
| RTO (impact start to service restored) | 5m 00s | 2.0s | **met** |
| RPO (last good snapshot to impact start) | 15m 00s | 3.0s | **met** |

## Facts reported by recovery steps

| Fact | Value |
|---|---|
| `restore_seconds` | 0.03 |
| `rows_order_items` | 5 |
| `rows_orders` | 5 |
| `skipped_reasons` | orders-20261026T123946Z: fails validation (totals: 2 order(s) whose total differs from their items) |
| `snapshot` | orders-20261026T123944Z |
| `snapshot_age_seconds` | 3.9 |
| `snapshot_created_at` | 2026-10-26T12:39:44Z |
| `snapshots_skipped` | 1 |

## Timeline (UTC)

| Time | Kind | Event |
|---|---|---|
| 2026-10-26T12:39:47.041Z | impact | Impact began (alert condition first true) |
| 2026-10-26T12:39:47.452Z | alert | OrdersDataUnhealthy fired (page); incident opened |
| 2026-10-26T12:39:47.452Z | automation | Playbook 'orders-restore-from-snapshot' selected (up to 2 attempt(s)) |
| 2026-10-26T12:39:47.453Z | automation | Recovery attempt 1 started |
| 2026-10-26T12:39:47.903Z | step | Restore newest verified snapshot: ok (exit 0) |
| 2026-10-26T12:39:48.060Z | resolved | OrdersDataUnhealthy resolved; impact over |
| 2026-10-26T12:39:49.071Z | verify | Health probes: passed (3 consecutive healthy probes (3 total)) |
| 2026-10-26T12:39:49.071Z | verify | Validate recovered data and write path: passed (exit 0) |
| 2026-10-26T12:39:49.071Z | verify | Verification passed |
| 2026-10-26T12:39:49.072Z | mitigated | Service recovered by automation (attempt 1) |
| 2026-10-26T12:39:49.074Z | postmortem | Postmortem draft generated |

## Automated recovery

### Attempt 1: verified recovery

| Step | Result | Took | Detail |
|---|---|---|---|
| Restore newest verified snapshot | ok | 0.45s | exit 0 |
| Health probes | ok | 1.01s | 3 consecutive healthy probes (3 total) |
| Validate recovered data and write path | ok | 0.16s | exit 0 |

<details><summary>Step output</summary>

**Restore newest verified snapshot**

```
skipping orders-20261026T123946Z: fails validation (totals: 2 order(s) whose total differs from their items)
PASS  connect: database reachable
PASS  schema: tables present: orders, order_items
PASS  row counts: match manifest: orders=5, order_items=5
PASS  orphans: no order item without an order
PASS  totals: every order total equals the sum of its items
restored orders-20261026T123944Z (2026-10-26T12:39:44Z)
{"facts": {"snapshot": "orders-20261026T123944Z", "snapshot_created_at": "2026-10-26T12:39:44Z", "snapshot_age_seconds": 3.9, "restore_seconds": 0.03, "snapshots_skipped": 1, "skipped_reasons": "orders-20261026T123946Z: fails validation (totals: 2 order(s) whose total differs from their items)", "rows_orders": 5, "rows_order_items": 5}}
```

**Validate recovered data and write path**

```
PASS  connect: database reachable
PASS  schema: tables present: orders, order_items
PASS  row counts: orders=5, order_items=5 (no manifest to compare)
PASS  orphans: no order item without an order
PASS  totals: every order total equals the sum of its items
PASS  write path: order 6 written through the service, found in the database, removed
{"facts": {"rows_orders": 5, "rows_order_items": 5}}
```

</details>

## Alert details

| Label | Value |
|---|---|
| `alertname` | OrdersDataUnhealthy |
| `autoremediate` | true |
| `environment` | drill |
| `service` | orders |
| `severity` | page |

Runbook: docs/runbooks/orders-data-unhealthy.md

## Root cause and contributing factors

**TODO (human):** the automation knows the symptom and what restored service, not why it broke. Describe systems
and decisions, not people, and keep asking why until you reach something that can be fixed.

## What went well / what went poorly / where we got lucky

- Went well: automation restored service 1.6s after the alert, verified by health probes.
- **TODO (human):** add what the timeline cannot show.

## Action items

| Action | Type | Owner | Due |
|---|---|---|---|
| 1 newer snapshot(s) failed verification during recovery (orders-20261026T123946Z: fails validation (totals: 2 order(s) whose total differs from their items)): find out how they came to be taken in that state | prevent | TODO | TODO |
| Find and fix what caused the failure in the first place | prevent | TODO | TODO |
