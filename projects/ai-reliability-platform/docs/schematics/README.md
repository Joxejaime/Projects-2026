# Schematics: ai-reliability-platform

Diagrams are Mermaid, so GitHub renders them inline below. Each also has a rendered `.svg` next to its
`.mmd` source. Edit the `.mmd` file, then run `python3 scripts/build_schematics.py` from the repository root.

## System architecture

What runs where. The gateway is one stdlib Python process; Prometheus scrapes it and evaluates the SLO rules in observability/rules/slo.yml, Grafana reads Prometheus. Providers are mocks.

```mermaid
%% title: System architecture
%% caption: What runs where. The gateway is one stdlib Python process; Prometheus scrapes it and evaluates the SLO rules in observability/rules/slo.yml, Grafana reads Prometheus. Providers are mocks.
flowchart LR
    client["Client / tenant<br/>X-Tenant header"]

    subgraph gw["Gateway process (gateway/)"]
        direction TB
        http["HTTP server<br/>/v1/chat  /healthz  /readyz  /metrics<br/>/admin/* lab only, token gated"]
        core["Router<br/>rate limit, budget, cache, providers"]
        pbrk["Circuit breaker<br/>primary"]
        fbrk["Circuit breaker<br/>fallback"]
        http --> core
        core --> pbrk
        core --> fbrk
    end

    primary["Primary provider<br/>mock, ~120 ms"]
    fallback["Fallback provider<br/>mock, ~250 ms"]

    subgraph obs["Observability (observability/)"]
        direction TB
        prom["Prometheus<br/>scrapes /metrics"]
        rules["Recording rules +<br/>7 alert rules"]
        graf["Grafana<br/>provisioned dashboard"]
        prom --> rules
        prom --> graf
    end

    client -->|"POST /v1/chat"| http
    pbrk --> primary
    fbrk --> fallback
    http -. "/metrics" .-> prom
    rules -. "page / ticket alerts<br/>link to docs/runbooks" .-> oncall["On-call engineer"]
```

[SVG](01-architecture.svg) · [source](01-architecture.mmd)

## Request decision flow

The order of checks in gateway/router.py. Each terminal state is a label on gateway_requests_total, which the SLO is computed from. Defaults: 2.0 s request deadline, 0.8 s per attempt, 3 attempts per provider, full-jitter backoff (base 0.05 s, cap 0.4 s).

```mermaid
%% title: Request decision flow
%% caption: The order of checks in gateway/router.py. Each terminal state is a label on gateway_requests_total, which the SLO is computed from. Defaults: 2.0 s request deadline, 0.8 s per attempt, 3 attempts per provider, full-jitter backoff (base 0.05 s, cap 0.4 s).
flowchart TD
    start(["POST /v1/chat"]) --> rl{"Tenant under<br/>rate limit?"}
    rl -- no --> r429a["429 rate_limited"]
    rl -- yes --> bud{"Tenant has<br/>token budget?"}
    bud -- no --> r429b["429 budget_exceeded"]
    bud -- yes --> cache{"Cache hit?"}
    cache -- yes --> okc["200 outcome=cached"]
    cache -- no --> p["Try primary provider"]

    p --> pb{"Breaker<br/>allows call?"}
    pb -- "no, open" --> f["Try fallback provider"]
    pb -- yes --> pcall["Call provider<br/>attempt timeout 0.8 s"]
    pcall --> pres{"Result"}
    pres -- success --> store
    pres -- "retryable error" --> retry{"Attempts left and<br/>deadline allows?"}
    retry -- yes --> pcall
    retry -- no --> f
    pres -- "not retryable" --> f

    f --> fres{"Fallback<br/>succeeds?"}
    fres -- yes --> degraded["Store + charge budget<br/>200 outcome=degraded"]
    fres -- no --> r503["503 upstream_unavailable<br/>outcome=failed"]

    store["Store in cache, charge tokens<br/>200 outcome=ok"]

    classDef good fill:#d8f3dc,stroke:#2d6a4f,color:#1b4332
    classDef warn fill:#fff3bf,stroke:#b08900,color:#5c4800
    classDef bad fill:#ffe0e0,stroke:#c92a2a,color:#7a1c1c
    class okc,store good
    class degraded warn
    class r429a,r429b,r503 bad
```

[SVG](02-request-flow.svg) · [source](02-request-flow.mmd)

## Circuit breaker states

gateway/resilience.py. Defaults from gateway/config.py: 5 consecutive failures to open, 15 s before a probe. A provider rejecting a bad request counts as a success, because it is not a health signal. The numeric state is exported as gateway_circuit_state, and the PrimaryProviderCircuitOpen alert fires when the primary stays in state 2 (open) for 1 minute.

```mermaid
%% title: Circuit breaker states
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
```

[SVG](03-circuit-breaker.svg) · [source](03-circuit-breaker.mmd)

## AWS deployment (Terraform)

What terraform/ declares. Not applied in the build environment, so treat it as reviewed but unproven. Without a certificate_arn the ALB forwards plain HTTP on port 80; with one it serves HTTPS on 443 and port 80 redirects to it (301). Tasks run in private subnets and reach the outside world only through the NAT gateway on port 443.

```mermaid
%% title: AWS deployment (Terraform)
%% caption: What terraform/ declares. Not applied in the build environment, so treat it as reviewed but unproven. Without a certificate_arn the ALB forwards plain HTTP on port 80; with one it serves HTTPS on 443 and port 80 redirects to it (301). Tasks run in private subnets and reach the outside world only through the NAT gateway on port 443.
flowchart TB
    internet(["Internet clients"]) --> alb

    subgraph vpc["VPC"]
        subgraph pub["Public subnets"]
            alb["Application Load Balancer<br/>listener :80, plus :443 if a certificate is set"]
            nat["NAT gateway + Elastic IP"]
        end
        subgraph priv["Private subnets"]
            direction LR
            t1["ECS Fargate task<br/>gateway"]
            t2["ECS Fargate task<br/>gateway"]
        end
        alb -->|"security group: ALB to tasks only"| t1
        alb --> t2
        t1 -->|"egress 443 only"| nat
        t2 --> nat
    end

    nat --> out(["Outbound: AWS APIs and provider endpoints"])

    subgraph support["Supporting resources"]
        direction LR
        ecr[("ECR repository<br/>lifecycle policy")]
        logs["CloudWatch log group<br/>JSON logs from stdout"]
        asg["App Auto Scaling<br/>target tracking on CPU"]
        iam["IAM task execution role<br/>and task role"]
    end
    support -. "image pull, logs, scaling, permissions" .-> priv

    subgraph alarms["Monitoring"]
        direction LR
        al["CloudWatch alarms<br/>ALB 5xx, p95 latency,<br/>unhealthy hosts, CPU high"] --> sns["SNS topic"] --> mail["Email subscription"]
    end
    alb -. "metrics" .-> al
    priv -. "metrics" .-> al
```

[SVG](04-aws-deployment.svg) · [source](04-aws-deployment.mmd)

## Delivery pipeline (GitHub Actions)

.github/workflows/ai-reliability-platform.yml at the repository root. The three jobs run on every push to main and pull request touching this project; the image job waits for tests. Only a tag named ai-reliability-platform-vX.Y.Z publishes to GHCR.

```mermaid
%% title: Delivery pipeline (GitHub Actions)
%% caption: .github/workflows/ai-reliability-platform.yml at the repository root. The three jobs run on every push to main and pull request touching this project; the image job waits for tests. Only a tag named ai-reliability-platform-vX.Y.Z publishes to GHCR.
flowchart LR
    trigger(["push to main or pull request<br/>paths: this project"])

    subgraph test["Job: test"]
        direction TB
        t1["ruff check + format"] --> t2["unittest: unit + end-to-end"] --> t3["validate_configs.py<br/>rules, dashboards, k8s hardening"] --> t4["docker compose config"]
    end

    subgraph tf["Job: terraform"]
        direction TB
        f1["fmt -check"] --> f2["init -backend=false"] --> f3["validate"]
    end

    subgraph img["Job: image (needs test)"]
        direction TB
        i1["Build image"] --> i2["Trivy image scan<br/>HIGH/CRITICAL fails the build"] --> i3["Trivy config scan<br/>report only"]
    end

    tag{"Tag ai-reliability-platform-v*?"}
    release["Push to GHCR<br/>with provenance + SBOM"]
    done(["Merge allowed"])

    trigger --> test
    trigger --> tf
    test --> img
    img --> tag
    tag -- yes --> release --> done
    tag -- no --> done
    tf --> done
```

[SVG](05-delivery-pipeline.svg) · [source](05-delivery-pipeline.mmd)
