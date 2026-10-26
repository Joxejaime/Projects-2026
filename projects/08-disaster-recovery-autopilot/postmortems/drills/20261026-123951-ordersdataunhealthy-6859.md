# Postmortem: Orders data unhealthy (drill: corrupt-backups)

> **Status: DRAFT, generated automatically** by drpilot on 2026-10-26T12:39:52.399Z. Facts below come from
> the alert, the responder's timeline and the recovery steps. Sections marked TODO need a human, and
> the draft is not finished until they are filled in and the document is reviewed.

| | |
|---|---|
| Incident | `20261026-123951-ordersdataunhealthy-6859` |
| Service | orders |
| Severity | page |
| Alert | `OrdersDataUnhealthy` |
| Impact | 2026-10-26T12:39:51.373Z to 2026-10-26T12:39:52.190Z (0.8s) |
| Automated recovery | failed, escalated |

## Summary

`OrdersDataUnhealthy` fired for **orders** at 2026-10-26T12:39:51.785Z. Outcome: playbook `orders-restore-from-snapshot` could not recover the service, so a human was paged. Impact lasted 0.8s.

Alert description: Disaster-recovery drill: the orders tables were deliberately destroyed.

**TODO (human):** one or two sentences a non-engineer could follow: who was affected and how.

## Key times

| Measure | Value |
|---|---|
| Time to detect (impact start to alert) | 0.4s |
| Time to mitigate (alert to verified recovery) | n/a |
| Time to recover (impact start to service restored) | 0.8s |
| Total impact (impact start to alert resolved) | 0.8s |

## Recovery objectives

| Objective | Target | Observed | Result |
|---|---|---|---|
| RTO (impact start to service restored) | 5m 00s | 0.8s | **met** |
| RPO (last good snapshot to impact start) | 15m 00s | unknown (no restore reported it) | **MISSED** |

## Timeline (UTC)

| Time | Kind | Event |
|---|---|---|
| 2026-10-26T12:39:51.373Z | impact | Impact began (alert condition first true) |
| 2026-10-26T12:39:51.785Z | alert | OrdersDataUnhealthy fired (page); incident opened |
| 2026-10-26T12:39:51.785Z | automation | Playbook 'orders-restore-from-snapshot' selected (up to 2 attempt(s)) |
| 2026-10-26T12:39:51.786Z | automation | Recovery attempt 1 started |
| 2026-10-26T12:39:51.918Z | step | Restore newest verified snapshot: FAILED (exit 1: restore failed: no snapshot verified (orders-20261026T123950Z: checksum mismatch (manifest 47b38ac3a898, dump 28d39a931605))) |
| 2026-10-26T12:39:51.920Z | automation | Recovery attempt 2 started |
| 2026-10-26T12:39:52.051Z | step | Restore newest verified snapshot: FAILED (exit 1: restore failed: no snapshot verified (orders-20261026T123950Z: checksum mismatch (manifest 47b38ac3a898, dump 28d39a931605))) |
| 2026-10-26T12:39:52.054Z | escalation | Automation gave up after 2 attempt(s); paging a human |
| 2026-10-26T12:39:52.190Z | resolved | OrdersDataUnhealthy resolved; impact over |
| 2026-10-26T12:39:52.399Z | postmortem | Postmortem draft generated |

## Automated recovery

### Attempt 1: did not recover

| Step | Result | Took | Detail |
|---|---|---|---|
| Restore newest verified snapshot | FAILED | 0.13s | exit 1: restore failed: no snapshot verified (orders-20261026T123950Z: checksum mismatch (manifest 47b38ac3a898, dump 28d39a931605)) |

<details><summary>Step output</summary>

**Restore newest verified snapshot**

```
skipping orders-20261026T123950Z: checksum mismatch (manifest 47b38ac3a898, dump 28d39a931605)
restore failed: no snapshot verified (orders-20261026T123950Z: checksum mismatch (manifest 47b38ac3a898, dump 28d39a931605))
```

</details>

### Attempt 2: did not recover

| Step | Result | Took | Detail |
|---|---|---|---|
| Restore newest verified snapshot | FAILED | 0.13s | exit 1: restore failed: no snapshot verified (orders-20261026T123950Z: checksum mismatch (manifest 47b38ac3a898, dump 28d39a931605)) |

<details><summary>Step output</summary>

**Restore newest verified snapshot**

```
skipping orders-20261026T123950Z: checksum mismatch (manifest 47b38ac3a898, dump 28d39a931605)
restore failed: no snapshot verified (orders-20261026T123950Z: checksum mismatch (manifest 47b38ac3a898, dump 28d39a931605))
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

- Went poorly: the recovery playbook ran but service was not verified healthy afterwards.
- **TODO (human):** add what the timeline cannot show.

## Action items

| Action | Type | Owner | Due |
|---|---|---|---|
| Automation 'orders-restore-from-snapshot' failed (last failure: Restore newest verified snapshot, exit 1: restore failed: no snapshot verified (orders-20261026T123950Z: checksum mismatch (manifest 47b38ac3a898, dump 28d39a931605))): fix what it hit (playbook, or the system it depends on) and re-run the drill | mitigate | TODO | TODO |
| RPO missed (unknown (no restore reported it) vs 15m 00s): no verified restore happened, so run `recover.py restore-test` on a schedule and alert when it fails | prevent | TODO | TODO |
| Find and fix what caused the failure in the first place | prevent | TODO | TODO |
