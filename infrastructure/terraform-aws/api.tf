resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.lambda_name}"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/energy-demo-aws/http-api"
  retention_in_days = 7
}

resource "aws_lambda_function" "energy" {
  function_name                  = local.lambda_name
  role                           = aws_iam_role.lambda.arn
  handler                        = "handler.lambda_handler"
  runtime                        = "python3.12"
  architectures                  = ["x86_64"]
  filename                       = "${path.module}/../../artifacts/aws/lambda.zip"
  source_code_hash               = filebase64sha256("${path.module}/../../artifacts/aws/lambda.zip")
  memory_size                    = 128
  timeout                        = 3
  reserved_concurrent_executions = 2
  depends_on                     = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy.lambda_logs]
}

resource "aws_apigatewayv2_api" "energy" {
  name          = local.name
  protocol_type = "HTTP"
  lifecycle { prevent_destroy = true }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.energy.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.energy.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 5000
}

resource "aws_apigatewayv2_route" "energy" {
  api_id    = aws_apigatewayv2_api.energy.id
  route_key = "GET /api/energy"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.energy.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 2
    throttling_rate_limit  = 1
  }
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    format = jsonencode({
      requestId   = "$context.requestId", status = "$context.status"
      requestTime = "$context.requestTime", responseLength = "$context.responseLength"
    })
  }
}

resource "aws_lambda_permission" "api" {
  statement_id   = "AllowEnergyDemoHttpApi"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.energy.function_name
  principal      = "apigateway.amazonaws.com"
  source_arn     = "${aws_apigatewayv2_api.energy.execution_arn}/*/GET/api/energy"
  source_account = var.account_id
}
