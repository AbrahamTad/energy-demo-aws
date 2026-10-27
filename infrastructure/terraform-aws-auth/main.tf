# Separate administrator-managed identity root. Never applied by GitHub's
# application deployment roles; those roles receive no Cognito permissions.
terraform {
  required_version = "= 1.16.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.69.1"
    }
  }
  # Separate key in the existing protected state bucket; configured only after
  # explicit approval with an administrator session (see README.md).
  backend "s3" {}
}

variable "account_id" {
  type        = string
  description = "Explicit approved real AWS account."
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id)) && var.account_id != "000000000000"
    error_message = "An explicitly approved real 12-digit account ID is required."
  }
}

provider "aws" {
  region              = "eu-north-1"
  allowed_account_ids = [var.account_id]
  default_tags { tags = { Project = "EnergyDemo", Environment = "AWS", ManagedBy = "Terraform" } }
}

resource "aws_cognito_user_pool" "users" {
  name                     = "energy-demo-aws-users"
  user_pool_tier           = "LITE"
  deletion_protection      = "ACTIVE"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  mfa_configuration        = "OPTIONAL"
  lifecycle { prevent_destroy = true }

  username_configuration { case_sensitive = false }
  admin_create_user_config { allow_admin_create_user_only = false }
  software_token_mfa_configuration { enabled = true }
  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 1
  }
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
  user_attribute_update_settings { attributes_require_verification_before_update = ["email"] }
  email_configuration { email_sending_account = "COGNITO_DEFAULT" }
  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
    email_subject        = "Verify your EnergyDemo account"
    email_message        = "Your EnergyDemo verification code is {####}. If you did not request this account, ignore this email."
  }
  schema {
    name                     = "email"
    attribute_data_type      = "String"
    required                 = true
    mutable                  = true
    developer_only_attribute = false
    string_attribute_constraints {
      min_length = 1
      max_length = 254
    }
  }
  schema {
    name                     = "name"
    attribute_data_type      = "String"
    required                 = false
    mutable                  = true
    developer_only_attribute = false
    string_attribute_constraints {
      min_length = 1
      max_length = 64
    }
  }
}

resource "aws_cognito_user_pool_client" "spa" {
  name                                 = "energy-demo-web"
  user_pool_id                         = aws_cognito_user_pool.users.id
  generate_secret                      = false
  explicit_auth_flows                  = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  allowed_oauth_flows_user_pool_client = false
  supported_identity_providers         = ["COGNITO"]
  read_attributes                      = ["email", "email_verified", "name", "sub"]
  write_attributes                     = ["email", "name"]
  access_token_validity                = 15
  id_token_validity                    = 15
  refresh_token_validity               = 1
  auth_session_validity                = 3
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
  lifecycle { prevent_destroy = true }
}

# These are public browser configuration values, never credentials or secrets.
output "user_pool_id" { value = aws_cognito_user_pool.users.id }
output "spa_client_id" { value = aws_cognito_user_pool_client.spa.id }
output "jwt_issuer" { value = "https://cognito-idp.eu-north-1.amazonaws.com/${aws_cognito_user_pool.users.id}" }
