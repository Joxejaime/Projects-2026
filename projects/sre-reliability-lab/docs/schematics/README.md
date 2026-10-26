# Schematics: sre-reliability-lab

Diagrams are Mermaid, so GitHub renders them inline below. Each also has a rendered `.svg` next to its
`.mmd` source. Edit the `.mmd` file, then run `python3 scripts/build_schematics.py` from the repository root.

## System architecture

Everything in the lab, top to bottom: authoring, runtime, experiments. The SLO file drives the alert rules; the demo service gives them something real to measure; the chaos runner injects faults into the service and measures the result from the client side and from the service's own /metrics. The compose stack (make up) runs the service, load generator, Prometheus, Alertmanager and Grafana.

```mermaid
%% title: System architecture
%% caption: Everything in the lab, top to bottom: authoring, runtime, experiments. The SLO file drives the alert rules; the demo service gives them something real to measure; the chaos runner injects faults into the service and measures the result from the client side and from the service's own /metrics. The compose stack (make up) runs the service, load generator, Prometheus, Alertmanager and Grafana.
flowchart TB
    subgraph author["Authoring"]
        direction LR
        slo["slo/shop-api.yaml<br/>3 SLOs, source of truth"] --> slogen["slogen CLI<br/>check, generate, simulate, budget"] -->|generate| rules["generated/shop-api.rules.yml<br/>recording + alert rules"]
    end

    subgraph runtime["Runtime (docker compose, or make demo for the service alone)"]
        direction LR
        load["Load generator<br/>demo/loadgen.py"] --> routes
        subgraph svc["Demo service: demo/shop.py"]
            direction TB
            routes["/checkout and /catalog<br/>simulated work 20-60 ms"]
            faults["/admin/faults<br/>per-route errors and latency<br/>token gated, lab only"]
            metrics["/metrics<br/>http_requests_total<br/>http_request_duration_seconds"]
            faults -. "injects into" .-> routes
            routes --> metrics
        end
        subgraph stack["Monitoring"]
            direction TB
            prom["Prometheus"] --> am["Alertmanager<br/>pager / ticket routing"]
            prom --> graf["Grafana<br/>SLO dashboard"]
        end
        metrics -. "scrape" .-> prom
    end

    subgraph exp["Experiments"]
        direction LR
        runner["Chaos runner<br/>chaos/runner.py"] --> report["game-days/*.md<br/>report with verdict"]
    end

    rules --> prom
    runner -->|"inject and reset via admin API"| faults
    runner -->|"test traffic: target + control route"| routes
    runner -->|"scrape before and after"| metrics
    slogen -. "projection: would the alert fire?" .-> runner
```

[SVG](01-architecture.svg) · [source](01-architecture.mmd)

## From SLO to alerts

slogen/rules.py and slogen/policies.py. An SLO is stated once; the recording rules and the four burn-rate alerts are generated from it, never hand-written. Each alert needs BOTH windows above threshold (burn rate x error budget): the long window proves the burn is significant, the short window proves it is still happening, so the alert clears quickly after a fix.

```mermaid
%% title: From SLO to alerts
%% caption: slogen/rules.py and slogen/policies.py. An SLO is stated once; the recording rules and the four burn-rate alerts are generated from it, never hand-written. Each alert needs BOTH windows above threshold (burn rate x error budget): the long window proves the burn is significant, the short window proves it is still happening, so the alert clears quickly after a fix.
flowchart TD
    def["SLO definition<br/>objective, window 30d, SLI metric + selector<br/>availability: bad / total<br/>latency: 1 - (le bucket / count)"]
    def --> val["slogen check<br/>validates fields and the latency bucket"]
    val --> rec["Recording rules per SLO<br/>slo:sli_error:ratio_rate for 5m 30m 1h 2h 6h 1d 3d<br/>slo:error_budget_remaining:ratio<br/>slo:objective:ratio"]

    rec --> fast["FastBurn<br/>1h and 5m above 14.4 x budget<br/>for 2m<br/>PAGE: 2% of budget in 1 h"]
    rec --> mod["ModerateBurn<br/>6h and 30m above 6 x budget<br/>for 5m<br/>PAGE: 5% of budget in 6 h"]
    rec --> slow["SlowBurn<br/>1d and 2h above 3 x budget<br/>for 15m<br/>TICKET: 10% of budget in 1 d"]
    rec --> drift["Drift<br/>3d and 6h above 1 x budget<br/>for 15m<br/>TICKET: 10% of budget in 3 d"]

    fast --> am["Alertmanager"]
    mod --> am
    slow --> am
    drift --> am

    ci["CI: generate --check"] -. "fails if the committed rules<br/>differ from the SLO file" .-> rec
    sim["slogen simulate"] -. "replays an incident through<br/>these same four policies" .-> fast

    classDef page fill:#ffe0e0,stroke:#c92a2a,color:#7a1c1c
    classDef ticket fill:#fff3bf,stroke:#b08900,color:#5c4800
    class fast,mod page
    class slow,drift ticket
```

[SVG](02-slo-to-alerts.svg) · [source](02-slo-to-alerts.mmd)

## Alert routing and the response loop

observability/alertmanager.yml plus the docs. Pages go to the pager receiver and repeat hourly; everything else goes to the ticket receiver every 4 h. While a page is firing for an SLO, its ticket-level alerts are inhibited. Receiver URLs are placeholders: swap in PagerDuty, Opsgenie or Slack. The postmortems folder holds only a template, because no real incident has happened.

```mermaid
%% title: Alert routing and the response loop
%% caption: observability/alertmanager.yml plus the docs. Pages go to the pager receiver and repeat hourly; everything else goes to the ticket receiver every 4 h. While a page is firing for an SLO, its ticket-level alerts are inhibited. Receiver URLs are placeholders: swap in PagerDuty, Opsgenie or Slack. The postmortems folder holds only a template, because no real incident has happened.
flowchart LR
    alert(["Alert from Prometheus<br/>labels: service, slo, severity"]) --> group["Group by service + slo<br/>wait 30 s, interval 5 m"]
    group --> sev{"severity"}
    sev -- "page" --> pager["Receiver: pager<br/>repeat every 1 h"]
    sev -- "other, e.g. ticket" --> ticket["Receiver: ticket<br/>repeat every 4 h"]
    pager -. "inhibits ticket alerts<br/>with same service + slo" .-> ticket

    pager --> human["On-call engineer"]
    human --> rb["Runbook linked in the alert<br/>docs/runbooks/checkout-errors.md<br/>docs/runbooks/checkout-latency.md"]
    rb --> mit["Mitigate"]
    mit --> pm["Postmortem<br/>postmortems/template.md"]
    pm --> act["Action items"]
    act -. "new SLO, alert or runbook" .-> alert
```

[SVG](03-alert-routing.svg) · [source](03-alert-routing.mmd)

## Chaos experiment lifecycle

chaos/runner.py. The runner refuses to inject unless steady state holds, checks the abort condition every second, always clears the fault, and gives its verdict only after four checks: the fault was visible to clients, it was visible in the service's own metrics, a control route stayed healthy, and the service recovered in time. Exit codes: 0 held, 1 failed, 2 aborted, 3 precondition failed. Traffic threads are always stopped in a finally block.

```mermaid
%% title: Chaos experiment lifecycle
%% caption: chaos/runner.py. The runner refuses to inject unless steady state holds, checks the abort condition every second, always clears the fault, and gives its verdict only after four checks: the fault was visible to clients, it was visible in the service's own metrics, a control route stayed healthy, and the service recovered in time. Exit codes: 0 held, 1 failed, 2 aborted, 3 precondition failed. Traffic threads are always stopped in a finally block.
flowchart TD
    start(["Scenario YAML<br/>hypothesis, target, control, fault, abort, recovery"]) --> reset["Reset all faults<br/>start traffic on target and control routes"]
    reset --> steady{"Steady state holds?<br/>error and slow ratio under limits"}
    steady -- no --> pre(["PRECONDITION_FAILED<br/>exit 3, nothing was injected"])
    steady -- yes --> s1["Scrape /metrics (before)<br/>inject fault via admin API"]
    s1 --> watch{"Checked every second:<br/>error ratio above abort limit?<br/>duration elapsed?"}
    watch -- "abort limit hit" --> ab["aborted = true"]
    watch -- "duration elapsed" --> clear
    ab --> clear["Scrape /metrics (after)<br/>clear the fault"]
    clear --> rec["Watch recovery<br/>sliding window until healthy, or max seconds"]
    rec --> checks{"Evaluate the four checks"}
    checks -- "aborted" --> abortv(["ABORTED<br/>exit 2"])
    checks -- "all four pass" --> held(["HYPOTHESIS_HELD<br/>exit 0"])
    checks -- "any check fails" --> failed(["HYPOTHESIS_FAILED<br/>exit 1"])
    held --> rep["Write report: phases, checks, SLO projection"]
    failed --> rep
    abortv --> rep
```

[SVG](04-chaos-experiment.svg) · [source](04-chaos-experiment.mmd)

## Delivery pipeline (GitHub Actions)

.github/workflows/sre-reliability-lab.yml at the repository root. The verify job runs the same checks as make lint, check and test. The promtool job runs Prometheus' own checker on the generated rules, which is the authoritative syntax check that could not be run in the build environment.

```mermaid
%% title: Delivery pipeline (GitHub Actions)
%% caption: .github/workflows/sre-reliability-lab.yml at the repository root. The verify job runs the same checks as make lint, check and test. The promtool job runs Prometheus' own checker on the generated rules, which is the authoritative syntax check that could not be run in the build environment.
flowchart LR
    trigger(["push to main or pull request<br/>paths: this project"])

    subgraph verify["Job: verify"]
        direction TB
        v1["ruff check + format"] --> v2["slogen check<br/>SLO definitions valid"] --> v3["slogen generate --check<br/>generated rules not stale"] --> v4["validate_configs.py<br/>docker compose config"] --> v5["unittest<br/>unit, simulator, live chaos experiments"]
    end

    subgraph prom["Job: prometheus-rules (prom/prometheus container)"]
        direction TB
        p1["promtool check rules"] --> p2["promtool check config<br/>advisory only"]
    end

    trigger --> verify
    trigger --> prom
    verify --> ok(["Merge allowed"])
    prom --> ok
```

[SVG](05-delivery-pipeline.svg) · [source](05-delivery-pipeline.mmd)
