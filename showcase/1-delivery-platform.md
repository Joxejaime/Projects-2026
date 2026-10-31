# 1 · Delivery platform

**One service, `release-tracker`, followed from a commit to an on-call page.** It is built and signed by a
pipeline that refuses to ship a vulnerable image, runs on a multi-AZ AWS platform deployed without stored
cloud keys, reaches clusters only through reviewed pull requests, and is watched against error-budget SLOs.

Built from [01](../projects/01-secure-cicd-pipeline) · [02](../projects/02-aws-terraform-platform) ·
[03](../projects/03-k8s-gitops) · [04](../projects/04-observability-slo)

![End to end view](../projects/00-start-here/docs/schematics/00-end-to-end.svg)

## The four stages

| Stage | What it does | Decisions worth asking about |
|---|---|---|
| **Ship** · [01](../projects/01-secure-cicd-pipeline) | Lint, 15 unit tests, Dockerfile lint and secret scan on every pull request; image built and smoke-tested; Trivy fails the build on fixable HIGH or CRITICAL findings; SBOM per build; on `main` the image is published by digest, signed keylessly with cosign and given a provenance attestation | Why fail only on *fixable* findings; why sign the digest rather than the tag; least-privilege `permissions:` per job |
| **Run** · [02](../projects/02-aws-terraform-platform) | Terraform modules for a multi-AZ VPC and ECS Fargate behind an ALB, separate dev and prod, remote state with locking, plan on pull request and apply behind an environment approval using GitHub OIDC | One shared NAT gateway in dev against one per AZ in prod; OIDC instead of access keys; why the task role starts with no permissions |
| **Deploy** · [03](../projects/03-k8s-gitops) | Kustomize base with dev and prod overlays, Argo CD auto-syncing dev and waiting for a human on prod, Pod Security `restricted`, default-deny networking, and a policy checker with tests that prove it rejects bad manifests | Why dev self-heals but prod waits; rollback as a reverted pull request; mutation tests on every policy rule |
| **Observe** · [04](../projects/04-observability-slo) | Multi-window burn-rate alerts at 14.4x, 6x, 3x and 1x generated from one SLO file, Alertmanager routing and inhibition, dashboards as code, runbooks, a postmortem template and a game-day plan | Why two windows per alert; what inhibition prevents; why a runbook link rides on every page |

## What the pipeline caught

The Trivy gate failed its first real run on four fixable HIGH CVEs living inside `pip` and its bundled wheel in
the base image. Deleting the packages in a later layer was not enough — the scanner still read them from the
base layer. The final stage is now `FROM scratch` with the cleaned filesystem copied in, so the image that gets
scanned is exactly the image that runs. The gate stayed strict throughout.

A second failure was infrastructure, not security: the vulnerability database download rate-limited and the
step died with no explanation, because its stderr was discarded. It now retries, falls back to a second
mirror, and prints the real error.

## Proven

All four workflows run on GitHub and pass.

- **01** — lint, tests, hadolint, gitleaks, image build, container smoke test, Trivy gate, SBOM, GHCR publish by digest, cosign keyless signature, provenance attestation
- **02** — `fmt`, module wiring check, `init` and `validate` for bootstrap, dev and prod, TFLint, Checkov with its first 21 findings triaged and each skip justified in the code
- **03** — `kustomize build`, strict kubeconform validation, policy checks on both overlays, 15 policy tests
- **04** — generated-file drift check, promtool config and rule checks, 8 alert-rule scenarios, amtool, compose validation, plus one real end-to-end run where injected errors fired an alert that reached a webhook

## Not proven

Terraform has never been applied to a real AWS account; there has been no Argo CD sync on a real cluster;
Grafana has never rendered the dashboard; and `cosign verify` has not been run against the published image.
[The portfolio guide](../projects/00-start-here/docs/PORTFOLIO-GUIDE.md) is the plan for converting each of
those into evidence.
