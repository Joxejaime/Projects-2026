# GitHub-side setup

The Terraform in `bootstrap/` creates the IAM roles and decides **which GitHub Environment**
may assume each one. It cannot decide **which branch** may deploy to that environment, because
the OIDC token for an environment job does not carry the branch:

```
repo:Joxejaime/devops-portfolio:environment:prod      # what AWS sees
repo:Joxejaime/devops-portfolio:ref:refs/heads/main   # what a branch job sends instead
```

A job gets one subject or the other, never both. So the two halves live in two places, and
**the IAM half is worthless on its own**:

| Control | Where it lives | Stops |
|---|---|---|
| Only the `prod` environment may assume the prod role | IAM trust policy (`bootstrap/github-oidc.tf`) | A job that targets some other environment |
| Only `main` may deploy to `prod` | GitHub Environment → deployment branches | A feature branch dispatching an apply |
| A human approves before apply | GitHub Environment → required reviewers | An unreviewed apply |
| Nobody pushes to `main` directly | Branch protection on `main` | Bypassing review entirely |

Skip the second row and the first is close to decorative: anyone able to run a workflow can
target `prod` from any branch.

## 1. Create the environments

**Settings → Environments → New environment**, once for `dev` and once for `prod`. The names
must match the `environments` list in `bootstrap/` exactly — the trust policies name them
with `StringEquals` and no wildcard, so a typo means `AssumeRoleWithWebIdentity` is denied.

> Creating them by hand matters. A workflow can bring an environment into existence just by
> naming it, and one created that way has **no** protection rules. That is why the trust
> policy no longer accepts `environment:*`.

## 2. Protect each environment

Inside each environment:

- **Deployment branches and tags** → *Selected branches* → add `main`. This is the "apply only
  from main" rule. Without it the environment accepts a dispatch from any branch.
- **Required reviewers** → add yourself. On a solo repository this is a deliberate pause
  before anything reaches AWS, not bureaucracy.
- For `prod`, consider a **wait timer** of a few minutes, so a mistaken dispatch can be cancelled.

## 3. Give each environment its own role ARN

`terraform output apply_role_arns` prints one ARN per environment:

```
{ "dev" = "arn:aws:iam::…:role/portfolio-gha-apply-dev",
  "prod" = "arn:aws:iam::…:role/portfolio-gha-apply-prod" }
```

Add `AWS_APPLY_ROLE_ARN` as a variable **inside each environment**, set to that environment's
ARN. Do not set it as a repository variable: an environment variable shadows the repository
one, so a repository-wide value would hand every environment the same role and undo the split.

Repository-level variables (**Settings → Secrets and variables → Actions → Variables**):

| Variable | Value |
|---|---|
| `AWS_PLAN_ROLE_ARN` | `terraform output plan_role_arn` |
| `AWS_REGION` | your region, e.g. `us-east-1` |
| `TF_STATE_BUCKET` | the bucket from `bootstrap/` |

## 4. Protect `main`

**Settings → Branches → Add branch ruleset** (or classic branch protection) for `main`:

- Require a pull request before merging
- Require status checks to pass — select the `00 - Supply chain guard` job and the checks for
  whichever components you want blocking
- Block force pushes, and do not allow deletions

Without this, every other control above can be walked around by committing straight to `main`.

## What this does and does not buy you

It means a deploy to `prod` requires a pull request into `main`, passing checks, a reviewer on
the environment, and an AWS role that only that environment can assume, with short-lived
credentials and no stored keys.

It does **not** make the apply role safe by itself. Scope `apply_policy_arns` to the services
this stack manages rather than `AdministratorAccess`; the variable has no default on purpose.
And none of this has been applied to a real AWS account yet, so treat the first `plan` as the
real test.
