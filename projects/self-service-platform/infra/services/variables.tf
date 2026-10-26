variable "region" {
  type    = string
  default = "us-east-1"
}

variable "github_oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider in this AWS account."
  type        = string
}
