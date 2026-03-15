terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  # Local state: sufficient for a portfolio project
}

provider "aws" {
  region  = var.aws_region
  profile = "personal"
}
