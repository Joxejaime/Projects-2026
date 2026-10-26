# 02 · AWS platform with Terraform / OpenTofu

Infrastructure as code for running the container from project 01 on AWS: a multi-AZ VPC, ECS Fargate
behind an Application Load Balancer, autoscaling, alarms, and a pipeline that plans on pull requests and
applies only through a protected environment, authenticated with short-lived OIDC credentials.

![AWS architecture](docs/schematics/02a-aws-architecture.svg)

<sub>Source: [`02a-aws-architecture.mmd`](docs/schematics/02a-aws-architecture.mmd) · [all schematics](docs/schematics/README.md)</sub>


![Plan and apply flow with OIDC](docs/schematics/02b-terraform-delivery.svg)

<sub>Source: [`02b-terraform-delivery.mmd`](docs/schematics/02b-terraform-delivery.mmd) · [all schematics](docs/schematics/README.md)</sub>


## Layout
```
bootstrap/        one-time: encrypted, versioned S3 state bucket + GitHub OIDC roles
modules/network/  VPC, public/private subnets across 2-3 AZs, NAT (shared or per-AZ), flow logs
modules/ecs-service/  cluster, task def, ALB, security groups, autoscaling, alarms, IAM
envs/dev/         cheap: 1 task, shared NAT, HTTP allowed
envs/prod/        resilient: 3 AZs, NAT per AZ, HTTPS-only (ACM cert required), deletion protection
scripts/check_wiring.py   static module-wiring checker that needs no provider download
```

## What it demonstrates
- **Reusable modules with validated inputs** (CIDR must be /16, image can't be `:latest`, AZ count 2-3).
- **Environment parity with deliberate differences** in `envs/` rather than copy-pasted modules.
- **Secure defaults:** tasks in private subnets with no public IPs; task security group accepts only the
  ALB; ALB drops invalid headers; default security group locked down; TLS 1.3 policy; flow logs;
  state bucket versioned, encrypted, public-access-blocked, TLS-only; non-root, read-only-rootfs container.
- **Safe delivery:** circuit-breaker rollback on failed deployments, autoscaling that owns the replica
  count (`ignore_changes`), separate task *execution* and *task* roles (task role starts empty).
- **Keyless CI auth:** GitHub OIDC; the plan role is read-only, the apply role can only be assumed by
  jobs that target a protected GitHub Environment. The apply policy has no default on purpose.
- **Native S3 state locking** (`use_lockfile`), so no DynamoDB table to run.

## Use it
```bash
# 1. state bucket + OIDC roles (once, with admin credentials)
cd bootstrap
tofu init && tofu apply -var state_bucket_name=<unique> -var github_repository=<you>/<repo> \
  -var 'apply_policy_arns=["arn:aws:iam::<account>:policy/<scoped-policy>"]'

# 2. an environment
cd ../envs/dev
cp backend.hcl.example backend.hcl && cp terraform.tfvars.example terraform.tfvars   # edit both
tofu init -backend-config=backend.hcl
tofu plan && tofu apply
curl "$(tofu output -raw url)/healthz"
# tear down: tofu destroy   (dev only; prod has deletion protection)
```
Cost note: the NAT gateway and ALB bill hourly even when idle. Use `dev` for experiments and destroy it
afterwards. Check current AWS pricing before leaving anything running.

## Verification status
| Check | Status |
|---|---|
| `tofu fmt -check` (parses all HCL) | Run: pass |
| `scripts/check_wiring.py` (arguments match module variables, required vars supplied, outputs exist) | Run: pass; also proven to catch 4 injected mistakes |
| `tofu init` / `validate` / `plan` / `apply`, TFLint, Checkov | **Not run yet.** The provider registry was unreachable from the build environment. CI runs `validate`, TFLint and Checkov on every PR (Checkov is report-only until you triage its first findings); run `plan` yourself before relying on this. |
| Applied to a real AWS account | **No.** Nothing here has been deployed. Treat the first `plan` as the real test and expect to fix small provider-schema details. |

## Next improvements
Remote module versioning, per-environment IAM boundary for the apply role, WAF on the ALB, Secrets
Manager integration for the task, a Route 53 + ACM module, cost estimation (Infracost) in PRs, and
`terraform test` for the modules.
