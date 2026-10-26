# Turning this into proof

This repository is a strong starting point, but a recruiter is persuaded by **evidence you produced**.
Spend a weekend on the steps below; each one converts "written" into "demonstrated".

## 1. Publish it (already done for this repository)
The four projects live in this repository under `projects/01-...` to `projects/04-...`, with one workflow each in
`.github/workflows/0N-*.yml` (path-filtered, so they only run when their project changes).
1. Settings → Branches: protect `main` (require a pull request and passing checks).
2. Watch workflows 01 to 04 run. **Fix whatever fails**: that is normal and is itself good practice.
   (Workflow 02's `static` jobs run on every change; `plan` and `apply` stay skipped until you configure AWS.)
3. Add the green-check badges to the repository README once the workflows are passing.

## 2. Produce evidence (a few hours)
| Project | Do this | Capture |
|---|---|---|
| 01 | Push to `main`, let the pipeline publish | Screenshot of the passing run, the GHCR package, the Security tab scan, the SBOM artifact; `cosign verify` output |
| 02 | Apply `dev` in a personal AWS account with a budget alarm; `curl` the ALB; then `destroy` | Plan output, `curl` result, CloudWatch alarm, the destroy confirmation |
| 03 | `kind create cluster`, install Argo CD and ingress-nginx, apply `argocd/` | Argo CD UI synced/healthy, `kubectl get pods`, a rollback demo |
| 04 | `make up`, follow [`projects/04-observability-slo/docs/game-day.md`](../../04-observability-slo/docs/game-day.md) | Dashboard during the outage, alert in the sink log, a *real* filled-in postmortem |

Put real numbers (time to detect, time to recover, pipeline duration) in the READMEs only after you
measure them. Then update each "Verification status" table.

## 3. Resume bullets (edit to match what you really did and measured)
Use these as templates; fill the brackets with your own results or delete the clause.
- Built a CI/CD pipeline in GitHub Actions (lint, test, container build, Trivy scan, SBOM, cosign signing,
  provenance) that blocks HIGH/CRITICAL vulnerabilities before publish; [pipeline runs in X minutes].
- Authored reusable Terraform/OpenTofu modules for a multi-AZ AWS VPC and ECS Fargate service with ALB,
  autoscaling and alarms; replaced stored cloud keys with GitHub OIDC and environment-gated applies.
- Implemented GitOps delivery with Kustomize and Argo CD, with Pod Security `restricted`, default-deny
  NetworkPolicies and a tested policy-as-code checker enforcing hardening rules on rendered manifests.
- Designed SLOs and multi-window burn-rate alerting in Prometheus/Alertmanager with unit-tested alert rules,
  runbooks and a game day; [measured detection time of X minutes in a fault drill].

Do not list a bullet you cannot defend in an interview. Anything in the "Not run yet" rows stays out
until you have run it.

## 4. LinkedIn
- **Headline:** `DevOps / Cloud Engineer · CI/CD · Terraform · Kubernetes · Observability` (adjust to roles you target).
- **Featured:** pin the repository and one screenshot of a green pipeline or the SLO dashboard.
- **About (starter):** "I build and operate the path from commit to production: secure pipelines,
  infrastructure as code, GitOps delivery and SLO-based monitoring. My portfolio follows one service through
  all four, with tests and runbooks. I'm looking for a DevOps or cloud role where I can keep growing."

## 5. Interview talk tracks (2 minutes each)
For every project prepare: *the problem, two decisions and the trade-off behind each, one thing that
broke while building it, and what you would do next.*
- **01:** Why scan and sign by digest? Why fail only on fixable HIGH/CRITICAL? What does `permissions:` per job protect against?
- **02:** Shared vs per-AZ NAT (cost vs resilience)? Why OIDC instead of access keys? Why does the task role start with no permissions? What does `ignore_changes = [desired_count]` prevent?
- **03:** Why is prod sync manual while dev auto-syncs? What does a default-deny NetworkPolicy change? What does the policy checker catch that kubeconform cannot?
- **04:** Why burn rate instead of a fixed error threshold? Why two windows? Walk through the bug the unit tests found (ratio absent before the first 5xx).

## 6. Honest limitations to volunteer
Nothing here ran against production traffic; the app is intentionally small; the SLO targets are
illustrative; costs and timings on your account will differ. Saying this plainly reads as maturity.
