# GitHub Actions authenticates to AWS with short-lived OIDC tokens: there are no
# long-lived access keys stored in GitHub secrets.

variable "github_repository" {
  description = "owner/repo allowed to assume the pipeline roles, e.g. Joxejaime/devops-portfolio."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must look like owner/repo."
  }
}

variable "apply_policy_arns" {
  description = <<-EOT
    Managed or customer policy ARNs for the APPLY role. Deliberately has no default:
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

    # Pull requests and branches of this repo may PLAN (read-only).
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:*"]
    }
  }
}

data "aws_iam_policy_document" "apply_trust" {
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

    # Only jobs that target a protected GitHub Environment may APPLY.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:environment:*"]
    }
  }
}

data "aws_iam_policy_document" "state_access" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.state.arn]
  }

  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.state.arn}/*"]
  }
}

resource "aws_iam_role" "plan" {
  name                 = "portfolio-gha-plan"
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
  policy = data.aws_iam_policy_document.state_access.json
}

resource "aws_iam_role" "apply" {
  name                 = "portfolio-gha-apply"
  assume_role_policy   = data.aws_iam_policy_document.apply_trust.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "apply" {
  for_each = toset(var.apply_policy_arns)

  role       = aws_iam_role.apply.name
  policy_arn = each.value
}

resource "aws_iam_role_policy" "apply_state" {
  name   = "state-access"
  role   = aws_iam_role.apply.id
  policy = data.aws_iam_policy_document.state_access.json
}

output "plan_role_arn" {
  description = "Set as repository variable AWS_PLAN_ROLE_ARN."
  value       = aws_iam_role.plan.arn
}

output "apply_role_arn" {
  description = "Set as repository variable AWS_APPLY_ROLE_ARN."
  value       = aws_iam_role.apply.arn
}
