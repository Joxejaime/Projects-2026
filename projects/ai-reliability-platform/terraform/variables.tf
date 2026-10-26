variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (used in resource names and tags)."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "name" {
  description = "Base name for resources."
  type        = string
  default     = "ai-gateway"
}

variable "image_tag" {
  description = "Immutable image tag to deploy (for example a git SHA). Never use 'latest'."
  type        = string

  validation {
    condition     = var.image_tag != "latest" && length(var.image_tag) > 0
    error_message = "image_tag must be a specific, immutable tag, not 'latest'."
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
  description = "Baseline number of tasks (also the autoscaling minimum)."
  type        = number
  default     = 2
}

variable "max_count" {
  description = "Autoscaling maximum."
  type        = number
  default     = 6
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "az_count" {
  description = "Number of availability zones to spread across."
  type        = number
  default     = 2
}

variable "allowed_ingress_cidrs" {
  description = "CIDR blocks allowed to reach the load balancer."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "certificate_arn" {
  description = "ACM certificate ARN. When set, HTTPS is enabled and HTTP redirects to it; when empty the ALB serves plain HTTP (dev only)."
  type        = string
  default     = ""
}

variable "alarm_email" {
  description = "Optional e-mail address subscribed to the alarm SNS topic."
  type        = string
  default     = ""
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "gateway_env" {
  description = "Extra GATEWAY_* environment variables for the container. Do not put secrets here."
  type        = map(string)
  default     = {}
}
