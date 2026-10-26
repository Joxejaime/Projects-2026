# One-time bootstrap: creates the S3 bucket that stores remote state for the
# environments. Run once with local state, then keep the (tiny) local state file
# safe or migrate it into the bucket it created.

terraform {
  required_version = ">= 1.11.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "devops-portfolio"
      ManagedBy = "terraform"
      Component = "state-bootstrap"
    }
  }
}

variable "region" {
  description = "AWS region for the state bucket."
  type        = string
  default     = "us-east-1"
}

variable "state_bucket_name" {
  description = "Globally unique name for the Terraform state bucket."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{2,62}$", var.state_bucket_name))
    error_message = "Bucket name must be 3-63 chars: lowercase letters, numbers, dots and hyphens."
  }
}

resource "aws_s3_bucket" "state" {
  # Triaged Checkov findings (single-account state bucket; versioning, SSE, public-access-block and
  # TLS-only access are in place). Revisit each if this bucket ever holds more than one team's state.
  #checkov:skip=CKV_AWS_18:Access logging needs a second log bucket; state access is already audited in CloudTrail
  #checkov:skip=CKV_AWS_144:Cross-region replication doubles cost; versioning covers accidental deletion for a portfolio account
  #checkov:skip=CKV_AWS_145:SSE-S3 (AES256) is enabled; a customer-managed KMS key adds cost and a key-policy dependency for the apply role
  #checkov:skip=CKV2_AWS_62:No consumer for bucket event notifications
  bucket = var.state_bucket_name

  # State is the source of truth for real infrastructure: never delete it by accident.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "tls_only" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.state.arn,
      "${aws_s3_bucket.state.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = data.aws_iam_policy_document.tls_only.json

  depends_on = [aws_s3_bucket_public_access_block.state]
}

output "state_bucket" {
  description = "Use this as the bucket in each environment's backend.hcl."
  value       = aws_s3_bucket.state.id
}
