terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    # archive provider: used to zip alarm_handler.py for Lambda deployment
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  # Local state is sufficient for a single-developer portfolio project.
  #
  # For team use, migrate to S3 remote backend:
  #
  # backend "s3" {
  #   bucket         = "unagi-terraform-state"
  #   key            = "unagi/terraform.tfstate"
  #   region         = "eu-north-1"
  #   encrypt        = true
  #   dynamodb_table = "unagi-terraform-locks"  # prevents concurrent applies
  # }
  #
  # Bootstrap steps (one-time, before `terraform init`):
  #   aws s3api create-bucket --bucket unagi-terraform-state --region eu-north-1 \
  #     --create-bucket-configuration LocationConstraint=eu-north-1
  #   aws s3api put-bucket-versioning --bucket unagi-terraform-state \
  #     --versioning-configuration Status=Enabled
  #   aws dynamodb create-table --table-name unagi-terraform-locks \
  #     --attribute-definitions AttributeName=LockID,AttributeType=S \
  #     --key-schema AttributeName=LockID,KeyType=HASH \
  #     --billing-mode PAY_PER_REQUEST
}

provider "aws" {
  region  = var.aws_region
  profile = "personal"
}
