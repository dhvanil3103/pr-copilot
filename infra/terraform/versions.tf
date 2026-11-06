terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.72"
    }
  }

  # Local state by default. To move it to S3, see docs/DEPLOY_EKS.md ("Remote state").
  # backend "s3" {
  #   bucket       = "my-terraform-state-bucket"
  #   key          = "pr-copilot/terraform.tfstate"
  #   region       = "us-east-1"
  #   use_lockfile = true
  # }
}

provider "aws" {
  region = var.region

  # Every resource Terraform creates gets these tags, so leftovers are easy to find.
  default_tags {
    tags = local.tags
  }
}
