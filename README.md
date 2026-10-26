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

## What is proven, and what is not

Nothing here is claimed unless it has been run. Each component README ends with its own
**Verification status** table.

| Component | Checks that have run | Where |
|---|---|---|
| [01](projects/01-secure-cicd-pipeline) Secure CI/CD | Lint, 15 unit tests, hadolint, gitleaks, image build, container smoke test, Trivy gate, SBOM, GHCR publish by digest, cosign keyless signature, provenance attestation | GitHub Actions |
| [02](projects/02-aws-terraform-platform) AWS platform | `fmt`, module wiring check, `init` + `validate` for bootstrap/dev/prod, TFLint, Checkov (21 findings triaged) | GitHub Actions |
| [03](projects/03-k8s-gitops) Kubernetes GitOps | `kustomize build`, strict kubeconform validation, policy checks on both overlays, 13 policy tests | GitHub Actions |
| [04](projects/04-observability-slo) Observability | Drift check, promtool config and rule checks, 8 alert-rule scenarios, amtool, compose validation; one real end-to-end alert run | GitHub Actions, local |
| [05](projects/05-ai-reliability-platform) AI reliability | 40 unit and end-to-end tests, image build and scan, Terraform checks; provider-outage drill | GitHub Actions, local |
| [06](projects/06-self-service-platform) Developer platform | 29 tests, scaffold → validate → generated-tests round trip, Terraform checks | GitHub Actions |
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

**Not proven anywhere yet:** applying any Terraform to a real AWS account, an Argo CD sync on a real cluster,
Grafana rendering the dashboard, the Docker Compose stacks, and `cosign verify` against the published image.
[`projects/00-start-here/docs/PORTFOLIO-GUIDE.md`](projects/00-start-here/docs/PORTFOLIO-GUIDE.md) is the plan
for turning each of those into evidence.

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
├── assets/linkedin/                    1080x1350 cards and carousel PDFs built from the diagrams
└── scripts/                            diagram rendering, card building, offline verification
```

GitHub only runs workflows from the repository root, so each pipeline lives in
`.github/workflows/0N-<component>.yml` with a `paths:` filter and that folder as its working directory.

Run every offline check for components 00 to 04:

```bash
./scripts/verify-devops-series.sh
```

## Diagrams

Written in Mermaid so GitHub renders them inline, with a plain-SVG export beside each source. Colour means
role (client, service, protection, observability, alert, success, cloud) and each diagram carries a legend.
To change one, edit its `.mmd` file and run:

```bash
python3 scripts/build_schematics.py     # needs mermaid-cli (mmdc)
python3 scripts/build_cards.py          # needs Playwright with Chromium and the Inter font
```

## License

MIT, see each component's `LICENSE`.
