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
  region            = "eu-north-1"
  name              = "energy-demo-aws"
  bucket_name       = "energy-demo-aws-${var.account_id}-${local.region}"
  boundary_arn      = "arn:aws:iam::${var.account_id}:policy/energy-demo-bootstrap/lambda-logs-boundary"
  lambda_name       = "energy-demo-aws-energy"
  user_lambda_name  = "energy-demo-aws-user-energy"
  user_boundary_arn = "arn:aws:iam::${var.account_id}:policy/energy-demo-bootstrap/user-energy-boundary"
}

variable "cognito_user_pool_id" {
  type    = string
  default = "eu-north-1_6m60ePWS0"
  validation {
    condition     = can(regex("^eu-north-1_[A-Za-z0-9]+$", var.cognito_user_pool_id))
    error_message = "Use the separately provisioned Cognito pool in eu-north-1."
  }
}

variable "cognito_client_id" {
  type    = string
  default = "796jkcsk4dc5scoc77r8ejies7"
  validation {
    condition     = can(regex("^[a-z0-9]{1,128}$", var.cognito_client_id))
    error_message = "Use the public SPA client ID, never a client secret."
  }
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
