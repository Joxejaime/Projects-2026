# Runbook: checkout availability burn

**Alerts:** `CheckoutAvailabilityFastBurn` / `ModerateBurn` (page), `SlowBurn` / `Drift` (ticket)
**SLO:** 99.9% of `/checkout` requests do not return 5xx over 30 days (`slo/shop-api.yaml`)

## What the alert is telling you
A burn rate above the threshold on both a long and a short window: the budget is being spent fast
**and it is still being spent**. FastBurn at 14.4x means roughly 2% of the monthly budget per hour.

## 1. Scope it (2 minutes)
- Is it only `/checkout`? Compare against `catalog-availability`. If only checkout is burning, suspect
  the checkout code path or its dependencies; if both, suspect the platform (node, network, deploy).
- Which status codes? `sum by (code) (rate(http_requests_total{route="/checkout"}[5m]))`.
- When did it start, and what changed then (deploy, config, dependency incident)?

## 2. Mitigate before you diagnose
| Evidence | Action |
|---|---|
| Started right after a deploy | Roll back. Investigate afterwards. |
| One bad instance | Remove it from rotation / restart it. |
| Dependency failing | Enable degradation or fallback if one exists; otherwise escalate to the dependency owner. |
| Traffic spike | Scale out; shed non-critical load. |

## 3. Confirm recovery
`slo:sli_error:ratio_rate5m` back under the budget line, and both burn alerts resolved. The 5-minute
short window means FastBurn clears within minutes of the fix.

## 4. After
- Note budget consumed (`slo:error_budget_remaining:ratio`). Under 50% remaining: tighten release controls.
- Postmortem if you paged. Use [`postmortems/template.md`](../../postmortems/template.md).
- Rehearse this failure with `make chaos-errors` so the runbook is exercised before it is needed.
