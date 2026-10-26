# Snapshot storage for the recovery tools (`BACKUP_STORE=s3://<bucket>/<prefix>`): a private, encrypted, versioned
# bucket. The writer policy can add and read snapshots but cannot delete them, and versioning keeps overwritten
# objects for `noncurrent_retention_days`, so a compromised or buggy backup job cannot destroy the backups.
#
# NOT APPLIED to any AWS account. CI runs terraform fmt, init -backend=false, validate and TFLint on it.

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
}

variable "region" {
  type        = string
  description = "AWS region for the bucket."
  default     = "us-east-1"
}

variable "bucket_name" {
  type        = string
  description = "Globally unique name for the snapshot bucket."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.bucket_name))
    error_message = "bucket_name must be 3-63 characters of lowercase letters, digits, dots and hyphens."
  }
}

variable "retention_days" {
  type        = number
  description = "Days before a snapshot object expires. Keep this above your snapshot interval times the number of snapshots you want to be able to fall back to."
  default     = 35

  validation {
    condition     = var.retention_days >= 7
    error_message = "retention_days must be at least 7."
  }
}

variable "noncurrent_retention_days" {
  type        = number
  description = "Days an overwritten or deleted version is kept before it is removed."
  default     = 30

  validation {
    condition     = var.noncurrent_retention_days >= 7
    error_message = "noncurrent_retention_days must be at least 7."
  }
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to the bucket."
  default     = {}
}

# Accepted trade-offs for a portfolio account, in the same spirit as project 02's Checkov triage: no access
# logging, cross-region replication or KMS key (SSE-S3, versioning and the public access block are on).
#checkov:skip=CKV_AWS_18:Access logging needs a second bucket; accepted for a portfolio account
#checkov:skip=CKV_AWS_144:Cross-region replication is the multi-region step this project deliberately defers
#checkov:skip=CKV_AWS_145:SSE-S3 is used instead of a customer KMS key to avoid key cost and policy surface
#checkov:skip=CKV2_AWS_62:Event notifications are not needed for backups
resource "aws_s3_bucket" "backups" {
  bucket = var.bucket_name
  tags   = var.tags
}

resource "aws_s3_bucket_ownership_controls" "backups" {
  bucket = aws_s3_bucket.backups.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "backups" {
  bucket = aws_s3_bucket.backups.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id

  rule {
    id     = "expire-old-snapshots"
    status = "Enabled"

    filter {}

    expiration {
      days = var.retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.backups]
}

data "aws_iam_policy_document" "tls_only" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    resources = [
      aws_s3_bucket.backups.arn,
      "${aws_s3_bucket.backups.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "tls_only" {
  bucket = aws_s3_bucket.backups.id
  policy = data.aws_iam_policy_document.tls_only.json

  depends_on = [aws_s3_bucket_public_access_block.backups]
}

# Attach to the role the backup job and the responder run as. No s3:DeleteObject on purpose.
data "aws_iam_policy_document" "snapshot_writer" {
  statement {
    sid       = "ListSnapshots"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.backups.arn]
  }

  statement {
    sid       = "ReadAndWriteSnapshots"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.backups.arn}/*"]
  }
}

output "bucket_name" {
  value = aws_s3_bucket.backups.id
}

output "bucket_arn" {
  value = aws_s3_bucket.backups.arn
}

output "snapshot_writer_policy_json" {
  description = "IAM policy for the snapshot job and the responder: list, read and add snapshots, never delete."
  value       = data.aws_iam_policy_document.snapshot_writer.json
}
