# Evidence: end-to-end alert run (build environment, 2026-10-25)

**What was run:** the real `release-tracker` process (with `ENABLE_CHAOS=true`), the real Prometheus 3.5.0
and Alertmanager 0.28.1 binaries loading this repository's recording rules, alert rules and Alertmanager
routing, a webhook sink, and `loadgen.py` at 20 requests/second. Everything ran as plain local processes:
**Docker Compose and Grafana were not part of this run** (no Docker daemon was available there), and
only the Prometheus scrape interval (5 s instead of 15 s) and webhook address were changed from the committed files.

## Timeline (UTC, 2026-10-25)
| Time | Event |
|---|---|
| before 17:14:49 | About 60 s of healthy traffic. 5-minute error ratio = 0, no alerts. |
| 17:14:49 | Fault injected: 50% of `/api` requests answered with HTTP 500. |
| 17:15:30 | `AvailabilityFastBurn` -> **pending** (both the 5m and 1h ratios above 0.072). |
| 17:17:30 | `AvailabilityFastBurn` -> **firing** after its 2-minute hold. About **2 min 41 s** after fault start. |
| shortly after | Alertmanager delivered a `firing` notification to the **`pager`** receiver (`severity=page`) with the runbook link. |
| ~17:18:20 | Fault removed, healthy traffic resumed. Peak 5-minute error ratio during the run: 0.395. |
| 17:23:15 | Alert condition cleared (the 5-minute window flushed the errors). |
| by 17:27:46 | Alertmanager delivered the `resolved` notification (my poll granularity was 15 s; the delay is largely Alertmanager's default 5-minute `group_interval`). |

## Webhook sink output (verbatim)
```
{"receiver": "pager", "status": "firing", "alertname": "AvailabilityFastBurn", "severity": "page", "summary": "release-tracker availability SLO: burning error budget at 14.4x", "runbook": "docs/runbooks/availability-burn.md"}
{"receiver": "pager", "status": "resolved", "alertname": "AvailabilityFastBurn", "severity": "page", "summary": "release-tracker availability SLO: burning error budget at 14.4x", "runbook": "docs/runbooks/availability-burn.md"}
```

## Caveats (read before quoting any number)
- The fault lasted about 3.5 minutes, so **AvailabilityMediumBurn, SlowBurn and BudgetLeak stayed pending**
  and never fired: their hold times (15 min or more) were never reached. Ticket routing and the
  page-suppresses-ticket inhibition were therefore **not exercised** in this run.
- Prometheus had only about 10 minutes of history, so the "1h" and "6h" windows were effectively the same
  ~10-minute window. With a full hour of healthy history the 1h ratio would have risen more slowly and
  detection time would be longer. **Do not quote ~2m41s as a detection SLA**; repeat the game day
  (`docs/game-day.md`) with an hour of baseline to get a realistic figure.
- Synthetic traffic against a single local process; not representative of production.
