# Game day: prove the alerts work

Run this yourself and keep the evidence. A portfolio claim of "I built SLO alerting" is much
stronger with your own screenshots and a filled-in postmortem.

## Setup
```bash
make up                       # builds the app, starts Prometheus, Alertmanager, Grafana, load
open http://127.0.0.1:3000    # Grafana (user admin, password from GRAFANA_ADMIN_PASSWORD or the compose default)
make logs-alerts              # in another terminal: alerts arriving at the webhook sink
```

## Scenario 1: error outage (expect a page)
1. Let the healthy load run for ~5 minutes so there is a baseline.
2. `make outage` (50% of requests return 500).
3. Record the time. Expected: burn rate climbs on the dashboard; `AvailabilityFastBurn` goes Pending
   then Firing about 2 minutes after both the 5m and 1h ratios exceed 7.2%; the sink logs a `pager` alert.
4. `make healthy`. Expected: the 5m ratio drops first and the alert resolves shortly after.

## Scenario 2: latency (expect LatencyFastBurn)
`make slow` makes 50% of requests take 600 ms. Expected: p95 jumps above 250 ms; `LatencyFastBurn` fires.

## Scenario 3: crash (expect TargetDown)
`docker compose stop app`, wait 2+ minutes, then `docker compose start app`.

## Write it up
Copy `docs/postmortem-template.md`, fill in the real times you recorded and attach screenshots of the
dashboard and the sink output. Replace any "expected" statements above with what you actually observed.
