locals {
  name = "${var.service}-${var.environment}"

  tags = {
    Service     = var.service
    Environment = var.environment
    Owner       = var.owner
    Tier        = var.tier
    ManagedBy   = "platformctl"
  }

  # Production deploys must go through a GitHub *environment* (with required reviewers);
  # lower environments may deploy from main and from release tags.
  oidc_subjects = var.environment == "prod" ? [
    "repo:${var.github_repo}:environment:prod",
    ] : [
    "repo:${var.github_repo}:ref:refs/heads/main",
    "repo:${var.github_repo}:ref:refs/tags/v*",
  ]
}

# --- Container registry ----------------------------------------------------------------
resource "aws_ecr_repository" "this" {
  name                 = local.name
  image_tag_mutability = "IMMUTABLE"
  force_delete         = var.environment != "prod"
  tags                 = local.tags

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 30 most recent images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 30 }
      action       = { type = "expire" }
    }]
  })
}

# --- Logs ------------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "this" {
  name              = "/apps/${local.name}"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

# --- CI/CD identity: GitHub Actions assumes this role via OIDC (no long-lived keys) ------
data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = local.oidc_subjects
    }
  }
}

resource "aws_iam_role" "deploy" {
  name                 = "${local.name}-deploy"
  assume_role_policy   = data.aws_iam_policy_document.assume.json
  max_session_duration = 3600
  tags                 = local.tags
}

# Least privilege: push images to *this* service's repository only.
data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPushOwnRepository"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [aws_ecr_repository.this.arn]
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "ecr-push"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}

# --- Cost guardrail ----------------------------------------------------------------------
# Requires the `Service` cost-allocation tag to be activated in the billing console.
resource "aws_budgets_budget" "this" {
  count        = length(var.budget_alert_emails) > 0 ? 1 : 0
  name         = local.name
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = [format("user:Service$%s", var.service)]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.budget_alert_emails
  }
}
