# Schematics: sre-reliability-lab

Diagrams are Mermaid, so GitHub renders them inline below. Each also has a rendered `.svg` next to its
`.mmd` source. Edit the `.mmd` file, then run `python3 scripts/build_schematics.py` from the repository root.

## System architecture

Everything in the lab. The SLO file drives the alert rules; the demo service gives them something real to measure; the chaos runner injects faults into the service and measures the result from the client side and from the service's own /metrics. The compose stack (make up) runs the service, load generator, Prometheus, Alertmanager and Grafana.

```mermaid
%% title: System architecture
%% headline: Reliability as code, tested with real failures
%% takeaway: One SLO file drives the alerts. A chaos runner breaks the demo service and checks what happened.
%% legend: data=SLO source,guard=Generator and rules,app=Service,alert=Fault injection,obs=Observability,ok=Report
%% caption: Everything in the lab. The SLO file drives the alert rules; the demo service gives them something real to measure; the chaos runner injects faults into the service and measures the result from the client side and from the service's own /metrics. The compose stack (make up) runs the service, load generator, Prometheus, Alertmanager and Grafana.
flowchart TB
    slo["SLO file<br/>3 SLOs, source of truth"] --> slogen["slogen CLI"] --> rules["Generated<br/>Prometheus rules"]
    subgraph svc["Demo service"]
        routes["/checkout and /catalog"]
        faults["/admin/faults<br/>per-route errors<br/>and latency"]
        metrics["/metrics"]
        faults -.-> routes
        routes --> metrics
    end
    subgraph stack["Monitoring"]
        prom["Prometheus"]
        am["Alertmanager"]
        graf["Grafana"]
        prom --> am
        prom --> graf
    end
    runner["Chaos runner"] --> report["Game-day report"]
    rules --> prom
    metrics -. scrape .-> prom
    runner -->|"inject and reset"| faults
    runner -->|"test traffic"| routes
    runner -->|"scrape before and after"| metrics

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef obs fill:#EDE9FE,stroke:#7C3AED,stroke-width:2.5px,color:#2E1065
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#0B3D1E
    class slo data
    class slogen,rules guard
    class routes app
    class faults,runner alert
    class metrics,prom,am,graf obs
    class report ok
    style svc fill:#EFF6FF,stroke:#93C5FD,stroke-width:2px,color:#1E3A8A
    style stack fill:#F5F3FF,stroke:#C4B5FD,stroke-width:2px,color:#4C1D95
```

[SVG](01-architecture.svg) · [source](01-architecture.mmd)

## From SLO to alerts

slogen/rules.py and slogen/policies.py. An SLO is stated once; the recording rules and the four burn-rate alerts are generated from it, never hand-written. Each alert needs BOTH windows above threshold (burn rate x error budget): the long window proves the burn is significant, the short window proves it is still happening, so the alert clears quickly after a fix. CI runs generate --check, and slogen simulate replays an incident through the same four policies.

```mermaid
%% title: From SLO to alerts
%% headline: One SLO file generates every alert
%% takeaway: Four burn-rate alerts: two page someone, two open tickets.
%% legend: entry=SLO definition,guard=Generated rules,alert=Page,data=Ticket,obs=Alertmanager,neutral=CI check
%% caption: slogen/rules.py and slogen/policies.py. An SLO is stated once; the recording rules and the four burn-rate alerts are generated from it, never hand-written. Each alert needs BOTH windows above threshold (burn rate x error budget): the long window proves the burn is significant, the short window proves it is still happening, so the alert clears quickly after a fix. CI runs generate --check, and slogen simulate replays an incident through the same four policies.
flowchart TB
    def["SLO definition<br/>objective, 30 day window,<br/>availability or latency SLI"]
    rec["Generated recording rules<br/>error ratio over 5m to 3d windows<br/>error budget remaining"]
    fast["FastBurn<br/>1h and 5m above 14.4x<br/>PAGE"]
    mod["ModerateBurn<br/>6h and 30m above 6x<br/>PAGE"]
    slow["SlowBurn<br/>1d and 2h above 3x<br/>TICKET"]
    drift["Drift<br/>3d and 6h above 1x<br/>TICKET"]
    am["Alertmanager"]
    ci["CI: generate --check<br/>fails on stale rules"]
    def --> rec
    rec --> fast
    rec --> mod
    rec --> slow
    rec --> drift
    fast --> am
    mod --> am
    slow --> am
    drift --> am
    ci -.-> rec

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef obs fill:#EDE9FE,stroke:#7C3AED,stroke-width:2.5px,color:#2E1065
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef neutral fill:#F1F5F9,stroke:#64748B,stroke-width:2.5px,color:#0F172A
    class def entry
    class rec guard
    class fast,mod alert
    class slow,drift data
    class am obs
    class ci neutral
```

[SVG](02-slo-to-alerts.svg) · [source](02-slo-to-alerts.mmd)

## Alert routing and the response loop

observability/alertmanager.yml plus the docs. Pages go to the pager receiver and repeat hourly; everything else goes to the ticket receiver every 4 h. While a page is firing for an SLO, its ticket-level alerts are inhibited. Receiver URLs are placeholders: swap in PagerDuty, Opsgenie or Slack. The postmortems folder holds only a template, because no real incident has happened.

```mermaid
%% title: Alert routing and the response loop
%% headline: Pages wake someone. Tickets can wait.
%% takeaway: Alertmanager routing, runbooks, postmortems and the action items that feed back into alerts.
%% legend: entry=Alert,guard=Routing,alert=Page,data=Ticket,app=Human response,ok=Learning
%% caption: observability/alertmanager.yml plus the docs. Pages go to the pager receiver and repeat hourly; everything else goes to the ticket receiver every 4 h. While a page is firing for an SLO, its ticket-level alerts are inhibited. Receiver URLs are placeholders: swap in PagerDuty, Opsgenie or Slack. The postmortems folder holds only a template, because no real incident has happened.
flowchart TB
    alert(["Alert from Prometheus<br/>labels: service, slo, severity"]) --> group["Alertmanager groups by<br/>service and SLO"]
    group --> sev{{"Severity?"}}
    sev -- page --> pager["Pager receiver<br/>repeats every hour"]
    sev -- ticket --> ticket["Ticket receiver<br/>repeats every 4 hours"]
    pager -. "inhibits tickets for the same SLO" .-> ticket
    pager --> human["On-call engineer follows the<br/>runbook linked in the alert, mitigates"]
    human --> pm["Postmortem and action items<br/>new SLO, alert or runbook"]
    pm -.-> alert

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#0B3D1E
    class alert entry
    class group,sev guard
    class pager alert
    class ticket data
    class human app
    class pm ok
```

[SVG](03-alert-routing.svg) · [source](03-alert-routing.mmd)

## Chaos experiment lifecycle

chaos/runner.py. The runner refuses to inject unless steady state holds, checks the abort condition every second, always clears the fault, and gives its verdict only after four checks: the fault was visible to clients, it was visible in the service's own metrics, a control route stayed healthy, and the service recovered in time. Exit codes: 0 held, 1 failed, 2 aborted, 3 precondition failed. Traffic threads are always stopped in a finally block.

```mermaid
%% title: Chaos experiment lifecycle
%% headline: A chaos experiment that checks its own claims
%% takeaway: It refuses to start unless healthy, aborts on damage and checks that a control route stayed clean.
%% legend: entry=Scenario,app=Action,guard=Check,ok=Hypothesis held,data=Stopped early,alert=Failed
%% caption: chaos/runner.py. The runner refuses to inject unless steady state holds, checks the abort condition every second, always clears the fault, and gives its verdict only after four checks: the fault was visible to clients, it was visible in the service's own metrics, a control route stayed healthy, and the service recovered in time. Exit codes: 0 held, 1 failed, 2 aborted, 3 precondition failed. Traffic threads are always stopped in a finally block.
flowchart TB
    start(["Scenario file"]) --> steady{{"Steady state holds?"}}
    steady -- no --> pre(["Precondition failed<br/>exit 3, nothing injected"])
    steady -- yes --> inject["Inject the fault<br/>scrape /metrics before"]
    inject --> watch{{"Abort limit hit?<br/>checked every second"}}
    watch -- "yes: stop early" --> clear
    watch -- "no: duration elapsed" --> clear["Clear the fault<br/>scrape /metrics after, watch recovery"]
    clear --> checks["Four checks<br/>fault seen by clients and by service metrics<br/>control route clean, recovered in time"]
    checks -- "aborted" --> abortv(["Aborted, exit 2"])
    checks -- "all pass" --> held(["Hypothesis held, exit 0"])
    checks -- "any fails" --> failed(["Hypothesis failed, exit 1"])

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#0B3D1E
    class start entry
    class inject,clear app
    class steady,watch,checks guard
    class pre,abortv data
    class failed alert
    class held ok
```

[SVG](04-chaos-experiment.svg) · [source](04-chaos-experiment.mmd)

## Delivery pipeline (GitHub Actions)

.github/workflows/07-sre-reliability-lab.yml at the repository root. The verify job runs the same checks as make lint, check and test. The promtool job runs Prometheus' own checker on the generated rules, which is the authoritative syntax check that could not be run in the build environment.

```mermaid
%% title: Delivery pipeline (GitHub Actions)
%% headline: Stale alert rules fail the build
%% takeaway: CI regenerates the rules from the SLO file and runs Prometheus' own checker.
%% legend: entry=Trigger,app=Verify job,guard=Prometheus job,ok=Checks complete
%% caption: .github/workflows/07-sre-reliability-lab.yml at the repository root. The verify job runs the same checks as make lint, check and test. The promtool job runs Prometheus' own checker on the generated rules, which is the authoritative syntax check that could not be run in the build environment.
flowchart TB
    trigger(["Push or pull request<br/>touching this project"])
    verify["Job: verify<br/>ruff lint and format<br/>SLO definitions valid<br/>generated rules not stale<br/>config checks, compose file<br/>tests incl. live chaos experiments"]
    prom["Job: prometheus-rules<br/>promtool check rules<br/>promtool check config, advisory"]
    ok(["Checks complete"])
    trigger --> verify
    trigger --> prom
    verify --> ok
    prom --> ok

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#0B3D1E
    class trigger entry
    class verify app
    class prom guard
    class ok ok
```

[SVG](05-delivery-pipeline.svg) · [source](05-delivery-pipeline.mmd)
