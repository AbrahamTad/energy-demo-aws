resource "aws_cloudwatch_log_group" "user_energy" {
  name              = "/aws/lambda/${local.user_lambda_name}"
  retention_in_days = 7
}

resource "aws_lambda_function" "user_energy" {
  function_name    = local.user_lambda_name
  role             = aws_iam_role.user_energy.arn
  handler          = "user_handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  filename         = "${path.module}/../../artifacts/aws/lambda.zip"
  source_code_hash = filebase64sha256("${path.module}/../../artifacts/aws/lambda.zip")
  memory_size      = 128
  timeout          = 5
  environment {
    variables = {
      USER_ENERGY_TABLE    = aws_dynamodb_table.user_energy.name
      COGNITO_USER_POOL_ID = var.cognito_user_pool_id
      COGNITO_CLIENT_ID    = var.cognito_client_id
    }
  }
  depends_on = [aws_cloudwatch_log_group.user_energy, aws_iam_role_policy.user_energy]
}

resource "aws_apigatewayv2_authorizer" "users" {
  api_id           = aws_apigatewayv2_api.energy.id
  name             = "cognito-access-tokens"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  jwt_configuration {
    audience = [var.cognito_client_id]
    issuer   = "https://cognito-idp.${local.region}.amazonaws.com/${var.cognito_user_pool_id}"
  }
}

resource "aws_apigatewayv2_integration" "user_energy" {
  api_id                 = aws_apigatewayv2_api.energy.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.user_energy.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 6000
}

locals {
  user_routes = {
    list   = { method = "GET", path = "/api/me/energy" }
    create = { method = "POST", path = "/api/me/energy" }
    read   = { method = "GET", path = "/api/me/energy/{record_id}" }
    update = { method = "PUT", path = "/api/me/energy/{record_id}" }
    delete = { method = "DELETE", path = "/api/me/energy/{record_id}" }
  }
}

resource "aws_apigatewayv2_route" "user_energy" {
  for_each           = local.user_routes
  api_id             = aws_apigatewayv2_api.energy.id
  route_key          = "${each.value.method} ${each.value.path}"
  target             = "integrations/${aws_apigatewayv2_integration.user_energy.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.users.id
  # Direct SRP access tokens carry this scope; ID tokens do not.
  authorization_scopes = ["aws.cognito.signin.user.admin"]
}

resource "aws_lambda_permission" "user_energy" {
  for_each       = local.user_routes
  statement_id   = "EnergyDemoUser${title(each.key)}"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.user_energy.function_name
  principal      = "apigateway.amazonaws.com"
  source_arn     = "${aws_apigatewayv2_api.energy.execution_arn}/*/${each.value.method}${replace(each.value.path, "{record_id}", "*")}"
  source_account = var.account_id
}
