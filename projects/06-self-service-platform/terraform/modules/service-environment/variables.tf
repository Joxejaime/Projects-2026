variable "service" {
  description = "Service name (DNS label), matches service.yaml."
  type        = string

  validation {
    condition     = can(regex("^[a-z]([-a-z0-9]{0,40}[a-z0-9])?$", var.service))
    error_message = "service must be a lowercase DNS label of at most 42 characters."
  }
}

variable "environment" {
  type = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod."
  }
}

variable "owner" {
  description = "Owning team, e.g. team-orders. Used for tagging and cost attribution."
  type        = string

  validation {
    condition     = can(regex("^team-[a-z][a-z0-9-]{0,30}$", var.owner))
    error_message = "owner must look like team-<name>."
  }
}

variable "tier" {
  type = string

  validation {
    condition     = contains(["critical", "standard", "best-effort"], var.tier)
    error_message = "tier must be critical, standard or best-effort."
  }
}

variable "github_repo" {
  description = "GitHub repository (org/name) whose workflows may assume the deploy role."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repo))
    error_message = "github_repo must look like org/name."
  }
}

variable "github_oidc_provider_arn" {
  description = "ARN of the account's GitHub Actions OIDC identity provider (created once per account)."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Monthly cost budget for resources tagged with this service."
  type        = number
  default     = 50
}

variable "budget_alert_emails" {
  description = "Addresses notified when forecasted spend exceeds 80% of the budget. Empty disables the budget."
  type        = list(string)
  default     = []
}

variable "log_retention_days" {
  type    = number
  default = 30
}
