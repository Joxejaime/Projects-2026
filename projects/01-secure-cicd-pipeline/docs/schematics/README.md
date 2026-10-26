# Schematics: 01-secure-cicd-pipeline

Diagrams are Mermaid, so GitHub renders them inline below. Each also has a rendered `.svg` next to its
`.mmd` source. Edit the `.mmd` file, then run `python3 scripts/build_schematics.py` from the repository root.

## CI/CD pipeline stages

.github/workflows/01-secure-cicd.yml. Three checks run in parallel; build-scan builds the image without pushing, smoke-tests it, fails on fixable HIGH or CRITICAL vulnerabilities and keeps an SBOM; the publish job runs only on main, pushes by digest, signs keylessly with cosign and attaches a provenance attestation.

```mermaid
%% title: CI/CD pipeline stages
%% headline: A merge cannot publish unless every gate is green
%% takeaway: Lint, test, scan and secret-scan run first; only main publishes, signs and attests.
%% legend: entry=Trigger,guard=Check or protection,app=Build and test,data=Evidence,cloud=Registry
%% caption: .github/workflows/01-secure-cicd.yml. Three checks run in parallel; build-scan builds the image without pushing, smoke-tests it, fails on fixable HIGH or CRITICAL vulnerabilities and keeps an SBOM; the publish job runs only on main, pushes by digest, signs keylessly with cosign and attaches a provenance attestation.
flowchart TB
  trig(["Trigger: pull request, push to main, manual run"])

  subgraph PRCHK["1. Checks in parallel"]
    direction LR
    q["quality<br/>ruff lint and<br/>15 unit tests"]
    h["dockerfile-lint<br/>hadolint"]
    s["secret-scan<br/>gitleaks over<br/>full history"]
  end

  subgraph BS["2. build-scan, needs quality and dockerfile-lint"]
    direction TB
    b["Build image, not pushed<br/>APP_VERSION = commit SHA"]
    sm["Smoke test container<br/>/healthz, then app_info<br/>in /metrics"]
    tv["Trivy scan<br/>fail on fixable<br/>HIGH or CRITICAL"]
    up["Upload SARIF<br/>to Security tab"]
    sb["SBOM, SPDX JSON<br/>kept as artifact"]
    b --> sm --> tv --> up --> sb
  end

  subgraph PUB["3. publish, main only, needs build-scan and secret-scan"]
    direction LR
    pu["Push to ghcr.io<br/>tags sha-commit, latest"]
    cs["cosign sign by digest<br/>keyless via GitHub OIDC"]
    at["Attest build provenance<br/>pushed to the registry"]
    pu --> cs --> at
  end

  trig --> PRCHK
  PRCHK --> BS
  BS -->|"merge to main"| PUB

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef obs fill:#EDE9FE,stroke:#7C3AED,stroke-width:2.5px,color:#2E1065
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#052E16
    classDef cloud fill:#FFEDD5,stroke:#EA580C,stroke-width:2.5px,color:#431407
    classDef neutral fill:#F1F5F9,stroke:#64748B,stroke-width:2.5px,color:#0F172A
    class trig entry
    class q,h,s,tv,cs,at guard
    class b,sm app
    class up,sb data
    class pu cloud
```

[SVG](01a-cicd-pipeline.svg) · [source](01a-cicd-pipeline.mmd)

## Container lifecycle

app/server.py. Liveness and readiness probes, Prometheus scraping, and the graceful-shutdown sequence: SIGTERM turns readiness off, the load balancer removes the instance, in-flight requests finish, then the process exits after the grace period.

```mermaid
%% title: Container lifecycle
%% headline: Drains before it stops
%% takeaway: On SIGTERM readiness flips to 503 first, so traffic leaves before the process exits.
%% caption: app/server.py. Liveness and readiness probes, Prometheus scraping, and the graceful-shutdown sequence: SIGTERM turns readiness off, the load balancer removes the instance, in-flight requests finish, then the process exits after the grace period.
sequenceDiagram
  autonumber
  participant LB as Load balancer / kubelet
  participant App as release-tracker process
  participant Prom as Prometheus

  Note over LB,Prom: Process starts with PORT, APP_VERSION and SHUTDOWN_GRACE_SECONDS
  LB->>App: GET /healthz (liveness)
  App-->>LB: 200 ok
  LB->>App: GET /readyz (readiness)
  App-->>LB: 200 ready
  Note over LB,Prom: Traffic flows. Each request gets an X-Request-Id,<br/>one JSON log line and a latency histogram sample
  Prom->>App: GET /metrics every 15s
  App-->>Prom: counters, histogram buckets, app_info

  Note over LB,Prom: Deploy or scale-in sends SIGTERM
  LB->>App: SIGTERM
  App->>App: readiness flag = false, start grace timer
  LB->>App: GET /readyz
  App-->>LB: 503 shutting_down
  Note over LB,Prom: Removed from rotation, in-flight requests finish
  App->>App: Grace timer expires, server.shutdown()
  App-->>LB: process exits cleanly
```

[SVG](01b-container-lifecycle.svg) · [source](01b-container-lifecycle.mmd)
