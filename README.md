# DevOps & Cloud portfolio — Jaime Castillo Araujo

**Three projects covering the path from a commit to a service running in production, staying up under
failure, and recovering with evidence.** Built as eight self-contained components, each with its own tests,
docs, diagrams and CI pipeline — all eight run on GitHub Actions and pass.

`Terraform` `Kubernetes` `AWS` `GitHub Actions` `Docker` `Prometheus` `Argo CD` `Python`

---

## 1 · [Delivery platform](showcase/1-delivery-platform.md)

One service followed from a commit to an on-call page. A pipeline that refuses to ship a vulnerable image,
a multi-AZ AWS platform deployed without stored cloud keys, GitOps promotion by pull request, and error-budget
SLO alerting with runbooks.

*The Trivy gate failed its first real run on four fixable HIGH CVEs in the base image — the fix was removing
the package installers and flattening the runtime so the scanned image is exactly the image that runs.*

`GitHub Actions` `Docker` `Trivy` `cosign` `Terraform` `ECS Fargate` `IAM OIDC` `Kustomize` `Argo CD` `Prometheus`
→ components [01](projects/01-secure-cicd-pipeline) · [02](projects/02-aws-terraform-platform) · [03](projects/03-k8s-gitops) · [04](projects/04-observability-slo)

## 2 · [Reliability and recovery](showcase/2-reliability-and-recovery.md)

Three answers to the same question: what happens when it breaks? A gateway that keeps serving through a
provider outage, a lab that states reliability as numbers and rehearses failure against them, and an autopilot
that drives recovery and drafts the postmortem from the timeline it observed.

*In a simulated total outage of the primary provider, all 180 requests still succeeded through the fallback.
A 5% error rate pages after 18 minutes, having spent 2.2% of the monthly error budget — and that delay is
defensible, not accidental.*

`Python` `Prometheus` `Alertmanager` `PostgreSQL` `chaos experiments` `circuit breakers` `SLOs`
→ components [05](projects/05-ai-reliability-platform) · [07](projects/07-sre-reliability-lab) · [08](projects/08-disaster-recovery-autopilot)

## 3 · [Developer platform](showcase/3-developer-platform.md)

A paved road: one command produces a production-shaped service that already satisfies every guardrail, and the
same rules audit any existing repository by rule ID.

*Every policy rule carries a mutation test that breaks one thing and expects the checker to name that rule.*

`Python` `Jinja2` `Terraform` `Kubernetes` `policy-as-code` `OIDC`
→ component [06](projects/06-self-service-platform)

---

## About me

I'm **Jaime Castillo Araujo**, based in Managua, Nicaragua.

I'm a DevOps and cloud engineer, and I've worked as a **freelance DevOps and cloud consultant since 2023**. I came
to it through production support: **Tech Support Specialist at Ibex**, supporting a point-of-sale SaaS platform,
promoted from Level 1 to Level 2 after a year.

That background is where this portfolio comes from. Time on the receiving end of outages teaches you which alerts
are worth waking someone for, why a runbook matters more than a dashboard, and how much of an incident is
communication rather than terminal commands. These projects are the next step: building the delivery pipelines,
the infrastructure and the recovery tooling that decide whether a support queue is calm or on fire.

### What I'm looking for

Open to **remote roles across Latin America**, not limited to Nicaragua.

- Junior DevOps Engineer / DevOps Engineer
- Junior Cloud Engineer / AWS Engineer
- Junior Platform or Infrastructure Engineer
- Junior SRE, where the role is about reliability engineering rather than the pager alone

I'm early in the DevOps side of my career and direct about it: this repository is deliberately explicit about
what has actually been run versus what has only been written. I'd rather be hired on what I can defend.

### How this was built

I build this with Claude Code, Anthropic's AI coding tool, under strong human oversight. Claude is the working
tool; the decisions, the review and the control are mine. I decide what gets built and what each component has to
prove, review the changes, check the repositories, decide what to fix or move, and run and debug the results. I keep
a human hand on security and control throughout. The results in the tables below come from checks that actually
ran, in GitHub Actions or locally. Anything not yet run is listed under "Not proven anywhere yet".

### Contact

| | |
|---|---|
| Email | [castilloajosejaime@gmail.com](mailto:castilloajosejaime@gmail.com) |
| GitHub | [@Joxejaime](https://github.com/Joxejaime) |
| LinkedIn | [jaime-castillo-araujo](https://www.linkedin.com/in/jaime-castillo-araujo) |
| Location | Managua, Nicaragua · open to remote across LatAm |

---

## What is proven, and what is not

Nothing here is claimed unless it has been run. Each component README ends with its own
**Verification status** table.

| Component | Checks that have run | Where |
|---|---|---|
| [01](projects/01-secure-cicd-pipeline) Secure CI/CD | Lint, 15 unit tests, hadolint, gitleaks, image build, container smoke test, Trivy gate, SBOM, GHCR publish by digest, cosign keyless signature, provenance attestation | GitHub Actions |
| [02](projects/02-aws-terraform-platform) AWS platform | `fmt`, module wiring check, `init` + `validate` for bootstrap/dev/prod, TFLint, Checkov (21 findings triaged) | GitHub Actions |
| [03](projects/03-k8s-gitops) Kubernetes GitOps | `kustomize build`, strict kubeconform validation, policy checks on both overlays, 15 policy tests | GitHub Actions |
| [04](projects/04-observability-slo) Observability | Drift check, promtool config and rule checks, 8 alert-rule scenarios, amtool, compose validation; one real end-to-end alert run | GitHub Actions, local |
| [05](projects/05-ai-reliability-platform) AI reliability | 40 unit and end-to-end tests, image build and scan, Terraform checks; provider-outage drill | GitHub Actions, local |
| [06](projects/06-self-service-platform) Developer platform | 32 tests, scaffold → validate → generated-tests round trip, Terraform checks | GitHub Actions |
| [07](projects/07-sre-reliability-lab) SRE lab | Lint, SLO validation, 33 tests including live chaos experiments, promtool rule checks | GitHub Actions |
| [08](projects/08-disaster-recovery-autopilot) DR autopilot | Lint, playbook validation, 85 pytest tests against a real PostgreSQL 16 server, three recovery drills with their postmortem drafts committed | GitHub Actions, local |

Live status of all eight pipelines:

[![01](https://github.com/Joxejaime/devops-portfolio/actions/workflows/01-secure-cicd.yml/badge.svg?branch=main)](https://github.com/Joxejaime/devops-portfolio/actions/workflows/01-secure-cicd.yml)
[![02](https://github.com/Joxejaime/devops-portfolio/actions/workflows/02-terraform.yml/badge.svg?branch=main)](https://github.com/Joxejaime/devops-portfolio/actions/workflows/02-terraform.yml)
[![03](https://github.com/Joxejaime/devops-portfolio/actions/workflows/03-k8s-gitops.yml/badge.svg?branch=main)](https://github.com/Joxejaime/devops-portfolio/actions/workflows/03-k8s-gitops.yml)
[![04](https://github.com/Joxejaime/devops-portfolio/actions/workflows/04-observability.yml/badge.svg?branch=main)](https://github.com/Joxejaime/devops-portfolio/actions/workflows/04-observability.yml)
[![05](https://github.com/Joxejaime/devops-portfolio/actions/workflows/05-ai-reliability-platform.yml/badge.svg?branch=main)](https://github.com/Joxejaime/devops-portfolio/actions/workflows/05-ai-reliability-platform.yml)
[![06](https://github.com/Joxejaime/devops-portfolio/actions/workflows/06-self-service-platform.yml/badge.svg?branch=main)](https://github.com/Joxejaime/devops-portfolio/actions/workflows/06-self-service-platform.yml)
[![07](https://github.com/Joxejaime/devops-portfolio/actions/workflows/07-sre-reliability-lab.yml/badge.svg?branch=main)](https://github.com/Joxejaime/devops-portfolio/actions/workflows/07-sre-reliability-lab.yml)
[![08](https://github.com/Joxejaime/devops-portfolio/actions/workflows/08-disaster-recovery-autopilot.yml/badge.svg?branch=main)](https://github.com/Joxejaime/devops-portfolio/actions/workflows/08-disaster-recovery-autopilot.yml)

### Measured: CI runs on `main`

| Pipeline | Runs | Passed | Typical duration |
|---|---|---|---|
| 01 Secure CI/CD | 3 | 2 | 1m 53s |
| 02 AWS platform (Terraform) | 3 | 3 | 35s |
| 03 Kubernetes GitOps | 3 | 3 | 24s |
| 04 Observability | 1 | 1 | 12s |
| 05 AI reliability | 3 | 3 | 1m 12s |
| 06 Developer platform | 3 | 3 | 21s |
| 07 SRE lab | 2 | 2 | 43s |
| 08 DR autopilot | 1 | 1 | 1m 16s |

Measured on 2026-10-26 from the GitHub Actions API: completed runs on `main`, duration from run start to last
update, typical = median of the passing runs. Pipelines only run when their own folder changes, so each has few
runs; the counts grow with every push. Nineteen runs, eighteen passed, and the one failure is in pipeline 01.

**Not proven anywhere yet:** applying any Terraform to a real AWS account, an Argo CD sync on a real cluster,
Grafana rendering the dashboard, the Docker Compose stacks, and `cosign verify` against the published image.
[`projects/00-start-here/docs/PORTFOLIO-GUIDE.md`](projects/00-start-here/docs/PORTFOLIO-GUIDE.md) is the plan
for turning each of those into evidence.

[`ENGINEERING-NOTES.md`](projects/00-start-here/docs/ENGINEERING-NOTES.md) writes up three problems from
building this where the reasoning mattered more than the patch — a Docker layer model that was wrong, a
lint rule worth suppressing on purpose, and a hardening pass Dependabot nearly reverted twice.

---

## Repository layout

The eight folders under `projects/` are the engineering record — one per component, each self-contained.
`showcase/` is the reading view that groups them into the three projects above.

```
devops-portfolio/
├── showcase/                           the three projects, as a reader meets them
├── projects/
│   ├── 00-start-here/                  detailed index, end-to-end diagram, evidence plan
│   ├── 01-secure-cicd-pipeline/        release-tracker service, Dockerfile, scan, SBOM, signing
│   ├── 02-aws-terraform-platform/      Terraform modules (network, ECS service), dev/prod, OIDC
│   ├── 03-k8s-gitops/                  Kustomize overlays, Argo CD apps, policy checker
│   ├── 04-observability-slo/           burn-rate rules, Alertmanager, Grafana, runbooks, game day
│   ├── 05-ai-reliability-platform/     gateway, resilience patterns, k8s, terraform, drill report
│   ├── 06-self-service-platform/       platformctl, policies, terraform module, catalog
│   ├── 07-sre-reliability-lab/         slogen, chaos runner, demo service, game days
│   └── 08-disaster-recovery-autopilot/ drpilot, playbooks, data checks, postmortem drafts
├── .github/workflows/                  one workflow per component, path-filtered to its folder
└── scripts/                            diagram rendering, offline verification
```

GitHub only runs workflows from the repository root, so each pipeline lives in
`.github/workflows/0N-<component>.yml` with a `paths:` filter and that folder as its working directory.

### Branches

| Branch | Role |
|---|---|
| `main` | Always releasable. Only changes that already passed on `staging` are promoted here. Images are published and signed from `main` only. |
| `staging` | Where changes land first. Tests, linting, security scans and integration checks run on every push and pull request. Dependabot opens its update PRs against it. |

Flow: work branch → pull request into `staging` → checks pass → merge → pull request `staging` → `main`.
Automated deployment to a live environment is not wired up yet: the Terraform apply is a manual, reviewer-gated
workflow run, and it will move onto `staging` once the first real AWS deployment has been done and documented.

Run every offline check for all projects:

```bash
./scripts/verify.sh
```

## Diagrams

Written in Mermaid so GitHub renders them inline, with a plain-SVG export beside each source. Colour means
role (client, service, protection, observability, alert, success, cloud) and each diagram carries a legend.
To change one, edit its `.mmd` file and run:

```bash
python3 scripts/build_schematics.py     # needs mermaid-cli (mmdc)
```

## License

MIT, see each component's `LICENSE`.
