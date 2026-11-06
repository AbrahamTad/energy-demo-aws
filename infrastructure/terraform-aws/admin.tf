variable "admin_email_testing_enabled" {
  type        = bool
  default     = false
  description = "Separate explicit opt-in for Admin SES test sending; keep false for Contact no-send rollout."
  validation {
    condition     = !var.admin_email_testing_enabled || var.enable_admin
    error_message = "Admin email testing requires separately enabled Admin infrastructure."
  }
}

variable "enable_admin" {
  type        = bool
  default     = false
  description = "Opt in only after separately reviewed identity, SES and bootstrap preparation."
}
variable "admin_cognito_client_id" {
  type    = string
  default = ""
}
variable "admin_email_sender" {
  type    = string
  default = ""
}
variable "admin_email_recipients" {
  type    = set(string)
  default = []
}

locals {
  admin_functions = var.enable_admin ? merge({ admin = "admin_handler.lambda_handler" }, var.admin_email_testing_enabled ? { email = "admin_email.lambda_handler", events = "admin_events.lambda_handler" } : {}) : {}
  admin_routes = var.enable_admin ? merge({
    session_get  = { method = "GET", path = "/api/admin/session", handler = "admin" }
    session_post = { method = "POST", path = "/api/admin/session", handler = "admin" }
    users        = { method = "GET", path = "/api/admin/users", handler = "admin" }
    public       = { method = "GET", path = "/api/admin/records/public", handler = "admin" }
    mine         = { method = "GET", path = "/api/admin/records/mine", handler = "admin" }
    status       = { method = "GET", path = "/api/admin/status", handler = "admin" }
    }, var.admin_email_testing_enabled ? {
    email_get  = { method = "GET", path = "/api/admin/email", handler = "email" }
    email_post = { method = "POST", path = "/api/admin/email", handler = "email" }
  } : {}) : {}
}

module "admin_policy" {
  source                = "../modules/admin-policy"
  account_id            = var.account_id
  pool_id               = var.cognito_user_pool_id
  sender                = var.admin_email_sender
  recipients            = var.admin_email_recipients
  email_testing_enabled = var.admin_email_testing_enabled
}

resource "aws_dynamodb_table" "admin_control" {
  count                       = var.enable_admin ? 1 : 0
  name                        = "${local.name}-admin-control"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "pk"
  deletion_protection_enabled = true
  attribute {
    name = "pk"
    type = "S"
  }
  ttl {
    attribute_name = "expires"
    enabled        = true
  }
  server_side_encryption { enabled = true }
  point_in_time_recovery { enabled = true }
  on_demand_throughput {
    max_read_request_units  = 10
    max_write_request_units = 10
  }
  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = can(regex("^[a-z0-9]{1,128}$", var.admin_cognito_client_id)) && (!var.admin_email_testing_enabled || (length(var.admin_email_recipients) > 0 && length(var.admin_email_recipients) <= 5 && alltrue([for email in setunion(var.admin_email_recipients, toset([var.admin_email_sender])) : can(regex("^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$", email))])))
      error_message = "Admin requires a dedicated Cognito client; separately enabled email testing also requires a fixed sender and 1-5 approved SES recipients."
    }
  }
}

resource "aws_iam_role" "admin" {
  for_each             = var.enable_admin ? toset(var.admin_email_testing_enabled ? ["admin", "email", "events", "private"] : ["admin", "private"]) : toset([])
  name                 = "admin-${each.key}"
  path                 = "/energy-demo-aws/"
  permissions_boundary = "arn:aws:iam::${var.account_id}:policy/energy-demo-bootstrap/admin-${each.key}-boundary"
  assume_role_policy = each.key == "private" ? jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Action = ["sts:AssumeRole", "sts:TagSession"],
    Principal = { AWS = "arn:aws:iam::${var.account_id}:root" },
    Condition = { ArnEquals = { "aws:PrincipalArn" = "arn:aws:iam::${var.account_id}:role/energy-demo-aws/admin-admin" }, StringLike = { "aws:RequestTag/user_sub" = "????????-????-????-????-????????????" }, "ForAllValues:StringEquals" = { "aws:TagKeys" = ["user_sub"] } }
  }] }) : jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }] })
  # Exact caller ARN condition avoids a creation-order dependency on the admin role.
}
resource "aws_iam_role_policy" "admin" {
  for_each = aws_iam_role.admin
  name     = "admin-${each.key}"
  role     = each.value.id
  policy   = module.admin_policy.policies[each.key]
}
resource "aws_cloudwatch_log_group" "admin" {
  for_each          = local.admin_functions
  name              = "/aws/lambda/${local.name}-admin-${each.key}"
  retention_in_days = 7
}
resource "aws_lambda_function" "admin" {
  for_each         = local.admin_functions
  function_name    = "${local.name}-admin-${each.key}"
  role             = aws_iam_role.admin[each.key].arn
  handler          = each.value
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 20
  filename         = "${path.module}/../../artifacts/aws/lambda.zip"
  source_code_hash = filebase64sha256("${path.module}/../../artifacts/aws/lambda.zip")
  environment {
    variables = merge({ ADMIN_CONTROL_TABLE = aws_dynamodb_table.admin_control[0].name }, each.key == "events" ? {
      ADMIN_EMAIL_TOPIC_ARN         = "arn:aws:sns:${local.region}:${var.account_id}:${local.name}-admin-email"
      ADMIN_EMAIL_CONFIGURATION_SET = "${local.name}-admin"
      } : {
      COGNITO_USER_POOL_ID = var.cognito_user_pool_id
      COGNITO_CLIENT_ID    = var.cognito_client_id
      }, each.key == "admin" ? {
      ADMIN_COGNITO_CLIENT_ID = var.admin_cognito_client_id
      PUBLIC_ENERGY_TABLE     = aws_dynamodb_table.public_energy.name
      USER_ENERGY_TABLE       = aws_dynamodb_table.user_energy.name
      ADMIN_PRIVATE_ROLE_ARN  = aws_iam_role.admin["private"].arn
      } : {}, each.key == "email" ? {
      ADMIN_EMAIL_TESTING_ENABLED   = tostring(var.admin_email_testing_enabled)
      ADMIN_EMAIL_SENDER            = var.admin_email_sender
      ADMIN_EMAIL_RECIPIENTS        = jsonencode(sort(tolist(var.admin_email_recipients)))
      ADMIN_EMAIL_CONFIGURATION_SET = "${local.name}-admin"
    } : {})
  }
  depends_on = [aws_cloudwatch_log_group.admin, aws_iam_role_policy.admin]
}
resource "aws_apigatewayv2_integration" "admin" {
  for_each               = var.enable_admin ? toset(var.admin_email_testing_enabled ? ["admin", "email"] : ["admin"]) : toset([])
  api_id                 = aws_apigatewayv2_api.energy.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.admin[each.key].invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 21000
}
resource "aws_apigatewayv2_route" "admin" {
  for_each             = local.admin_routes
  api_id               = aws_apigatewayv2_api.energy.id
  route_key            = "${each.value.method} ${each.value.path}"
  target               = "integrations/${aws_apigatewayv2_integration.admin[each.value.handler].id}"
  authorization_type   = "JWT"
  authorizer_id        = aws_apigatewayv2_authorizer.users.id
  authorization_scopes = ["aws.cognito.signin.user.admin"]
}
resource "aws_lambda_permission" "admin" {
  for_each       = local.admin_routes
  statement_id   = "Admin${each.key}"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.admin[each.value.handler].function_name
  principal      = "apigateway.amazonaws.com"
  source_account = var.account_id
  source_arn     = "${aws_apigatewayv2_api.energy.execution_arn}/*/${each.value.method}${each.value.path}"
}
resource "aws_lambda_permission" "admin_events" {
  count          = var.enable_admin && var.admin_email_testing_enabled ? 1 : 0
  statement_id   = "TrustedSESNotifications"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.admin["events"].function_name
  principal      = "sns.amazonaws.com"
  source_account = var.account_id
  source_arn     = "arn:aws:sns:${local.region}:${var.account_id}:${local.name}-admin-email"
}
resource "aws_sns_topic_subscription" "admin_events" {
  count      = var.enable_admin && var.admin_email_testing_enabled ? 1 : 0
  topic_arn  = "arn:aws:sns:${local.region}:${var.account_id}:${local.name}-admin-email"
  protocol   = "lambda"
  endpoint   = aws_lambda_function.admin["events"].arn
  depends_on = [aws_lambda_permission.admin_events]
}
resource "aws_cloudfront_function" "admin_entry" {
  count   = var.enable_admin ? 1 : 0
  name    = "${local.name}-admin-entry"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = <<-JS
    function handler(event) {
      var request = event.request;
      if (request.uri === '/admin' || request.uri === '/admin/') {
        request.uri = '/index.html';
      }
      return request;
    }
  JS
}

output "admin_enabled" { value = var.enable_admin }
