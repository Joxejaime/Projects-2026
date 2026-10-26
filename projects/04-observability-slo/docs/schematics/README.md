# Schematics: 04-observability-slo

Diagrams are Mermaid, so GitHub renders them inline below. Each also has a rendered `.svg` next to its
`.mmd` source. Edit the `.mmd` file, then run `python3 scripts/build_schematics.py` from the repository root.

## Observability stack

docker-compose.yml, prometheus/gen_slo_rules.py and grafana/build_dashboard.py. A load generator with error and latency knobs drives the service; Prometheus records error ratios and evaluates burn-rate alerts; Alertmanager routes by severity to a webhook receiver; the runbook link travels with the alert.

```mermaid
%% title: Observability stack
%% headline: Alert rules and dashboards are generated, not hand-written
%% takeaway: One SLO definition produces the rules and the dashboard; CI fails on drift.
%% legend: entry=Traffic,app=Service,obs=Prometheus and Grafana,alert=Alert routing,guard=Generators,ok=Human response
%% caption: docker-compose.yml, prometheus/gen_slo_rules.py and grafana/build_dashboard.py. A load generator with error and latency knobs drives the service; Prometheus records error ratios and evaluates burn-rate alerts; Alertmanager routes by severity to a webhook receiver; the runbook link travels with the alert.
flowchart TB
  lg["Load generator<br/>RPS, ERROR_RATE, SLOW_RATE"]
  app["release-tracker<br/>/metrics<br/>/api/simulate when ENABLE_CHAOS=true"]
  lg -->|"requests"| app

  subgraph PROM["Prometheus"]
    scrape["Scrape every 15s"]
    rec["Recording rules<br/>error ratio over 5m, 30m, 1h, 2h, 6h, 1d, 3d"]
    alr["Alert rules<br/>4 availability burn rates, 2 latency burn rates<br/>TargetDown, CrashLooping"]
    scrape --> rec --> alr
  end
  app --> scrape

  graf["Grafana<br/>dashboard provisioned from code"]
  rec --> graf

  am["Alertmanager<br/>group, route by severity, inhibit"]
  alr --> am
  am -->|"severity page"| recv["Receivers<br/>pager and ticket<br/>webhook sink in the lab,<br/>Slack or PagerDuty in real life"]
  am -->|"severity ticket"| recv
  recv --> rb["On-call follows the runbook<br/>link carried in the alert"]

  gen["Generators: gen_slo_rules.py, build_dashboard.py<br/>one source of truth, drift checked in CI"]
  gen -.->|"writes"| rec
  gen -.->|"writes"| alr
  gen -.->|"writes"| graf

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef obs fill:#EDE9FE,stroke:#7C3AED,stroke-width:2.5px,color:#2E1065
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#052E16
    classDef cloud fill:#FFEDD5,stroke:#EA580C,stroke-width:2.5px,color:#431407
    classDef neutral fill:#F1F5F9,stroke:#64748B,stroke-width:2.5px,color:#0F172A
    class lg entry
    class app app
    class scrape,rec,alr,graf obs
    class am,recv alert
    class rb ok
    class gen guard
```

[SVG](04a-observability-stack.svg) · [source](04a-observability-stack.mmd)

## Burn-rate alert logic

docs/slo.md and prometheus/gen_slo_rules.py. Burn rate is the observed error ratio divided by the error budget. Thresholds are burn rate times budget, the long window proves significance, the short window proves it is still happening, and Alertmanager inhibits ticket alerts while a page alert is firing.

```mermaid
%% title: Burn-rate alert logic
%% headline: Fast on real outages, quiet on blips
%% takeaway: Each alert needs a long and a short window above threshold; pages suppress tickets.
%% legend: entry=SLO,alert=Page,data=Ticket,obs=Routing,guard=Inhibition,ok=Suppressed,neutral=Explanation
%% caption: docs/slo.md and prometheus/gen_slo_rules.py. Burn rate is the observed error ratio divided by the error budget. Thresholds are burn rate times budget, the long window proves significance, the short window proves it is still happening, and Alertmanager inhibits ticket alerts while a page alert is firing.
flowchart TB
  slo["SLO: 99.5 percent of /api requests are not 5xx<br/>Error budget = 0.5 percent over 30 days"]
  burn["Burn rate = observed error ratio / error budget<br/>1x spends the budget exactly in 30 days"]
  slo --> burn

  burn --> A
  subgraph A["Availability alerts (latency uses the same pattern: 6x page, 1x ticket): fire only when BOTH windows exceed the threshold"]
    direction TB
    f["Fast: 14.4x, 1h and 5m, hold 2m<br/>threshold 7.2 percent errors, PAGE"]
    m["Medium: 6x, 6h and 30m, hold 15m<br/>threshold 3 percent, PAGE"]
    s["Slow: 3x, 1d and 2h, hold 1h<br/>threshold 1.5 percent, TICKET"]
    l["Leak: 1x, 3d and 6h, hold 3h<br/>threshold 0.5 percent, TICKET"]
  end

  why["Long window: is it real and significant?<br/>Short window: is it still happening right now?<br/>Together: fast to fire, fast to clear"]
  A --- why

  A --> route["Alertmanager routes by severity<br/>page to the pager receiver, ticket to the ticket receiver"]
  route --> inh{"Is it a ticket alert while a page alert<br/>is firing for the same service and SLO?"}
  inh -->|"yes"| quiet["Ticket suppressed by inhibition<br/>on-call is not notified twice"]
  inh -->|"no"| deliver["Delivered to the receiver"]

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef obs fill:#EDE9FE,stroke:#7C3AED,stroke-width:2.5px,color:#2E1065
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#052E16
    classDef cloud fill:#FFEDD5,stroke:#EA580C,stroke-width:2.5px,color:#431407
    classDef neutral fill:#F1F5F9,stroke:#64748B,stroke-width:2.5px,color:#0F172A
    class slo entry
    class burn,why neutral
    class f,m alert
    class s,l data
    class route,deliver obs
    class inh guard
    class quiet ok
```

[SVG](04b-burn-rate-logic.svg) · [source](04b-burn-rate-logic.mmd)

## Alert lifecycle

docs/evidence/e2e-run.md. A fault is injected, the alert goes pending then firing after its hold time, Alertmanager delivers a page with a runbook link, and a resolved notification follows when the errors stop.

```mermaid
%% title: Alert lifecycle
%% headline: From fault to page to resolved
%% takeaway: Measured end to end with real Prometheus and Alertmanager binaries.
%% caption: docs/evidence/e2e-run.md. A fault is injected, the alert goes pending then firing after its hold time, Alertmanager delivers a page with a runbook link, and a resolved notification follows when the errors stop.
sequenceDiagram
  autonumber
  participant App as release-tracker
  participant P as Prometheus
  participant AM as Alertmanager
  participant Sink as Webhook sink
  actor Oncall as On-call

  Note over App,AM: Healthy: error ratio 0, no alerts
  App->>P: Error responses begin (fault injected)
  P->>P: Both 5m and 1h ratios cross 0.072 -> alert PENDING
  P->>P: Condition holds for 2m -> alert FIRING
  P->>AM: Send alert (severity page)
  AM->>AM: Group, wait group_wait 10s
  AM->>Sink: POST /pager, status firing, runbook link
  Sink-->>Oncall: Page with link to availability-burn.md
  Oncall->>App: Follow runbook: confirm, find change, roll back
  App->>P: Errors stop, 5m ratio falls first
  P->>P: Condition false -> alert resolved
  P->>AM: Resolved
  AM->>Sink: POST /pager, status resolved
  Note over AM,Oncall: Then write a blameless postmortem
```

[SVG](04c-alert-lifecycle.svg) · [source](04c-alert-lifecycle.mmd)
