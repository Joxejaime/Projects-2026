# Schematics: ai-reliability-platform

Diagrams are Mermaid, so GitHub renders them inline below. Each also has a rendered `.svg` next to its
`.mmd` source. Edit the `.mmd` file, then run `python3 scripts/build_schematics.py` from the repository root.

## System architecture

What runs where. The gateway is one stdlib Python process; Prometheus scrapes it and evaluates the SLO rules in observability/rules/slo.yml, Grafana reads Prometheus. Providers are mocks.

```mermaid
%% title: System architecture
%% headline: An AI gateway built to keep answering when a provider fails
%% takeaway: Rate limits, budgets, cache, two providers, metrics and SLO alerts in one small service.
%% legend: entry=Client,app=Gateway,guard=Circuit breakers,neutral=External provider,obs=Observability,alert=On-call
%% caption: What runs where. The gateway is one stdlib Python process; Prometheus scrapes it and evaluates the SLO rules in observability/rules/slo.yml, Grafana reads Prometheus. Providers are mocks.
flowchart TB
    client["Client / tenant<br/>POST /v1/chat with X-Tenant header"]
    subgraph gw["Gateway process"]
        http["HTTP server<br/>/v1/chat, /healthz, /readyz, /metrics"]
        core["Router<br/>rate limit, budget, cache"]
        pbrk["Circuit breaker<br/>primary"]
        fbrk["Circuit breaker<br/>fallback"]
        http --> core
        core --> pbrk
        core --> fbrk
    end
    primary["Primary provider<br/>mock, about 120 ms"]
    fallback["Fallback provider<br/>mock, about 250 ms"]
    subgraph obs["Observability"]
        prom["Prometheus<br/>scrapes /metrics"]
        rules["7 alert rules<br/>recording rules"]
        graf["Grafana<br/>dashboard"]
        prom --> rules
        prom --> graf
    end
    oncall["On-call engineer<br/>alerts link to runbooks"]
    client --> http
    pbrk --> primary
    fbrk --> fallback
    http -. "/metrics" .-> prom
    rules -.-> oncall

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef obs fill:#EDE9FE,stroke:#7C3AED,stroke-width:2.5px,color:#2E1065
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef neutral fill:#F1F5F9,stroke:#64748B,stroke-width:2.5px,color:#0F172A
    class client entry
    class http,core app
    class pbrk,fbrk guard
    class primary,fallback neutral
    class prom,rules,graf obs
    class oncall alert
    style gw fill:#EFF6FF,stroke:#93C5FD,stroke-width:2px,color:#1E3A8A
    style obs fill:#F5F3FF,stroke:#C4B5FD,stroke-width:2px,color:#4C1D95
```

[SVG](01-architecture.svg) · [source](01-architecture.mmd)

## Request decision flow

The order of checks in gateway/router.py. Each terminal state is a label on gateway_requests_total, which the SLO is computed from. Defaults: 2.0 s request deadline, 0.8 s per attempt, 3 attempts per provider, full-jitter backoff (base 0.05 s, cap 0.4 s). A provider is skipped when its circuit is open or its error is not retryable.

```mermaid
%% title: Request decision flow
%% headline: Every request takes one of six paths, and each one is measured
%% takeaway: Limits first, then cache, then the primary provider, then the fallback.
%% legend: entry=Request,guard=Check,app=Provider call,ok=Success,data=Fallback success,alert=Rejected
%% caption: The order of checks in gateway/router.py. Each terminal state is a label on gateway_requests_total, which the SLO is computed from. Defaults: 2.0 s request deadline, 0.8 s per attempt, 3 attempts per provider, full-jitter backoff (base 0.05 s, cap 0.4 s). A provider is skipped when its circuit is open or its error is not retryable.
flowchart TB
    start(["POST /v1/chat"]) --> rl{{"Under the tenant<br/>rate limit?"}}
    rl -- no --> r429a["429 rate_limited"]
    rl -- yes --> bud{{"Token budget<br/>left?"}}
    bud -- no --> r429b["429 budget_exceeded"]
    bud -- yes --> cache{{"Cache hit?"}}
    cache -- yes --> okc["200 cached"]
    cache -- no --> p["Primary provider<br/>circuit breaker check, up to 3 attempts<br/>jittered backoff, 2 s deadline"]
    p -- success --> store["200 ok<br/>cache and charge tokens"]
    p -- "failed or circuit open" --> f["Fallback provider<br/>same retries and breaker"]
    f -- success --> degraded["200 degraded<br/>served by the fallback"]
    f -- failed --> r503["503 upstream_unavailable"]

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#0B3D1E
    class start entry
    class rl,bud,cache guard
    class p,f app
    class r429a,r429b,r503 alert
    class okc,store ok
    class degraded data
```

[SVG](02-request-flow.svg) · [source](02-request-flow.mmd)

## Circuit breaker states

gateway/resilience.py. Defaults from gateway/config.py: 5 consecutive failures to open, 15 s before a probe. A provider rejecting a bad request counts as a success, because it is not a health signal. The numeric state is exported as gateway_circuit_state, and the PrimaryProviderCircuitOpen alert fires when the primary stays in state 2 (open) for 1 minute.

```mermaid
%% title: Circuit breaker states
%% headline: A circuit breaker stops hammering a provider that is down
%% takeaway: Five failures open it. After 15 seconds one probe call decides whether to close it.
%% legend: ok=Calls flow,alert=Calls rejected,data=One probe allowed
%% caption: gateway/resilience.py. Defaults from gateway/config.py: 5 consecutive failures to open, 15 s before a probe. A provider rejecting a bad request counts as a success, because it is not a health signal. The numeric state is exported as gateway_circuit_state, and the PrimaryProviderCircuitOpen alert fires when the primary stays in state 2 (open) for 1 minute.
stateDiagram-v2
    [*] --> CLOSED
    CLOSED --> OPEN: 5 consecutive failures
    OPEN --> HALF_OPEN: 15 s recovery timeout elapsed
    HALF_OPEN --> CLOSED: probe call succeeds
    HALF_OPEN --> OPEN: probe call fails

    CLOSED: CLOSED<br/>calls flow normally
    OPEN: OPEN<br/>calls rejected immediately<br/>traffic goes to fallback
    HALF_OPEN: HALF_OPEN<br/>one probe call allowed

    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#0B3D1E
    class CLOSED ok
    class OPEN alert
    class HALF_OPEN data
```

[SVG](03-circuit-breaker.svg) · [source](03-circuit-breaker.mmd)

## AWS deployment (Terraform)

What terraform/ declares. Not applied in the build environment, so treat it as reviewed but unproven. Without a certificate_arn the ALB forwards plain HTTP on port 80; with one it serves HTTPS on 443 and port 80 redirects to it (301). Tasks run in private subnets and reach the outside world only through the NAT gateway on port 443.

```mermaid
%% title: AWS deployment (Terraform)
%% headline: The AWS deployment: private tasks behind a load balancer
%% takeaway: ECS Fargate, ALB, NAT, autoscaling and four CloudWatch alarms, all in Terraform (not yet applied).
%% legend: entry=Internet,app=Load balancer and tasks,cloud=AWS service,obs=Monitoring,alert=Notification
%% caption: What terraform/ declares. Not applied in the build environment, so treat it as reviewed but unproven. Without a certificate_arn the ALB forwards plain HTTP on port 80; with one it serves HTTPS on 443 and port 80 redirects to it (301). Tasks run in private subnets and reach the outside world only through the NAT gateway on port 443.
flowchart TB
    internet(["Internet clients"]) --> alb
    subgraph vpc["VPC"]
        subgraph pub["Public subnets"]
            alb["Application Load Balancer<br/>:80, plus :443 with a certificate"]
            nat["NAT gateway"]
        end
        subgraph priv["Private subnets"]
            t1["ECS Fargate task"]
            t2["ECS Fargate task"]
        end
        alb -->|"ALB security group only"| t1
        alb --> t2
        t1 -->|"egress 443 only"| nat
        t2 --> nat
    end
    nat --> out(["Provider and AWS APIs"])
    ecr[("ECR repository, CloudWatch logs,<br/>Auto Scaling on CPU, IAM roles")]
    ecr -.-> priv
    al["4 CloudWatch alarms<br/>5xx, p95 latency, unhealthy hosts, CPU"] --> sns["SNS topic to email"]
    priv -.-> al

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef obs fill:#EDE9FE,stroke:#7C3AED,stroke-width:2.5px,color:#2E1065
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef cloud fill:#FFEDD5,stroke:#EA580C,stroke-width:2.5px,color:#5A2300
    class internet,out entry
    class alb,t1,t2 app
    class nat,ecr cloud
    class al obs
    class sns alert
    style vpc fill:#F8FAFC,stroke:#CBD5E1,stroke-width:2px,color:#334155
    style pub fill:#EFF6FF,stroke:#93C5FD,stroke-width:2px,color:#1E3A8A
    style priv fill:#F0FDF4,stroke:#86EFAC,stroke-width:2px,color:#166534
```

[SVG](04-aws-deployment.svg) · [source](04-aws-deployment.mmd)

## Delivery pipeline (GitHub Actions)

.github/workflows/ai-reliability-platform.yml at the repository root. The test and terraform jobs run on every push to main and pull request touching this project; the image job waits for tests. Only a tag named ai-reliability-platform-vX.Y.Z publishes to GHCR.

```mermaid
%% title: Delivery pipeline (GitHub Actions)
%% headline: Every change is linted, tested, scanned and validated
%% takeaway: Tests, Terraform checks and a Trivy image scan run before anything is released.
%% legend: entry=Trigger,app=Test job,guard=Terraform job,cloud=Image job,data=Release gate,ok=Done
%% caption: .github/workflows/ai-reliability-platform.yml at the repository root. The test and terraform jobs run on every push to main and pull request touching this project; the image job waits for tests. Only a tag named ai-reliability-platform-vX.Y.Z publishes to GHCR.
flowchart TB
    trigger(["Push or pull request<br/>touching this project"])
    test["Job: test<br/>ruff lint and format<br/>unit and end-to-end tests<br/>config validation<br/>compose file check"]
    tf["Job: terraform<br/>fmt check<br/>init without backend<br/>validate"]
    img["Job: image, after tests pass<br/>build the container<br/>Trivy image scan fails on HIGH or CRITICAL<br/>Trivy config scan, report only"]
    tag{{"Release tag?"}}
    release["Publish to GHCR<br/>provenance and SBOM"]
    done(["Checks complete"])
    trigger --> test
    trigger --> tf
    test --> img
    img --> tag
    tag -- yes --> release --> done
    tag -- no --> done
    tf --> done

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#0B3D1E
    classDef cloud fill:#FFEDD5,stroke:#EA580C,stroke-width:2.5px,color:#5A2300
    class trigger entry
    class test app
    class tf guard
    class img cloud
    class tag data
    class release,done ok
```

[SVG](05-delivery-pipeline.svg) · [source](05-delivery-pipeline.mmd)
