variable "account_id" {
  type        = string
  description = "Explicit real AWS account, also checked by the provider and backend."
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id)) && var.account_id != "000000000000"
    error_message = "Set the real 12-digit AWS account ID; the Floci account is forbidden."
  }
}

variable "budget_email" {
  type        = string
  sensitive   = true
  description = "Recipient for $1/$3/$5 account-wide monthly budget notifications."
  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.budget_email))
    error_message = "A valid budget notification email is required."
  }
}

locals {
  region       = "eu-north-1"
  name         = "energy-demo-aws"
  bucket_name  = "energy-demo-aws-${var.account_id}-${local.region}"
  boundary_arn = "arn:aws:iam::${var.account_id}:policy/energy-demo-bootstrap/lambda-logs-boundary"
  lambda_name  = "energy-demo-aws-energy"
}

provider "aws" {
  region              = local.region
  allowed_account_ids = [var.account_id]
  default_tags {
    tags = {
      Project     = "EnergyDemo"
      Environment = "AWS"
      ManagedBy   = "Terraform"
    }
  }
}
