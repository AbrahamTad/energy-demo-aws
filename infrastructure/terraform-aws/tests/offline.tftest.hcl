# Mock provider: these plans never authenticate to AWS or access the backend.
mock_provider "aws" {
  override_during = plan
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/energy-demo-aws/lambda-execution" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:eu-north-1:123456789012:log-group:/aws/lambda/energy-demo-aws-energy" }
  }
  mock_resource "aws_lambda_function" {
    defaults = {
      arn        = "arn:aws:lambda:eu-north-1:123456789012:function:energy-demo-aws-admin-events"
      invoke_arn = "arn:aws:apigateway:eu-north-1:lambda:path/2015-03-31/functions/arn:aws:lambda:eu-north-1:123456789012:function:energy-demo-aws-energy/invocations"
    }
  }
  mock_resource "aws_s3_bucket" {
    defaults = {
      arn                         = "arn:aws:s3:::energy-demo-aws-123456789012-eu-north-1"
      bucket_regional_domain_name = "energy-demo-aws-123456789012-eu-north-1.s3.eu-north-1.amazonaws.com"
    }
  }
  mock_resource "aws_cloudfront_distribution" {
    defaults = { arn = "arn:aws:cloudfront::123456789012:distribution/TESTFIXTURE" }
  }
  mock_resource "aws_cloudfront_origin_access_control" {
    defaults = { id = "FIXTUREOAC" }
  }
  mock_resource "aws_apigatewayv2_api" {
    defaults = {
      api_endpoint  = "https://fixture.execute-api.eu-north-1.amazonaws.com"
      execution_arn = "arn:aws:execute-api:eu-north-1:123456789012:fixture"
    }
  }
  mock_resource "aws_apigatewayv2_authorizer" {
    defaults = { id = "fixtureauthorizer" }
  }
}

run "admin_is_opt_in" {
  command = plan
  assert {
    condition     = length(aws_lambda_function.admin) == 0 && length(aws_apigatewayv2_route.admin) == 0 && length(aws_dynamodb_table.admin_control) == 0
    error_message = "Existing deployments must not silently enable admin infrastructure."
  }
}

run "admin_security_and_cost_boundaries" {
  command = plan
  variables {
    admin_email_testing_enabled = true
    enable_admin                = true
    admin_cognito_client_id     = "adminfixtureclient"
    admin_email_sender          = "sender@example.invalid"
    admin_email_recipients      = ["test@example.invalid"]
  }
  assert {
    condition     = length(aws_apigatewayv2_route.admin) == 8 && alltrue([for route in aws_apigatewayv2_route.admin : route.authorization_type == "JWT" && route.authorizer_id == aws_apigatewayv2_authorizer.users.id && route.authorization_scopes == toset(["aws.cognito.signin.user.admin"])])
    error_message = "Every admin route, including step-up and email, must require Cognito access tokens."
  }
  assert {
    condition     = length(aws_lambda_function.admin) == 3 && length(aws_iam_role.admin) == 4 && aws_dynamodb_table.admin_control[0].ttl[0].enabled && aws_dynamodb_table.admin_control[0].ttl[0].attribute_name == "expires" && aws_dynamodb_table.admin_control[0].point_in_time_recovery[0].enabled && aws_dynamodb_table.admin_control[0].deletion_protection_enabled && aws_dynamodb_table.admin_control[0].on_demand_throughput[0].max_write_request_units == 10
    error_message = "Admin must use dedicated bounded functions/roles and protected, expiring control data."
  }
  assert {
    condition     = alltrue([for s in jsondecode(module.admin_policy.policies["admin"]).Statement : !contains(flatten([s.Resource]), "arn:aws:dynamodb:eu-north-1:123456789012:table/energy-demo-aws-user-energy")]) && jsondecode(module.admin_policy.policies["private"]).Statement[0].Condition["ForAllValues:StringEquals"]["dynamodb:LeadingKeys"] == ["$${aws:PrincipalTag/user_sub}"] && jsondecode(module.admin_policy.policies["private"]).Statement[0].Action == ["dynamodb:Query"]
    error_message = "Admin cannot directly browse private records; the read-only assumed role must enforce owner tags."
  }
  assert {
    condition     = alltrue([for s in jsondecode(module.admin_policy.policies["email"]).Statement : s.Condition.StringEquals["ses:FromAddress"] == "sender@example.invalid" && s.Condition["ForAllValues:StringEquals"]["ses:Recipients"] == ["test@example.invalid"] if contains(s.Action, "ses:SendEmail")]) && alltrue([for s in jsondecode(module.admin_policy.policies["events"]).Statement : !contains(s.Action, "ses:SendEmail")])
    error_message = "Sending is limited by IAM to the fixed sender and approved recipients; event handlers cannot send."
  }
}

run "reject_unconfigured_admin" {
  command = plan
  variables { enable_admin = true }
  expect_failures = [aws_dynamodb_table.admin_control[0]]
}

override_resource {
  target          = aws_dynamodb_table.public_energy
  override_during = plan
  values          = { arn = "arn:aws:dynamodb:eu-north-1:123456789012:table/energy-demo-aws-public-energy" }
}
override_resource {
  target          = aws_dynamodb_table.user_energy
  override_during = plan
  values          = { arn = "arn:aws:dynamodb:eu-north-1:123456789012:table/energy-demo-aws-user-energy" }
}

variables {
  account_id   = "123456789012" # Offline fixture; never authenticated.
  budget_email = "test@example.invalid"
}

run "guarded_serverless_stack" {
  command = plan
  assert {
    condition     = aws_apigatewayv2_stage.default.name == "$default" && aws_apigatewayv2_route.energy.route_key == "GET /api/energy"
    error_message = "API path must stay /api/energy without a stage prefix."
  }
  assert {
    condition = alltrue([
      for behavior in aws_cloudfront_distribution.frontend.ordered_cache_behavior :
      behavior.path_pattern == "/api/*" && behavior.target_origin_id == "energy-api" &&
      behavior.cache_policy_id == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" &&
      behavior.origin_request_policy_id == "b689b0a8-53d0-40ab-baf2-68738e2966ac"
    ])
    error_message = "API caching must stay disabled and viewer Host must not reach API Gateway."
  }
  assert {
    condition = length(aws_cloudfront_distribution.frontend.origin) == 2 && alltrue([
      for origin in aws_cloudfront_distribution.frontend.origin :
      length(origin.s3_origin_config) == 0 && (
        origin.origin_id == "frontend-s3" ? length(origin.custom_origin_config) == 0 && origin.origin_access_control_id == aws_cloudfront_origin_access_control.frontend.id :
        origin.origin_id == "energy-api" && alltrue([
          for config in origin.custom_origin_config :
          config.origin_protocol_policy == "https-only" && config.origin_ssl_protocols == toset(["TLSv1.2"])
        ]) && length(origin.custom_origin_config) == 1
      )
    ]) && aws_cloudfront_origin_access_control.frontend.signing_behavior == "always" && aws_cloudfront_origin_access_control.frontend.signing_protocol == "sigv4"
    error_message = "Keep OAC without an empty legacy OAI block, and preserve the HTTPS/TLS API origin."
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.frontend.block_public_policy && aws_s3_bucket_public_access_block.frontend.restrict_public_buckets
    error_message = "The frontend bucket must remain private."
  }
  assert {
    condition     = aws_lambda_function.energy.timeout == 3 && aws_cloudwatch_log_group.lambda.retention_in_days == 7
    error_message = "Learning cost safeguards changed."
  }
  assert {
    condition     = aws_budgets_budget.learning.limit_amount == "5" && length(aws_budgets_budget.learning.notification) == 3
    error_message = "The $5 budget and three notifications are required."
  }
}

run "reject_floci_account" {
  command = plan
  variables { account_id = "000000000000" }
  expect_failures = [var.account_id]
}

run "database_and_private_routes" {
  command = plan
  assert {
    condition = (
      alltrue([for table in [aws_dynamodb_table.public_energy, aws_dynamodb_table.user_energy] :
        table.billing_mode == "PAY_PER_REQUEST" && table.deletion_protection_enabled &&
        table.server_side_encryption[0].enabled && table.point_in_time_recovery[0].enabled &&
        table.on_demand_throughput[0].max_read_request_units == 10 && table.on_demand_throughput[0].max_write_request_units == 5
      ]) && aws_dynamodb_table.user_energy.hash_key == "user_sub" && aws_dynamodb_table.public_energy.hash_key == "dataset"
    )
    error_message = "Keep separate protected, encrypted, backed-up pay-per-request tables with throughput caps and sub ownership."
  }
  assert {
    condition = (
      aws_apigatewayv2_route.energy.authorization_type == "NONE" && length(aws_apigatewayv2_route.user_energy) == 5 && alltrue([
        for route in values(aws_apigatewayv2_route.user_energy) : route.authorization_type == "JWT" && route.authorization_scopes == toset(["aws.cognito.signin.user.admin"])
      ]) && aws_apigatewayv2_authorizer.users.jwt_configuration[0].audience == toset(["796jkcsk4dc5scoc77r8ejies7"]) &&
      aws_apigatewayv2_authorizer.users.jwt_configuration[0].issuer == "https://cognito-idp.eu-north-1.amazonaws.com/eu-north-1_6m60ePWS0"
    )
    error_message = "The public API remains public; every private CRUD route requires an access token from the exact Cognito client and issuer."
  }
  assert {
    condition = (
      jsondecode(aws_iam_role_policy.public_energy.policy).Statement[0].Action == ["dynamodb:Query"] &&
      jsondecode(aws_iam_role_policy.public_energy.policy).Statement[0].Resource == "arn:aws:dynamodb:eu-north-1:123456789012:table/energy-demo-aws-public-energy" &&
      jsondecode(aws_iam_role_policy.public_energy.policy).Statement[0].Condition["ForAllValues:StringEquals"]["dynamodb:LeadingKeys"] == ["PUBLIC"] &&
      alltrue([for s in jsondecode(aws_iam_role_policy.user_energy.policy).Statement :
        s.Resource == "arn:aws:dynamodb:eu-north-1:123456789012:table/energy-demo-aws-user-energy" &&
        toset(s.Action) == toset(["dynamodb:Query", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"])
        if anytrue([for action in s.Action : startswith(action, "dynamodb:")])
      ])
    )
    error_message = "Public and private Lambdas must never share data permissions; no Scan or cross-table data access."
  }
  assert {
    condition = (
      toset(keys(aws_lambda_function.energy.environment[0].variables)) == toset(["PUBLIC_ENERGY_TABLE"]) &&
      !contains(keys(aws_lambda_function.user_energy.environment[0].variables), "PUBLIC_ENERGY_TABLE") &&
      aws_iam_role.user_energy.permissions_boundary == "arn:aws:iam::123456789012:policy/energy-demo-bootstrap/user-energy-boundary" &&
      alltrue([for behavior in aws_cloudfront_distribution.frontend.ordered_cache_behavior :
        contains(behavior.allowed_methods, "POST") && contains(behavior.allowed_methods, "PUT") && contains(behavior.allowed_methods, "DELETE") &&
        behavior.cache_policy_id == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" && behavior.origin_request_policy_id == "b689b0a8-53d0-40ab-baf2-68738e2966ac"
      ])
    )
    error_message = "Keep isolated environments/boundaries and forward authenticated writes without enabling API caching."
  }
}

run "admin_no_send_prerequisites_without_ses_inputs" {
  command = plan
  variables {
    enable_admin            = true
    admin_cognito_client_id = "fixtureadminclient"
  }
  assert {
    condition     = toset(keys(aws_lambda_function.admin)) == toset(["admin"]) && toset(keys(aws_iam_role.admin)) == toset(["admin", "private"]) && toset(keys(aws_apigatewayv2_integration.admin)) == toset(["admin"]) && length(aws_apigatewayv2_route.admin) == 6 && length(aws_lambda_permission.admin_events) == 0 && length(aws_sns_topic_subscription.admin_events) == 0
    error_message = "No-send Admin must omit email/events functions, roles, integrations, routes and subscriptions."
  }
  assert {
    condition     = alltrue([for route in aws_apigatewayv2_route.admin : route.authorization_type == "JWT" && route.authorizer_id == aws_apigatewayv2_authorizer.users.id && route.authorization_scopes == toset(["aws.cognito.signin.user.admin"])]) && alltrue([for policy in aws_iam_role_policy.admin : anytrue([for s in jsondecode(policy.policy).Statement : s.Effect == "Deny" && contains(s.Action, "ses:SendEmail") && contains(s.Action, "ses:SendRawEmail") && s.Resource == "*"])])
    error_message = "No-send must preserve JWT protection and deny sending on all remaining Admin roles."
  }
}
run "email_flag_requires_admin" {
  command = plan
  variables { admin_email_testing_enabled = true }
  expect_failures = [var.admin_email_testing_enabled]
}
