# projects-2026

Three DevOps / SRE projects that together follow one engineering lifecycle: **application, infrastructure,
delivery, observability, incident handling and recovery**. Each is self-contained (its own tests, docs, runbooks
and CI workflow) and has schematics explaining how it works.

A second group, the **DevOps delivery series** (projects `01` to `04`, below), is four connected projects that follow one service
from commit to on-call.

| Lifecycle stage | ai-reliability-platform | self-service-platform | sre-reliability-lab |
|---|---|---|---|
| Application | LLM gateway with resilience patterns | Generated service skeleton with tests | Demo service with fault injection |
| Infrastructure | Docker, Kubernetes, Terraform on AWS | Terraform service-environment module | Docker Compose monitoring stack |
| Delivery | CI with image scan, provenance and SBOM | Generated CI workflow per service | CI that fails on stale generated alert rules |
| Observability | Metrics, dashboard, SLO burn-rate alerts | Service catalog, SLO per tier | SLOs as code, generated alert rules, routing |
| Incident handling | Runbooks, postmortem template, outage drill | Generated runbook per service | Game-day playbook, runbooks, chaos runs |
| Recovery | Circuit closes after provider recovers | Not covered | Recovery measured after each fault |

The projects are independent: nothing in one imports or depends on another. See the table below for what each one is.

| Project | What it shows | Start here | Schematics |
|---|---|---|---|
| [`ai-reliability-platform`](projects/ai-reliability-platform) | An AI-backed service that keeps answering when a provider fails, protects itself from noisy tenants, and reports honestly on its health. App, Docker, Kubernetes, Terraform on AWS, CI, SLO alerts, runbooks, measured failure drill. | [README](projects/ai-reliability-platform/README.md) | [5 diagrams](projects/ai-reliability-platform/docs/schematics/README.md) |
| [`self-service-platform`](projects/self-service-platform) | A paved road: one command generates a compliant service, a policy engine checks any repo against rule IDs, a catalog tracks services, and a Terraform module provisions an environment without long-lived credentials. | [README](projects/self-service-platform/README.md) | [5 diagrams](projects/self-service-platform/docs/schematics/README.md) |
| [`sre-reliability-lab`](projects/sre-reliability-lab) | Reliability stated as numbers: one SLO file generates multi-window burn-rate alerts, an incident simulator replays failures through them, and a chaos runner rehearses faults and writes game-day reports. | [README](projects/sre-reliability-lab/README.md) | [5 diagrams](projects/sre-reliability-lab/docs/schematics/README.md) |

## DevOps delivery series (projects 01 to 04)

Four connected projects around one small service, `release-tracker`: ship it securely, run it on AWS, deploy it
with GitOps, and watch it against SLOs. Unlike the three projects above, these are meant to be read together:
02 to 04 use the image or the `/metrics` endpoint produced by 01. Start with the
[overview and end-to-end diagram](projects/00-devops-series-overview/README.md).

| Project | What it shows | Start here | Schematics |
|---|---|---|---|
| [`01-secure-cicd-pipeline`](projects/01-secure-cicd-pipeline) | A pipeline that lints, tests, builds, scans, produces an SBOM, publishes by digest and signs the image with cosign. Hardened container, probes, metrics, graceful shutdown. | [README](projects/01-secure-cicd-pipeline/README.md) | [2 diagrams](projects/01-secure-cicd-pipeline/docs/schematics/README.md) |
| [`02-aws-terraform-platform`](projects/02-aws-terraform-platform) | OpenTofu modules for a multi-AZ VPC and ECS Fargate behind an ALB, dev and prod environments, plan on pull request and gated apply with GitHub OIDC (no stored keys). | [README](projects/02-aws-terraform-platform/README.md) | [2 diagrams](projects/02-aws-terraform-platform/docs/schematics/README.md) |
| [`03-k8s-gitops`](projects/03-k8s-gitops) | Kustomize overlays and Argo CD: promotion by pull request, Pod Security `restricted`, default-deny network policy, and a policy checker with tests that prove it rejects bad manifests. | [README](projects/03-k8s-gitops/README.md) | [2 diagrams](projects/03-k8s-gitops/docs/schematics/README.md) |
| [`04-observability-slo`](projects/04-observability-slo) | Prometheus burn-rate alerts with unit tests, Alertmanager routing and inhibition, a generated Grafana dashboard, runbooks, and a recorded end-to-end alert run. | [README](projects/04-observability-slo/README.md) | [3 diagrams](projects/04-observability-slo/docs/schematics/README.md) |

Run all of their offline checks with `./scripts/verify-devops-series.sh`. Each project README has a verification table;
results of their GitHub Actions workflows (`01-` to `04-` in `.github/workflows/`) are recorded there once they have run.
Projects 01 and 04 overlap in topic with `ai-reliability-platform` and `sre-reliability-lab`, but are independent of them.

## How the repository is organized

```
projects-2026/
├── projects/
│   ├── ai-reliability-platform/    app, tests, k8s, terraform, observability, docs, schematics
│   ├── self-service-platform/      platformctl, policies, terraform module, examples, docs, schematics
│   └── sre-reliability-lab/        slogen, chaos runner, demo service, observability, game days, schematics
│   ├── 00-devops-series-overview/  overview diagram, guide to turning the series into proof, test evidence
│   ├── 01-secure-cicd-pipeline/    release-tracker service, Dockerfile, CI/CD with scan, SBOM and signing
│   ├── 02-aws-terraform-platform/  OpenTofu modules (network, ECS service), dev/prod, OIDC bootstrap
│   ├── 03-k8s-gitops/              Kustomize overlays, Argo CD apps, policy checker
│   └── 04-observability-slo/       burn-rate rules, Alertmanager, Grafana, runbooks, game day
├── .github/workflows/              one CI workflow per project, triggered only by changes under its folder
├── assets/linkedin/                1080x1350 cards and a PDF carousel per project, built from the schematics
├── scripts/build_schematics.py     renders every docs/schematics/*.mmd to SVG and rebuilds the schematics READMEs
│                                   (optionally only for the project names given as arguments)
├── scripts/verify-devops-series.sh offline checks for projects 00 to 04
├── scripts/build_cards.py          builds the LinkedIn cards and carousel PDFs from those schematics
└── push.sh                         publishes this repository to GitHub
```

GitHub only runs workflows from the repository root, so each project's pipeline lives in
`.github/workflows/<project>.yml` with a `paths:` filter and its project folder as the working directory.

## What has and has not been verified

Each project README has its own verified / not-verified table. In short:

| Run and passing in the build environment | Written but never run there |
|---|---|
| Unit and end-to-end tests of all three projects, lint, config validation | Docker image builds and `docker compose up` (no Docker daemon was available) |
| The failure drill, game days and incident simulator, whose results are recorded in the docs | `terraform validate` / `apply` for all Terraform |
| Generated artefacts: scaffolded services pass the policy check; generated alert rules match the SLO file | Prometheus evaluating the rules and alerts firing live; Kubernetes manifests applied to a cluster |

The CI workflows in `.github/workflows/` run the missing checks (Terraform, `promtool`, image scan) on first push.
The four DevOps-series workflows (01 to 04) have run on GitHub and pass; see each project's Verification status. The workflows of the earlier projects were adapted for this layout and have not been re-checked here.

## Placeholders still to replace

The image registry defaults to `ghcr.io/joxejaime` and example repositories point at `Joxejaime/...`. One placeholder
remains: the `@example-org/<team>` handle in the `CODEOWNERS` template of `self-service-platform`. GitHub team handles
only exist in a GitHub organization, so use your org there, or `@Joxejaime` on a personal account.

## Schematics

Diagrams are written in Mermaid so GitHub renders them inline, with a plain-SVG export next to each source.
Colour means role (client, service, protection, observability, alert, success, cloud) and each diagram carries
its own legend. To change one, edit its `.mmd` file and run:

```bash
python3 scripts/build_schematics.py     # needs mermaid-cli (mmdc)
python3 scripts/build_cards.py          # needs Playwright with Chromium and the Inter font
```

`assets/linkedin/<project>/` holds a cover card, one card per schematic and a closing card (PNG, 1080x1350 at 2x),
plus `<project>-carousel.pdf` with all of them in order for a swipeable LinkedIn document post.

## License

MIT, see each project's `LICENSE`.
