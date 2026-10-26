# SLO methodology

How this lab goes from "users want checkout to work" to a page at 3 a.m. that is worth waking up for.

## 1. Pick SLIs that measure what users feel
An SLI is a ratio: **good events / valid events**. Two are defined for checkout, deliberately separate
because they fail independently (the latency chaos experiment proves it):

| SLI | Good event | Source |
|---|---|---|
| Availability | response is not a 5xx | `http_requests_total{route="/checkout"}` |
| Latency | response within 300 ms | `http_request_duration_seconds_bucket{le="0.3"}` |

Client errors (4xx) are excluded from "bad": a user typing the wrong thing is not our unreliability.

## 2. Set objectives you will actually defend
`99.9%` over 30 days gives an error budget of `0.1%` of requests: about **43 minutes** of total outage-equivalent per month.
Each extra nine costs roughly ten times more to deliver, so objectives are chosen from the user need and the business
cost of failure, not from habit. Objectives live in [`slo/shop-api.yaml`](../slo/shop-api.yaml) so changing one is a reviewed pull request.

## 3. Alert on budget burn, not on raw error rate
**Burn rate** = observed error ratio / allowed error ratio. A burn rate of 1 spends exactly the whole budget over the window.
A burn rate of `B` held for time `T` spends `B x T / window` of the budget:

| Policy | Burn rate | Windows (long and short) | Budget spent when it fires | Action |
|---|---|---|---|---|
| FastBurn | 14.4x | 1h and 5m | 14.4 x 1h / 720h = **2%** | page |
| ModerateBurn | 6x | 6h and 30m | 6 x 6h / 720h = **5%** | page |
| SlowBurn | 3x | 1d and 2h | 3 x 1d / 30d = **10%** | ticket |
| Drift | 1x | 3d and 6h | 1 x 3d / 30d = **10%** | ticket |

Why **two windows** per policy: the long window proves the burn is significant; the short window proves it is *still
happening*. Without the short window an alert keeps firing for up to an hour after the problem is fixed.
Why **four policies**: fast, severe failures page within minutes; slow leaks that would quietly eat the month's budget
are caught too, but as tickets, because nobody needs to wake up for a 4x burn.

[`slogen generate`](../slogen/rules.py) turns each SLO into recording rules for every window plus these four alerts.
CI fails if the committed [`generated/shop-api.rules.yml`](../generated/shop-api.rules.yml) is stale.

## 4. Check the alert design before an incident, using the simulator
`slogen simulate` replays an incident (constant traffic, one-minute resolution) through the policies. Real output:

```
$ python -m slogen simulate --objective 99.9 --window 30d --start-minute 10 --duration 30 --error-ratio 0.05
policy       severity  threshold  fires?    after   budget used at alert   clears after end
FastBurn     page        0.01440  yes       18 min                 2.20%              3 min
ModerateBurn page        0.00600  no            -                      -                  -
SlowBurn     ticket      0.00300  no            -                      -                  -
Drift        ticket      0.00100  no            -                      -                  -
Total error budget consumed by the incident: 3.47%
```
A 5% error spike for 30 minutes pages after 18 minutes, having spent 2.2% of the monthly budget; it clears 3 minutes after the fix.

```
$ python -m slogen simulate --objective 99.9 --window 30d --duration 10 --error-ratio 1.0
FastBurn     page        0.01440  yes        1 min                 4.63%              4 min
ModerateBurn page        0.00600  yes        6 min                16.20%             29 min
SlowBurn     ticket      0.00300  yes       18 min                23.15%            119 min
Drift        ticket      0.00100  yes       18 min                23.15%            359 min
```
A total outage pages within about 1 minute. A 10-minute outage burns 23% of the month.

```
$ python -m slogen simulate --objective 99.9 --window 30d --duration 2880 --error-ratio 0.004
FastBurn     page        0.01440  no            -                      -                  -
ModerateBurn page        0.00600  no            -                      -                  -
SlowBurn     ticket      0.00300  yes     1094 min                10.14%             29 min
```
A slow leak (0.4% errors) never pages by design; it opens a ticket after roughly 18 hours, with 10% of the budget gone.
That is the trade-off made visible: a slow burn takes a long time to detect because it has to be statistically distinguishable from noise.

## 5. Limits of this model (read before trusting it)
- The simulator assumes **constant traffic**. Real traffic is bursty, and low-traffic services produce noisy ratios;
  those need longer windows, minimum-volume guards, or synthetic probes.
- `for:` durations are included in detection times; evaluation-interval and scrape delays are not (add roughly 15-30 s).
- Recording rules over `[3d]` need three days of history to be meaningful. In a freshly started lab the long windows
  hold little data, so long-window alerts behave like short ones until history accumulates.
- Latency SLO thresholds must correspond to an existing histogram bucket (`le`), or the SLI silently measures something else.
- I validated the generated rules' structure and internal consistency (every alert references a recording rule that
  exists, thresholds equal burn rate x budget). I did **not** evaluate them in a running Prometheus in the build environment; see the README.
