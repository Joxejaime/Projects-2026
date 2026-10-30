# GitHub Actions authenticates to AWS with short-lived OIDC tokens: there are no
# long-lived access keys stored in GitHub secrets.
#
# The subject claim is the whole security boundary here, so it is matched exactly.
# An earlier version trusted `repo:<owner>/<repo>:environment:*`, which looks restrictive
# but is not: a workflow can create an environment simply by naming it, and a brand new
# environment has no protection rules. Any job on any branch could therefore mint
# `environment:anything` and assume the apply role. Each environment now gets its own role
# whose trust policy names that one environment with StringEquals and no wildcard.
#
# The environment name is only half of it. The subject for an environment job does not carry
# the branch, so "apply only from main" cannot be expressed here: it is a deployment-branch
# rule on the GitHub Environment itself. See docs/github-setup.md — both halves are required.

variable "github_repository" {
  description = "owner/repo allowed to assume the pipeline roles, e.g. Joxejaime/devops-portfolio."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must look like owner/repo."
  }
}

variable "environments" {
  description = <<-EOT
    GitHub Environment names that may apply. One IAM role is created per entry, trusting only
    that environment. Keep this list to environments that actually exist and are protected.
  EOT
  type        = list(string)
  default     = ["dev", "prod"]

  validation {
    condition     = length(var.environments) > 0 && alltrue([for e in var.environments : can(regex("^[A-Za-z0-9_-]+$", e))])
    error_message = "environments must be a non-empty list of simple names (no wildcards)."
  }
}

variable "apply_policy_arns" {
  description = <<-EOT
    Managed or customer policy ARNs for the APPLY roles. Deliberately has no default:
    scope this to the services the stack manages (EC2/VPC, ECS, ELB, IAM roles with a
    path/boundary, CloudWatch, SNS, Logs) instead of AdministratorAccess.
  EOT
  type        = list(string)
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

# --- Trust policies ----------------------------------------------------------------------

# The plan job runs only on pull_request, so the subject is exactly that. Anything wider would
# let a job on an arbitrary branch assume a role that can read every resource in the account.
data "aws_iam_policy_document" "plan_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:pull_request"]
    }
  }
}

# One trust policy per environment, each naming exactly one environment.
data "aws_iam_policy_document" "apply_trust" {
  for_each = toset(var.environments)

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:environment:${each.value}"]
    }
  }
}

# --- State access ------------------------------------------------------------------------

# Plan must read state and take the lock, nothing more. The previous policy gave plan
# s3:DeleteObject over the whole bucket, so a read-only role could have destroyed the state
# it was only meant to read. Writes are now confined to the lock object.
data "aws_iam_policy_document" "state_access_plan" {
  statement {
    sid       = "ListStateBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.state.arn]
  }

  statement {
    sid       = "ReadState"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.state.arn}/*"]
  }

  statement {
    sid       = "TakeAndReleaseTheLockOnly"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.state.arn}/*.tflock"]
  }
}

# Apply writes new state versions, so it needs the object itself. Versioning on the bucket is
# what makes an accidental overwrite recoverable.
data "aws_iam_policy_document" "state_access_apply" {
  statement {
    sid       = "ListStateBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.state.arn]
  }

  statement {
    sid       = "ReadAndWriteState"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.state.arn}/*"]
  }
}

# --- Roles -------------------------------------------------------------------------------

resource "aws_iam_role" "plan" {
  name                 = "portfolio-gha-plan"
  description          = "Read-only plan role. Assumable only by pull_request jobs of ${var.github_repository}."
  assume_role_policy   = data.aws_iam_policy_document.plan_trust.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "plan_readonly" {
  role       = aws_iam_role.plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

resource "aws_iam_role_policy" "plan_state" {
  name   = "state-access"
  role   = aws_iam_role.plan.id
  policy = data.aws_iam_policy_document.state_access_plan.json
}

resource "aws_iam_role" "apply" {
  for_each = toset(var.environments)

  name                 = "portfolio-gha-apply-${each.value}"
  description          = "Apply role for the '${each.value}' environment of ${var.github_repository} only."
  assume_role_policy   = data.aws_iam_policy_document.apply_trust[each.value].json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "apply" {
  for_each = {
    for pair in setproduct(var.environments, var.apply_policy_arns) :
    "${pair[0]}|${pair[1]}" => { env = pair[0], arn = pair[1] }
  }

  role       = aws_iam_role.apply[each.value.env].name
  policy_arn = each.value.arn
}

resource "aws_iam_role_policy" "apply_state" {
  for_each = toset(var.environments)

  name   = "state-access"
  role   = aws_iam_role.apply[each.key].id
  policy = data.aws_iam_policy_document.state_access_apply.json
}

# --- Outputs -----------------------------------------------------------------------------

output "plan_role_arn" {
  description = "Set as the repository variable AWS_PLAN_ROLE_ARN."
  value       = aws_iam_role.plan.arn
}

output "apply_role_arns" {
  description = <<-EOT
    One ARN per environment. Set each as the variable AWS_APPLY_ROLE_ARN *inside* the matching
    GitHub Environment, not as a repository variable: an environment variable shadows the
    repository one, so each environment then receives only its own role.
  EOT
  value       = { for env, role in aws_iam_role.apply : env => role.arn }
}
