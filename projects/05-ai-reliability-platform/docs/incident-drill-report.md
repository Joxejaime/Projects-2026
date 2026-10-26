# Incident drill report: primary provider outage

> **This is a simulated incident on a local lab stack, not a production event.** It exists to
> show how the system behaves under failure and how I would write it up. Numbers come from a
> single run on one laptop-class machine (mock providers, 15 requests/s per phase, 12 s per
> phase) and demonstrate behaviour, not capacity. Raw output: [`drill_output.txt`](drill_output.txt).
> Reproduce with `make up && make drill`, or `scripts/incident_drill.sh` against a local
> `python -m gateway`.

## Scenario
Inject a 100% error rate into the primary provider while traffic flows, then clear it.

## Results

| Phase | Requests | HTTP 200 | Outcomes | p50 | p95 | Primary circuit at end |
|---|---|---|---|---|---|---|
| 1. Healthy baseline | 180 | 180 (100%) | 180 ok | 140 ms | 156 ms | closed |
| 2. Primary 100% errors | 180 | 180 (100%) | 180 degraded (served by fallback) | 290 ms | 326 ms | **open** |
| 3. Fault cleared | 180 | 180 (100%) | 178 ok, 2 degraded | 141 ms | 156 ms | closed |

## What the numbers show
- **No user-visible failures** during a total primary outage: all 180 requests succeeded via the
  fallback. They were slower (p50 about 290 ms vs 140 ms) because the fallback is configured as the slower provider.
- **The circuit opened and stayed open**, so the primary stopped receiving traffic instead of being
  hammered with retries (3 attempts per request would otherwise triple load on a failing upstream).
- **Worst case latency was bounded**: the slowest request during the transition took 751 ms, thanks
  to per-attempt timeouts and the overall request deadline.
- **Recovery was automatic**: after the fault was cleared, a half-open probe succeeded and the circuit
  closed. The 2 degraded responses in phase 3 are consistent with the half-open design: with
  `half_open_max_calls=1`, requests that arrive while the single probe is in flight are served by the
  fallback rather than risking the primary. (I inferred this from the breaker logic and the counts; I did
  not trace those two requests individually.)

## Detection (what the alerts would have done)
Evaluated against [`observability/rules/slo.yml`](../observability/rules/slo.yml):
- `PrimaryProviderCircuitOpen` (ticket) would fire after the circuit had been open for 1 minute.
- `FallbackServingHighShare` (ticket) would fire after degraded responses exceeded 25% for 5 minutes.
- `GatewayErrorBudgetFastBurn` (page) would **not** fire: users saw no failed requests. That is the
  intended design, because paging someone for an outage the system absorbed would be noise.

I did not run Prometheus in this session, so alert firing times above come from the rule definitions,
not from observed alert state. Running the stack with `make up` and the drill lets you watch them live.

## Gaps and follow-ups
| Gap | Action |
|---|---|
| Mock providers cannot model partial brown-outs (slow but not failing) with realistic distributions | Add a latency-distribution fault mode and a drill for it |
| Only one failure mode drilled | Drill "both providers down" and verify the page fires and `/readyz` flips to 503 |
| Alert timings unverified end to end | Add a CI job that runs the stack and asserts the alert transitions |
