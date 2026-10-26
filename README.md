# projects-2026

Three DevOps / SRE projects that together follow one engineering lifecycle: **application, infrastructure,
delivery, observability, incident handling and recovery**. Each is self-contained (its own tests, docs, runbooks
and CI workflow) and has schematics explaining how it works.

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
| [`self-service-platform`](projects/self-service-platform) | A paved road: one command generates a compliant service, a policy engine checks any repo against rule IDs, a catalog tracks services, and a Terraform module provisions an environment without long-lived credentials. | [README](projects/self-service-platform/README.md) | [4 diagrams](projects/self-service-platform/docs/schematics/README.md) |
| [`sre-reliability-lab`](projects/sre-reliability-lab) | Reliability stated as numbers: one SLO file generates multi-window burn-rate alerts, an incident simulator replays failures through them, and a chaos runner rehearses faults and writes game-day reports. | [README](projects/sre-reliability-lab/README.md) | [5 diagrams](projects/sre-reliability-lab/docs/schematics/README.md) |

## How the repository is organized

```
projects-2026/
├── projects/
│   ├── ai-reliability-platform/    app, tests, k8s, terraform, observability, docs, schematics
│   ├── self-service-platform/      platformctl, policies, terraform module, examples, docs, schematics
│   └── sre-reliability-lab/        slogen, chaos runner, demo service, observability, game days, schematics
├── .github/workflows/              one CI workflow per project, triggered only by changes under its folder
├── scripts/build_schematics.py     renders every docs/schematics/*.mmd to SVG and rebuilds the schematics READMEs
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
Workflow paths were adapted for this layout and have not yet run on GitHub.

## Placeholders still to replace

The image registry defaults to `ghcr.io/joxejaime` and example repositories point at `Joxejaime/...`. One placeholder
remains: the `@example-org/<team>` handle in the `CODEOWNERS` template of `self-service-platform`. GitHub team handles
only exist in a GitHub organization, so use your org there, or `@Joxejaime` on a personal account.

## Schematics

Diagrams are written in Mermaid so GitHub renders them inline, with a plain-SVG export next to each source.
To change one, edit its `.mmd` file and run:

```bash
python3 scripts/build_schematics.py     # needs mermaid-cli (mmdc)
```

## License

MIT, see each project's `LICENSE`.
