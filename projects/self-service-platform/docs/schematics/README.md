# Schematics: self-service-platform

Diagrams are Mermaid, so GitHub renders them inline below. Each also has a rendered `.svg` next to its
`.mmd` source. Edit the `.mmd` file, then run `python3 scripts/build_schematics.py` from the repository root.

## The golden path

From a developer's request to a running, compliant service. Generating and validating a repository are implemented and tested here. The pull request, terraform plan, approval and apply half is the intended workflow, generated as files but not exercised end to end.

```mermaid
%% title: The golden path
%% caption: From a developer's request to a running, compliant service. Generating and validating a repository are implemented and tested here. The pull request, terraform plan, approval and apply half is the intended workflow, generated as files but not exercised end to end.
flowchart LR
    dev(["Developer"]) -->|"platformctl new orders-api<br/>--owner team-orders --tier standard"| gen["Generated repository<br/>service.yaml, app/ and tests/<br/>Dockerfile: non-root, pinned base<br/>k8s/deployment.yaml: Deployment, Service, PDB<br/>CI workflow: pinned actions, least privilege<br/>CODEOWNERS, docs/runbook.md"]
    gen -->|"platformctl validate ."| pol{"Policy check<br/>passes?"}
    pol -- "errors" --> fix["Fix the listed<br/>rule IDs"]
    fix --> pol
    pol -- yes --> pr["Pull request"]
    dev -->|"platformctl env add<br/>orders-api prod"| tfenv["infra/services/<br/>orders-api-prod.tf"]
    tfenv --> pr
    pr --> plan["CI: terraform plan"] --> approve["Platform engineer<br/>approves apply"] --> live["ECR repo, deploy role,<br/>log group, budget"]
```

[SVG](01-golden-path.svg) · [source](01-golden-path.mmd)

## Policy-as-code validation

platformctl/policy.py. validate_repo reads service.yaml first (its tier sets the expectations), then checks each file type. Every finding has a stable ID. Errors fail the command (exit 1); warnings fail only with --strict. Policy values default to built-ins and can be overridden with --policy policies/default.yaml; unknown keys are rejected.

```mermaid
%% title: Policy-as-code validation
%% caption: platformctl/policy.py. validate_repo reads service.yaml first (its tier sets the expectations), then checks each file type. Every finding has a stable ID. Errors fail the command (exit 1); warnings fail only with --strict. Policy values default to built-ins and can be overridden with --policy policies/default.yaml; unknown keys are rejected.
flowchart TD
    repo(["platformctl validate PATH"]) --> spec{"service.yaml<br/>present?"}
    spec -- no --> s0["SPEC000 error: stop"]
    spec -- yes --> specrules["Spec rules SPEC001-SPEC010<br/>required fields, unknown keys, name,<br/>owner team-*, tier, port, replicas, language, SLO"]

    specrules --> k["k8s/*.yaml"]
    specrules --> d["Dockerfile"]
    specrules --> w[".github/workflows/*.yml"]

    k --> krules["K8S001 pinned image tag<br/>K8S002 allowed registry<br/>K8S003 resource requests/limits<br/>K8S004 runAsNonRoot<br/>K8S005 no privilege escalation<br/>K8S006 read-only root FS warn<br/>K8S007 readinessProbe<br/>K8S008 not privileged, no host access<br/>K8S009 replicas >= tier minimum<br/>K8S010 required labels<br/>K8S011 livenessProbe warn"]
    d --> drules["DOCK001 non-root USER<br/>DOCK002 pinned base image<br/>DOCK003 HEALTHCHECK warn<br/>DOCK000 missing file warn"]
    w --> wrules["CI001 permissions block warn<br/>CI002 action version pin"]

    krules --> out
    drules --> out
    wrules --> out
    out["Findings list<br/>(text or --format json)"] --> exit{"Any errors?<br/>or warnings with --strict?"}
    exit -- yes --> bad(["exit 1"])
    exit -- no --> good(["exit 0"])

    pol["policies/default.yaml<br/>allowed registries, required labels,<br/>min replicas by tier"] -.-> krules
```

[SVG](02-policy-engine.svg) · [source](02-policy-engine.mmd)

## Reliability tiers and the service catalog

A tier is the only reliability choice a developer makes; defaults for replicas, resources, SLO and disruption budget follow from it (platformctl/models.py TIER_DEFAULTS). The catalog is built by scanning a directory of service.yaml files and running the same validation on each; a duplicate service name is CAT001.

```mermaid
%% title: Reliability tiers and the service catalog
%% caption: A tier is the only reliability choice a developer makes; defaults for replicas, resources, SLO and disruption budget follow from it (platformctl/models.py TIER_DEFAULTS). The catalog is built by scanning a directory of service.yaml files and running the same validation on each; a duplicate service name is CAT001.
flowchart LR
    subgraph tiers["Tier defaults"]
        direction TB
        crit["critical<br/>3 replicas<br/>SLO 99.95%<br/>PDB min available 2<br/>cpu 250m-1000m, mem 256-512Mi"]
        std["standard<br/>2 replicas<br/>SLO 99.9%<br/>PDB min available 1<br/>cpu 100m-500m, mem 128-256Mi"]
        be["best-effort<br/>1 replica<br/>lighter resources"]
    end

    svcs["Directory of services<br/>each with service.yaml"] --> collect["catalog.collect"]
    collect --> val["validate each service<br/>plus duplicate-name check"]
    val --> md["catalog.md<br/>table: service, owner, tier, SLO,<br/>replicas, environments, spec path"]
    val --> js["catalog.json"]
    val --> rc{"Any errors?"}
    rc -- yes --> r1(["exit 1"])
    rc -- no --> r0(["exit 0"])

    tiers -. "tier minimums are enforced by<br/>the replica rule K8S009" .-> val
```

[SVG](03-tiers-and-catalog.svg) · [source](03-tiers-and-catalog.mmd)

## Terraform service-environment module

terraform/modules/service-environment. One module call per service and environment (generated by platformctl env add). The deploy role trusts GitHub's OIDC provider, so there are no long-lived AWS keys; prod can only be assumed from a GitHub environment (which can require reviewers), lower environments from main or release tags. Written and statically reviewed, not applied.

```mermaid
%% title: Terraform service-environment module
%% caption: terraform/modules/service-environment. One module call per service and environment (generated by platformctl env add). The deploy role trusts GitHub's OIDC provider, so there are no long-lived AWS keys; prod can only be assumed from a GitHub environment (which can require reviewers), lower environments from main or release tags. Written and statically reviewed, not applied.
flowchart TB
    gh(["GitHub Actions job"]) -->|"OIDC token<br/>sts:AssumeRoleWithWebIdentity"| trust

    subgraph mod["module.service_environment"]
        direction TB
        trust{"Trust policy:<br/>token sub claim matches?"}
        role["IAM deploy role<br/>+ inline policy"]
        ecr[("ECR repository<br/>immutable tags, scan on push,<br/>lifecycle policy")]
        logs["CloudWatch log group<br/>retention from variable<br/>for the service to write to"]
        budget["AWS Budget, only if alert emails are set<br/>monthly USD limit, filtered by Service tag,<br/>email notification at 80%"]
        trust -- yes --> role
    end

    subgraph subs["Allowed token subjects"]
        prod["prod: repo:ORG/REPO:environment:prod"]
        low["dev / staging: refs/heads/main<br/>and refs/tags/v*"]
    end
    subs -.-> trust

    role -->|"least privilege: push images<br/>to this ECR repository only"| ecr
    tags["Tags on all resources:<br/>service, environment, owner, tier,<br/>ManagedBy=platformctl"] -.-> mod
```

[SVG](04-terraform-module.svg) · [source](04-terraform-module.mmd)
