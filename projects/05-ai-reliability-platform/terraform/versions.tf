terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.70"
    }
  }

  # Remote state is recommended for any shared environment (S3 + DynamoDB lock, or S3 native
  # locking on newer Terraform). Left commented so `terraform init` works with local state:
  #
  # backend "s3" {
  #   bucket         = "YOUR-tf-state-bucket"
  #   key            = "ai-reliability-platform/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "YOUR-tf-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "ai-reliability-platform"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
