terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }

  # Partial configuration: supply bucket/key/region with
  #   tofu init -backend-config=backend.hcl   (see backend.hcl.example)
  # use_lockfile gives native S3 state locking: no DynamoDB table needed.
  backend "s3" {}
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "devops-portfolio"
      Environment = "dev"
      ManagedBy   = "terraform"
    }
  }
}

locals {
  name         = "release-tracker-dev"
  https_scheme = (var.certificate_arn == null ? "http" : "https")
}

module "network" {
  source = "../../modules/network"

  name               = local.name
  cidr_block         = "10.20.0.0/16"
  az_count           = 2
  single_nat_gateway = true
}

module "service" {
  source = "../../modules/ecs-service"

  name               = local.name
  vpc_id             = module.network.vpc_id
  public_subnet_ids  = module.network.public_subnet_ids
  private_subnet_ids = module.network.private_subnet_ids

  image         = var.image
  desired_count = 1
  min_capacity  = 1
  max_capacity  = 2

  certificate_arn            = null
  alb_ingress_cidrs          = var.alb_ingress_cidrs
  enable_deletion_protection = false
  log_retention_days         = 14
  alarm_sns_topic_arn        = aws_sns_topic.alerts.arn

  environment_variables = {
    APP_VERSION = var.app_version
  }
}

# --- Alerting target ---------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count = var.alert_email == null ? 0 : 1

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# --- Inputs / outputs --------------------------------------------------------

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "image" {
  description = "Image to deploy, pinned by tag or digest (the CI pipeline in project 01 publishes sha tags)."
  type        = string
}

variable "app_version" {
  description = "Value reported in the app_info metric."
  type        = string
  default     = "unknown"
}

variable "alb_ingress_cidrs" {
  description = "CIDRs allowed to reach the load balancer. Narrow this for dev."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "alert_email" {
  description = "Optional email for alarm notifications (needs manual confirmation from the inbox)."
  type        = string
  default     = null
}

variable "certificate_arn" {
  description = "Optional ACM certificate ARN. Leave null for HTTP-only dev."
  type        = string
  default     = null
}

output "url" {
  value = "${local.https_scheme}://${module.service.alb_dns_name}"
}

output "cluster_name" {
  value = module.service.cluster_name
}

output "service_name" {
  value = module.service.service_name
}

output "nat_public_ips" {
  value = module.network.nat_public_ips
}
