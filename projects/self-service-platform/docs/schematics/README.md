# Schematics: self-service-platform

Diagrams are Mermaid, so GitHub renders them inline below. Each also has a rendered `.svg` next to its
`.mmd` source. Edit the `.mmd` file, then run `python3 scripts/build_schematics.py` from the repository root.

## The golden path

From a developer's request to a running, compliant service. Generating and validating a repository are implemented and tested here. The pull request, terraform plan, approval and apply half is the intended workflow, generated as files but not exercised end to end.

```mermaid
%% title: The golden path
%% headline: One command to a compliant service
%% takeaway: platformctl generates the repo, a policy check gates it, Terraform provisions the environment.
%% legend: entry=Developer,app=Generated files,guard=Policy and review,data=Pull request,cloud=Terraform,ok=Provisioned
%% caption: From a developer's request to a running, compliant service. Generating and validating a repository are implemented and tested here. The pull request, terraform plan, approval and apply half is the intended workflow, generated as files but not exercised end to end.
flowchart TB
    dev(["Developer<br/>platformctl new orders-api<br/>--owner team-orders --tier standard"])
    gen["Generated repository<br/>service.yaml, app and tests, Dockerfile<br/>Kubernetes manifests, CI workflow<br/>CODEOWNERS, runbook"]
    pol{{"platformctl validate<br/>policy check"}}
    fix["Fix the findings<br/>each has a rule ID"]
    tfenv["platformctl env add<br/>orders-api prod<br/>writes Terraform"]
    pr["Pull request"]
    plan["CI: terraform plan"]
    approve["Platform engineer<br/>approves the apply"]
    live["ECR repository, deploy role,<br/>log group, budget"]
    dev --> gen --> pol
    pol -- errors --> fix --> pol
    pol -- passes --> pr
    dev -.-> tfenv --> pr
    pr --> plan --> approve --> live

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#0B3D1E
    classDef cloud fill:#FFEDD5,stroke:#EA580C,stroke-width:2.5px,color:#5A2300
    class dev entry
    class gen,tfenv app
    class pol,fix,approve guard
    class pr data
    class plan cloud
    class live ok
```

[SVG](01-golden-path.svg) · [source](01-golden-path.mmd)

## Policy-as-code validation

platformctl/policy.py. validate_repo reads service.yaml first (its tier sets the expectations), then checks each file type. Every finding has a stable ID. Errors fail the command (exit 1); warnings fail only with --strict. Policy values default to built-ins and can be overridden with --policy policies/default.yaml; unknown keys are rejected.

```mermaid
%% title: Policy-as-code validation
%% headline: Guardrails as code, each rule with a stable ID
%% takeaway: Spec, Kubernetes, Dockerfile and CI rules run on any repo. Errors fail the build.
%% legend: entry=Command,guard=Rules,data=Policy config and findings,alert=Fails,ok=Passes
%% caption: platformctl/policy.py. validate_repo reads service.yaml first (its tier sets the expectations), then checks each file type. Every finding has a stable ID. Errors fail the command (exit 1); warnings fail only with --strict. Policy values default to built-ins and can be overridden with --policy policies/default.yaml; unknown keys are rejected.
flowchart TB
    repo(["platformctl validate PATH"]) --> specrules["service.yaml<br/>SPEC001-SPEC010<br/>required fields, name, owner team-*,<br/>tier, port, replicas, SLO"]
    specrules --> krules["Kubernetes manifests<br/>K8S001-K8S011<br/>pinned image tag, allowed registry,<br/>resource limits, non-root,<br/>no privilege escalation, probes,<br/>replicas at least tier minimum, labels"]
    specrules --> drules["Dockerfile<br/>DOCK001-DOCK003<br/>non-root USER, pinned base image,<br/>HEALTHCHECK"]
    specrules --> wrules["CI workflows<br/>CI001-CI002<br/>permissions block,<br/>pinned action versions"]
    pol["policies/default.yaml<br/>allowed registries, required labels,<br/>minimum replicas by tier"] -.-> krules
    krules --> out["Findings<br/>text or JSON"]
    drules --> out
    wrules --> out
    out --> exit{{"Errors, or warnings<br/>with --strict?"}}
    exit -- yes --> bad(["exit 1"])
    exit -- no --> good(["exit 0"])

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#0B3D1E
    class repo entry
    class specrules,krules,drules,wrules,exit guard
    class pol,out data
    class bad alert
    class good ok
```

[SVG](02-policy-engine.svg) · [source](02-policy-engine.mmd)

## Reliability tiers

A tier is the only reliability choice a developer makes; defaults for replicas, resources, SLO and disruption budget follow from it (platformctl/models.py TIER_DEFAULTS). The K8S009 rule rejects manifests with fewer replicas than the tier minimum.

```mermaid
%% title: Reliability tiers
%% headline: One choice, the reliability tier, sets the defaults
%% takeaway: critical, standard or best-effort decides replicas, resources, SLO and disruption budget.
%% legend: entry=Developer choice,cloud=critical,app=standard,neutral=best-effort,data=Generated defaults
%% caption: A tier is the only reliability choice a developer makes; defaults for replicas, resources, SLO and disruption budget follow from it (platformctl/models.py TIER_DEFAULTS). The K8S009 rule rejects manifests with fewer replicas than the tier minimum.
flowchart TB
    pick["service.yaml<br/>tier: critical, standard or best-effort"]
    crit["critical<br/>3 replicas, SLO 99.95%<br/>disruption budget: 2 always up<br/>CPU 250m-1000m, memory 256-512Mi"]
    std["standard<br/>2 replicas, SLO 99.9%<br/>disruption budget: 1 always up<br/>CPU 100m-500m, memory 128-256Mi"]
    be["best-effort<br/>1 replica, SLO 99.0%<br/>no disruption budget<br/>CPU 50m-250m, memory 64-128Mi"]
    out["Generated Deployment and PDB<br/>K8S009 enforces the replica minimum"]
    pick --> crit
    pick --> std
    pick --> be
    crit --> out
    std --> out
    be --> out

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef cloud fill:#FFEDD5,stroke:#EA580C,stroke-width:2.5px,color:#5A2300
    classDef neutral fill:#F1F5F9,stroke:#64748B,stroke-width:2.5px,color:#0F172A
    class pick entry
    class crit cloud
    class std app
    class be neutral
    class out data
```

[SVG](03-reliability-tiers.svg) · [source](03-reliability-tiers.mmd)

## Terraform service-environment module

terraform/modules/service-environment. One module call per service and environment (generated by platformctl env add). The deploy role trusts GitHub's OIDC provider, so there are no long-lived AWS keys; prod can only be assumed from a GitHub environment (which can require reviewers), lower environments from main or release tags. All resources carry service, environment, owner, tier and ManagedBy tags. The budget is created only when alert emails are set. Written and statically reviewed, not applied.

```mermaid
%% title: Terraform service-environment module
%% headline: Deploying with no long-lived AWS keys
%% takeaway: A GitHub OIDC role scoped to one ECR repository, with prod locked to a reviewed environment.
%% legend: entry=GitHub job,guard=Trust check,app=Deploy role,cloud=AWS resource,alert=Prod subject,ok=Dev and staging subject
%% caption: terraform/modules/service-environment. One module call per service and environment (generated by platformctl env add). The deploy role trusts GitHub's OIDC provider, so there are no long-lived AWS keys; prod can only be assumed from a GitHub environment (which can require reviewers), lower environments from main or release tags. All resources carry service, environment, owner, tier and ManagedBy tags. The budget is created only when alert emails are set. Written and statically reviewed, not applied.
flowchart TB
    gh(["GitHub Actions job<br/>presents an OIDC token"])
    prod["prod: only from the<br/>GitHub environment 'prod'"]
    low["dev, staging: from main<br/>or release tags v*"]
    trust{{"Trust policy:<br/>does the token subject match?"}}
    role["IAM deploy role<br/>push images to this ECR repository only"]
    subgraph res["Created by the module"]
        ecr[("ECR repository<br/>immutable tags, scan on push")]
        logs["CloudWatch log group<br/>configurable retention"]
        budget["Monthly AWS Budget<br/>email alert at 80%"]
    end
    gh --> trust
    prod -.-> trust
    low -.-> trust
    trust -- matches --> role
    role --> ecr
    role -.-> logs
    role -.-> budget

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#0B3D1E
    classDef cloud fill:#FFEDD5,stroke:#EA580C,stroke-width:2.5px,color:#5A2300
    class gh entry
    class trust guard
    class role app
    class ecr,logs,budget cloud
    class prod alert
    class low ok
    style res fill:#FFFBEB,stroke:#FCD34D,stroke-width:2px,color:#92400E
```

[SVG](04-terraform-module.svg) · [source](04-terraform-module.mmd)

## Service catalog

platformctl/catalog.py. The catalog is built by scanning a directory of service.yaml files and running the same validation on each; a duplicate service name is CAT001. The command exits 1 if any service has an error, so it can gate CI.

```mermaid
%% title: Service catalog
%% headline: A service catalog that validates as it lists
%% takeaway: Scan every service.yaml, validate each one, and publish markdown or JSON. Errors fail CI.
%% legend: entry=Input,app=Processing,data=Outputs,guard=Check,alert=Fails,ok=Passes
%% caption: platformctl/catalog.py. The catalog is built by scanning a directory of service.yaml files and running the same validation on each; a duplicate service name is CAT001. The command exits 1 if any service has an error, so it can gate CI.
flowchart TB
    svcs["Directory of services<br/>each with a service.yaml"] --> collect["catalog.collect"]
    collect --> val["Validate each service<br/>plus duplicate-name check CAT001"]
    val --> md["catalog.md<br/>service, owner, tier, SLO,<br/>replicas, environments, spec path"]
    val --> js["catalog.json"]
    val --> rc{{"Any errors?"}}
    rc -- yes --> r1(["exit 1"])
    rc -- no --> r0(["exit 0"])

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#0B3D1E
    class svcs entry
    class collect,val app
    class md,js data
    class rc guard
    class r1 alert
    class r0 ok
```

[SVG](05-service-catalog.svg) · [source](05-service-catalog.mmd)
