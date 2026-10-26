# Chaos experiment: checkout-error-injection

**Verdict:** `HYPOTHESIS_HELD`

## Hypothesis
If 30% of /checkout requests start failing with HTTP 500, the blast radius stays on /checkout,
the failure is visible in client-side error ratio and the checkout-availability SLO signal, and the
service returns to a healthy steady state within 15 seconds of the fault being removed.

## Measurements (client-side)
| Phase | Requests | Error ratio | Slow ratio | p50 | p95 |
|---|---|---|---|---|---|
| Steady state | 200 | 0.0% | 0.0% | 44 ms | 59 ms |
| During fault | 499 | 30.3% | 0.0% | 41 ms | 60 ms |
| Control route during fault (`/catalog`) | 100 | 0.0% | 0.0% | 42 ms | 60 ms |
| After clearing | 76 | 0.0% | 0.0% | 43 ms | 60 ms |

Server-side SLI bad-event ratio during the fault (from the service's own `/metrics`): **30.2%**.

Recovery: 3.0 s after the fault was cleared. The recovery check uses a 3 s sliding window, so it cannot report less than that: the fault itself is removed instantly.

## Checks
- PASS: fault visible to clients
- PASS: fault visible in the server-side SLI
- PASS: control route unaffected
- PASS: recovered within the limit

## SLO projection
Observed bad-event ratio during the fault: **30.3%**, a burn rate of **302.6x** against a 99.9% objective.
If it persisted, the alert policies would behave as follows (simulated, one-minute resolution):

| Policy | Severity | Fires | After |
|---|---|---|---|
| FastBurn | page | yes | 3 min |
| ModerateBurn | page | yes | 11 min |
| SlowBurn | ticket | yes | 28 min |
| Drift | ticket | yes | 28 min |

Alerts the scenario expects to fire in the compose stack: CheckoutAvailabilityFastBurn.
