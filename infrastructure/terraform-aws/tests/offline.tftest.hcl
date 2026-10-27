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
    defaults = { invoke_arn = "arn:aws:apigateway:eu-north-1:lambda:path/2015-03-31/functions/arn:aws:lambda:eu-north-1:123456789012:function:energy-demo-aws-energy/invocations" }
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
