# SLOs for release-tracker

An SLO is a promise about user-visible behavior, measured with a number everyone can see.
These two cover what users of the API actually feel: "does it work?" and "is it fast?".
Health, readiness and `/metrics` traffic is excluded: those are machine traffic, not users.

| SLO | SLI (what is measured) | Target | 30-day error budget |
|---|---|---|---|
| Availability | `/api/*` requests that do not return 5xx, as a share of all `/api/*` requests | 99.5% | 0.5% of requests (about 3 h 36 min of total outage equivalent) |
| Latency | `/api/*` requests completing in 250 ms or less, as a share of all `/api/*` requests | 95% | 5% of requests may be slower |

4xx responses count as *good*: they are the client's mistake, not an outage.

## Why burn-rate alerts instead of "error rate > X%"

A fixed threshold either pages for blips that cost nothing, or stays silent through a slow leak that
quietly eats the whole budget. A **burn rate** is how fast the budget is being spent relative to the
rate that would exactly exhaust it at the end of 30 days (1x). Alerts combine a long window (is this
real?) with a short window (is it still happening?), so they fire quickly and also *stop* quickly
after recovery. The pattern follows the multiwindow, multi-burn-rate approach in Google's SRE Workbook.

| Alert | Burn rate | Windows (long AND short) | Hold | Action | Budget gone in |
|---|---|---|---|---|---|
| AvailabilityFastBurn | 14.4x | 1h and 5m | 2m | page | ~2 days (spends 2% of the monthly budget every hour) |
| AvailabilityMediumBurn | 6x | 6h and 30m | 15m | page | 5 days |
| AvailabilitySlowBurn | 3x | 1d and 2h | 1h | ticket | 10 days |
| AvailabilityBudgetLeak | 1x | 3d and 6h | 3h | ticket | 30 days (exactly on the limit) |
| LatencyFastBurn | 6x | 1h and 5m | 5m | page | 5 days |
| LatencySlowBurn | 1x | 6h and 30m | 30m | ticket | 30 days |

Thresholds are `burn rate x error budget`, for example 14.4 x 0.005 = 0.072 (7.2% errors).
The rules are generated from one definition (`prometheus/gen_slo_rules.py`), so the targets above,
the recording rules, the alerts and the dashboard cannot drift apart.

## Error budget policy (a proposal, to agree with the team)

- **Budget healthy (more than 50% left):** ship normally.
- **Budget low (less than 25% left):** only reliability work and low-risk changes until it recovers.
- **Budget exhausted:** feature releases pause; the next sprint's priority is the cause of the burn.
- Every page-level alert gets a short written review; repeated causes become backlog items.

## Known limitations

- Ratios are computed from `rate()`, which is noisy at very low traffic (a handful of requests per
  minute). For low-traffic services add a minimum-traffic guard or use longer windows.
- Prometheus here keeps 3 days of data, so the 30-day budget is *modelled* by the burn rates and not
  plotted as a monthly remaining-budget curve. A real deployment would add long-term storage
  (Thanos, Mimir, or a managed service) for that panel.
- The metrics are measured at the application. A load balancer or DNS outage would make the app look
  healthy; a synthetic probe from outside would be the next addition.
