# DevOps & Cloud portfolio — Jaime Castillo Araujo

[![01 Secure CI/CD](https://github.com/Joxejaime/Projects-2026/actions/workflows/01-secure-cicd.yml/badge.svg?branch=main)](https://github.com/Joxejaime/Projects-2026/actions/workflows/01-secure-cicd.yml)
[![02 Terraform platform](https://github.com/Joxejaime/Projects-2026/actions/workflows/02-terraform.yml/badge.svg?branch=main)](https://github.com/Joxejaime/Projects-2026/actions/workflows/02-terraform.yml)
[![03 Kubernetes GitOps](https://github.com/Joxejaime/Projects-2026/actions/workflows/03-k8s-gitops.yml/badge.svg?branch=main)](https://github.com/Joxejaime/Projects-2026/actions/workflows/03-k8s-gitops.yml)
[![04 Observability](https://github.com/Joxejaime/Projects-2026/actions/workflows/04-observability.yml/badge.svg?branch=main)](https://github.com/Joxejaime/Projects-2026/actions/workflows/04-observability.yml)
[![05 AI reliability](https://github.com/Joxejaime/Projects-2026/actions/workflows/05-ai-reliability-platform.yml/badge.svg?branch=main)](https://github.com/Joxejaime/Projects-2026/actions/workflows/05-ai-reliability-platform.yml)
[![06 Self-service platform](https://github.com/Joxejaime/Projects-2026/actions/workflows/06-self-service-platform.yml/badge.svg?branch=main)](https://github.com/Joxejaime/Projects-2026/actions/workflows/06-self-service-platform.yml)
[![07 SRE lab](https://github.com/Joxejaime/Projects-2026/actions/workflows/07-sre-reliability-lab.yml/badge.svg?branch=main)](https://github.com/Joxejaime/Projects-2026/actions/workflows/07-sre-reliability-lab.yml)
[![08 DR autopilot](https://github.com/Joxejaime/Projects-2026/actions/workflows/08-disaster-recovery-autopilot.yml/badge.svg?branch=main)](https://github.com/Joxejaime/Projects-2026/actions/workflows/08-disaster-recovery-autopilot.yml)

**Eight projects covering the path from a commit to a service running in production and being kept alive:
secure delivery, infrastructure as code, GitOps, observability, incident practice, and disaster recovery.**

Every project is self-contained — its own tests, docs, runbooks, diagrams and CI workflow — and every README
ends with a **Verification status** table that separates what was actually run from what was not.

> **New here? Start with [`projects/00-start-here`](projects/00-start-here).** It explains how the projects
> relate, what to read first, and what each one proves.

---

## The projects

Read them in order, or jump to the one that matches the role you have in mind.

### Projects 01–04 · one service, end to end

Four connected projects that follow a single small service, `release-tracker`, from commit to on-call.
They are meant to be read together: 02 to 04 use the image or the `/metrics` endpoint produced by 01.

| # | Project | What it shows | Core tools |
|---|---|---|---|
| 01 | [Secure CI/CD pipeline](projects/01-secure-cicd-pipeline) | A pipeline that refuses to ship a vulnerable image: lint, test, build, scan, SBOM, publish by digest, keyless signature and provenance | GitHub Actions, Docker, Trivy, gitleaks, cosign, GHCR |
| 02 | [AWS platform with Terraform](projects/02-aws-terraform-platform) | Multi-AZ VPC and ECS Fargate behind an ALB, dev and prod, plan on PR and gated apply with no stored cloud keys | Terraform, ECS, ALB, IAM OIDC, TFLint, Checkov |
| 03 | [Kubernetes GitOps](projects/03-k8s-gitops) | Promotion by pull request, Pod Security `restricted`, default-deny networking, and a tested policy checker | Kustomize, Argo CD, kubeconform, policy-as-code |
| 04 | [Observability and SLOs](projects/04-observability-slo) | Multi-window burn-rate alerting with unit-tested rules, routing, dashboards as code, runbooks and a game day | Prometheus, Alertmanager, Grafana, promtool |

### Projects 05–08 · deeper dives

Four independent projects, each going further into one theme. Nothing here imports anything from the series.

| # | Project | What it shows | Core tools |
|---|---|---|---|
| 05 | [AI reliability platform](projects/05-ai-reliability-platform) | An AI-backed service that keeps answering when a provider fails: retries, circuit breaker, fallback, per-tenant limits, plus a measured outage drill | Python, Docker, Kubernetes, Terraform, Prometheus |
| 06 | [Self-service platform](projects/06-self-service-platform) | A paved road: one command generates a compliant service, a policy engine checks any repo against rule IDs, and a catalog tracks what exists | Python, Jinja2, Terraform, Kubernetes, OIDC |
| 07 | [SRE reliability lab](projects/07-sre-reliability-lab) | Reliability as numbers: one SLO file generates the alert rules, an incident simulator replays failures, and chaos runs produce game-day reports | Python, Prometheus, Alertmanager, chaos experiments |
| 08 | [Disaster recovery autopilot](projects/08-disaster-recovery-autopilot) | When something breaks: alert opens an incident, a playbook restores and verifies, RTO/RPO are checked, and a postmortem draft is written automatically | Python, Alertmanager webhooks, backup/restore, GitHub Issues |

Projects 01 and 04 overlap in topic with 05 and 07, but are independent of them.

---

## What is proven, and what is not

Being precise about this is deliberate: nothing below is claimed unless it has been run.

| Project | Checks that have run | Where |
|---|---|---|
| 01 | Lint, 15 unit tests, hadolint, gitleaks, image build, container smoke test, Trivy gate, SBOM, GHCR publish by digest, cosign keyless signature, provenance attestation | GitHub Actions |
| 02 | `fmt`, module wiring check, `init` + `validate` for bootstrap/dev/prod, TFLint, Checkov (21 findings triaged) | GitHub Actions |
| 03 | `kustomize build`, strict kubeconform validation, policy checks on both overlays, 13 policy tests | GitHub Actions |
| 04 | Generated-file drift check, promtool config and rule checks, 8 alert-rule scenarios, amtool, compose validation; one real end-to-end alert run | GitHub Actions, local |
| 05 | 40 unit and end-to-end tests, image build and scan, Terraform checks; provider-outage drill | GitHub Actions, local |
| 06 | 29 tests, scaffold → validate → generated-tests round trip, Terraform checks | GitHub Actions |
| 07 | Lint, SLO validation, 33 tests including live chaos experiments, promtool rule checks | GitHub Actions |
| 08 | Lint, playbook validation, 35 tests, two disaster-recovery drills (restore succeeds; corrupt backups refused and escalated) with their postmortem drafts committed | Local; CI workflow added, first run pending |

**Not proven anywhere yet:** applying any Terraform to a real AWS account, an Argo CD sync on a real cluster,
Grafana rendering the dashboard, the Docker Compose stacks, and `cosign verify` against the published image.
[`projects/00-start-here/docs/PORTFOLIO-GUIDE.md`](projects/00-start-here/docs/PORTFOLIO-GUIDE.md) is the plan
for converting each of those into evidence.

---

## How the repository is organized

```
projects-2026/
├── projects/
│   ├── 00-start-here/                  guide to all eight, end-to-end diagram, evidence
│   ├── 01-secure-cicd-pipeline/        release-tracker service, Dockerfile, CI/CD with scan, SBOM, signing
│   ├── 02-aws-terraform-platform/      Terraform modules (network, ECS service), dev/prod, OIDC bootstrap
│   ├── 03-k8s-gitops/                  Kustomize overlays, Argo CD apps, policy checker
│   ├── 04-observability-slo/           burn-rate rules, Alertmanager, Grafana, runbooks, game day
│   ├── 05-ai-reliability-platform/     gateway app, tests, k8s, terraform, observability, drill report
│   ├── 06-self-service-platform/       platformctl, policies, terraform module, examples, catalog
│   ├── 07-sre-reliability-lab/         slogen, chaos runner, demo service, observability, game days
│   └── 08-disaster-recovery-autopilot/ drpilot responder, recovery playbooks, drills, postmortem drafts
├── .github/workflows/                  one workflow per project (0N-*.yml), path-filtered to its folder
├── assets/linkedin/                    1080x1350 cards and a PDF carousel per project (none yet for 08)
└── scripts/                            diagram rendering, card building, offline verification
```

Each project folder follows the same shape: `README.md`, `docs/` (including `docs/schematics/`), the code, and
its tests. GitHub only runs workflows from the repository root, so each pipeline lives in
`.github/workflows/0N-<project>.yml` with a `paths:` filter and that project folder as its working directory.

Run every offline check for projects 00 to 04:

```bash
./scripts/verify-devops-series.sh
```

## Schematics

Diagrams are Mermaid so GitHub renders them inline, with a plain-SVG export beside each source. Colour means
role (client, service, protection, observability, alert, success, cloud) and each diagram carries its own
legend. To change one, edit its `.mmd` file and run:

```bash
python3 scripts/build_schematics.py     # needs mermaid-cli (mmdc)
python3 scripts/build_cards.py          # needs Playwright with Chromium and the Inter font
```

`assets/linkedin/<project>/` holds a cover card, one card per schematic and a closing card, plus
`<project>-carousel.pdf` for a swipeable LinkedIn document post.

## Placeholders still to replace

The image registry defaults to `ghcr.io/joxejaime` and example repositories point at `Joxejaime/...`. One
placeholder remains: the `@example-org/<team>` handle in the `CODEOWNERS` template of project 06. GitHub team
handles only exist in a GitHub organization, so use your org there, or `@Joxejaime` on a personal account.

## License

MIT, see each project's `LICENSE`.
