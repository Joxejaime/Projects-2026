# Chaos experiment: checkout-latency-injection

**Verdict:** `HYPOTHESIS_HELD`

## Hypothesis
If /checkout gains 400 ms of extra latency, no request fails (the availability SLI stays clean) but the
checkout-latency SLI breaks because responses exceed the 300 ms threshold. This confirms the two SLIs measure
different failure modes and that the latency SLO, not the availability SLO, is the one that alerts.

## Measurements (client-side)
| Phase | Requests | Error ratio | Slow ratio | p50 | p95 |
|---|---|---|---|---|---|
| Steady state | 200 | 0.0% | 0.0% | 42 ms | 59 ms |
| During fault | 490 | 0.0% | 99.8% | 441 ms | 459 ms |
| Control route during fault (`/catalog`) | 100 | 0.0% | 0.0% | 40 ms | 60 ms |
| After clearing | 110 | 0.0% | 10.0% | 40 ms | 446 ms |

Server-side SLI bad-event ratio during the fault (from the service's own `/metrics`): **99.8%**.

Recovery: 4.0 s after the fault was cleared. The recovery check uses a 3 s sliding window, so it cannot report less than that: the fault itself is removed instantly.

## Checks
- PASS: fault visible to clients
- PASS: fault visible in the server-side SLI
- PASS: control route unaffected
- PASS: recovered within the limit
- PASS: client error ratio <= 0.01

## SLO projection
Observed bad-event ratio during the fault: **99.8%**, a burn rate of **99.8x** against a 99% objective.
If it persisted, the alert policies would behave as follows (simulated, one-minute resolution):

| Policy | Severity | Fires | After |
|---|---|---|---|
| FastBurn | page | yes | 9 min |
| ModerateBurn | page | yes | 25 min |
| SlowBurn | ticket | yes | 57 min |
| Drift | ticket | yes | 57 min |

Alerts the scenario expects to fire in the compose stack: CheckoutLatencyFastBurn.
