# Root module for every service environment. `platformctl env add` drops one <service>-<env>.tf
# file here per request; they are reviewed in a pull request and planned/applied by CI.
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }

  # backend "s3" { ... }   # configure shared remote state with locking before real use
}

provider "aws" {
  region = var.region
}
