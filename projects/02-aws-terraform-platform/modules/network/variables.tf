variable "name" {
  description = "Name prefix for all network resources."
  type        = string
}

variable "cidr_block" {
  description = "VPC CIDR. Must be a /16 so the subnet maths in main.tf holds."
  type        = string
  default     = "10.20.0.0/16"

  validation {
    condition     = can(cidrhost(var.cidr_block, 0)) && endswith(var.cidr_block, "/16")
    error_message = "cidr_block must be a valid IPv4 CIDR with a /16 prefix."
  }
}

variable "az_count" {
  description = "Number of availability zones to span (2-3)."
  type        = number
  default     = 2

  validation {
    condition     = var.az_count >= 2 && var.az_count <= 3
    error_message = "az_count must be 2 or 3."
  }
}

variable "single_nat_gateway" {
  description = "true = one shared NAT gateway (cheap, single-AZ egress risk); false = one per AZ (resilient)."
  type        = bool
  default     = true
}

variable "flow_log_retention_days" {
  description = "Retention for VPC flow logs in CloudWatch."
  type        = number
  default     = 30
}
