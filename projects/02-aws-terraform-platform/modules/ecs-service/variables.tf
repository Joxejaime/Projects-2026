variable "name" {
  description = "Service name; used as a prefix for every resource."
  type        = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  description = "Subnets for the load balancer."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Subnets for the tasks (no public IPs)."
  type        = list(string)
}

variable "image" {
  description = "Container image including tag or digest, e.g. ghcr.io/owner/release-tracker@sha256:..."
  type        = string

  validation {
    condition     = !endswith(var.image, ":latest") && length(regexall("[:@]", var.image)) > 0
    error_message = "Pin the image to a version tag or digest; ':latest' and untagged images are not allowed."
  }
}

variable "container_port" {
  type    = number
  default = 8080
}

variable "cpu" {
  description = "Fargate task CPU units."
  type        = number
  default     = 256
}

variable "memory" {
  description = "Fargate task memory (MiB)."
  type        = number
  default     = 512
}

variable "desired_count" {
  type    = number
  default = 2
}

variable "min_capacity" {
  type    = number
  default = 2
}

variable "max_capacity" {
  type    = number
  default = 4
}

variable "cpu_target_percent" {
  description = "Target average CPU for autoscaling."
  type        = number
  default     = 60
}

variable "health_check_path" {
  type    = string
  default = "/healthz"
}

variable "environment_variables" {
  description = "Plain (non-secret) environment variables. Secrets belong in Secrets Manager/SSM, not here."
  type        = map(string)
  default     = {}
}

variable "certificate_arn" {
  description = "ACM certificate ARN. When set, the ALB serves HTTPS and redirects HTTP to HTTPS. When null, HTTP only (dev)."
  type        = string
  default     = null
}

variable "alb_ingress_cidrs" {
  description = "CIDRs allowed to reach the load balancer."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "enable_deletion_protection" {
  description = "Protect the ALB from accidental deletion (enable in prod)."
  type        = bool
  default     = false
}

variable "alarm_sns_topic_arn" {
  description = "Optional SNS topic notified by the CloudWatch alarms."
  type        = string
  default     = null
}
