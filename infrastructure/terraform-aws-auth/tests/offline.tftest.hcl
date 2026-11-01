mock_provider "aws" {
  override_during = plan
  mock_resource "aws_cognito_user_pool" {
    defaults = { id = "eu-north-1_OfflineFixture" }
  }
}

variables { account_id = "123456789012" }

run "secure_identity" {
  command = plan
  assert {
    condition = (
      aws_cognito_user_pool.users.user_pool_tier == "LITE" &&
      aws_cognito_user_pool.users.deletion_protection == "ACTIVE" &&
      aws_cognito_user_pool.users.username_attributes == toset(["email"]) &&
      aws_cognito_user_pool.users.auto_verified_attributes == toset(["email"]) &&
      !aws_cognito_user_pool.users.username_configuration[0].case_sensitive
    )
    error_message = "Keep the low-cost, deletion-protected email pool."
  }
  assert {
    condition = (
      aws_cognito_user_pool.users.password_policy[0].minimum_length == 12 &&
      aws_cognito_user_pool.users.password_policy[0].require_lowercase &&
      aws_cognito_user_pool.users.password_policy[0].require_uppercase &&
      aws_cognito_user_pool.users.password_policy[0].require_numbers &&
      aws_cognito_user_pool.users.password_policy[0].require_symbols &&
      aws_cognito_user_pool.users.mfa_configuration == "OPTIONAL" &&
      aws_cognito_user_pool.users.software_token_mfa_configuration[0].enabled
    )
    error_message = "Strong passwords and optional authenticator MFA are required."
  }
  assert {
    condition = (
      aws_cognito_user_pool.users.account_recovery_setting[0].recovery_mechanism == toset([{ name = "verified_email", priority = 1 }]) &&
      aws_cognito_user_pool.users.user_attribute_update_settings[0].attributes_require_verification_before_update == toset(["email"]) &&
      aws_cognito_user_pool.users.email_configuration[0].email_sending_account == "COGNITO_DEFAULT" &&
      length(aws_cognito_user_pool.users.sms_configuration) == 0
    )
    error_message = "Recovery must require verified email; do not add SMS costs or bypass verification."
  }
  assert {
    condition = (
      !aws_cognito_user_pool_client.spa.generate_secret &&
      aws_cognito_user_pool_client.spa.explicit_auth_flows == toset(["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]) &&
      aws_cognito_user_pool_client.spa.prevent_user_existence_errors == "ENABLED" &&
      aws_cognito_user_pool_client.spa.enable_token_revocation &&
      !aws_cognito_user_pool_client.spa.allowed_oauth_flows_user_pool_client &&
      aws_cognito_user_pool_client.spa.write_attributes == toset(["email", "name"])
    )
    error_message = "The public SPA must use SRP, no client secret, revocable tokens, and restricted attribute writes."
  }
  assert {
    condition = (
      aws_cognito_user_pool_client.spa.access_token_validity == 15 &&
      aws_cognito_user_pool_client.spa.id_token_validity == 15 &&
      aws_cognito_user_pool_client.spa.refresh_token_validity == 1 &&
      aws_cognito_user_pool_client.spa.token_validity_units[0].access_token == "minutes" &&
      aws_cognito_user_pool_client.spa.token_validity_units[0].id_token == "minutes" &&
      aws_cognito_user_pool_client.spa.token_validity_units[0].refresh_token == "days"
    )
    error_message = "Keep short access/ID tokens and a one-day refresh lifetime."
  }
}

run "reject_simulator_account" {
  command = plan
  variables { account_id = "000000000000" }
  expect_failures = [var.account_id]
}

run "admin_step_up_is_separate" {
  command = plan
  assert {
    condition     = aws_cognito_user_group.admins.name == "energy-demo-admin" && aws_cognito_user_pool_client.admin_step_up.explicit_auth_flows == toset(["ALLOW_ADMIN_USER_PASSWORD_AUTH"]) && !aws_cognito_user_pool_client.admin_step_up.generate_secret && aws_cognito_user_pool_client.admin_step_up.access_token_validity == 15 && aws_cognito_user_pool_client.admin_step_up.id_token_validity == 15 && aws_cognito_user_pool_client.admin_step_up.refresh_token_validity == 1 && aws_cognito_user_pool_client.admin_step_up.token_validity_units[0].refresh_token == "days" && aws_cognito_user_pool_client.admin_step_up.enable_token_revocation && aws_cognito_user_pool.users.mfa_configuration == "OPTIONAL"
    error_message = "Admin needs a separate IAM-only password flow; normal SRP authentication and optional user MFA remain unchanged."
  }
}

run "admin_client_least_privilege" {
  command = plan
  assert {
    condition = (
      aws_cognito_user_pool_client.admin_step_up.read_attributes == toset(["sub"]) &&
      aws_cognito_user_pool_client.admin_step_up.write_attributes == toset(["email"]) &&
      !aws_cognito_user_pool_client.admin_step_up.allowed_oauth_flows_user_pool_client &&
      length(aws_cognito_user_pool_client.admin_step_up.allowed_oauth_flows) == 0 &&
      length(aws_cognito_user_pool_client.admin_step_up.allowed_oauth_scopes) == 0 &&
      length(aws_cognito_user_pool_client.admin_step_up.callback_urls) == 0 &&
      length(aws_cognito_user_pool_client.admin_step_up.logout_urls) == 0 &&
      aws_cognito_user_pool_client.admin_step_up.supported_identity_providers == toset(["COGNITO"]) &&
      aws_cognito_user_pool_client.admin_step_up.auth_session_validity == 3 &&
      !aws_cognito_user_pool_client.admin_step_up.enable_propagate_additional_user_context_data &&
      aws_cognito_user_pool_client.admin_step_up.refresh_token_rotation[0].feature == "DISABLED" &&
      aws_cognito_user_pool_client.admin_step_up.prevent_user_existence_errors == "ENABLED" &&
      aws_cognito_user_pool_client.admin_step_up.token_validity_units[0].access_token == "minutes" &&
      aws_cognito_user_pool_client.admin_step_up.token_validity_units[0].id_token == "minutes" &&
      aws_cognito_user_group.admins.role_arn == null
    )
    error_message = "Admin step-up must have minimal attribute permissions, no OAuth/federation/IAM role, and explicit short challenge and token settings."
  }
}
