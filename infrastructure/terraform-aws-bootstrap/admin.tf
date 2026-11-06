variable "enable_admin_ci" {
  type        = bool
  default     = false
  description = "Separate approval for Admin CI policies and attachments; initial operator deployment needs only boundaries."
  validation {
    condition     = !var.enable_admin_ci || var.enable_admin
    error_message = "Admin CI requires Admin infrastructure preparation."
  }
}

variable "admin_email_testing_enabled" {
  type        = bool
  default     = false
  description = "Separate explicit opt-in for Admin SES test sending; keep false for Contact no-send rollout."
  validation {
    condition     = !var.admin_email_testing_enabled || var.enable_admin
    error_message = "Admin email testing requires separately enabled Admin infrastructure."
  }
}

# Explicit operator preparation. Existing deployment permissions remain unchanged by default.
variable "enable_admin" {
  type    = bool
  default = false
}
variable "cognito_user_pool_id" {
  type    = string
  default = "eu-north-1_6m60ePWS0"
}
variable "admin_email_sender" {
  type    = string
  default = ""
}
variable "admin_email_recipients" {
  type    = set(string)
  default = []
}

module "admin_policy" {
  source                = "../modules/admin-policy"
  account_id            = var.account_id
  pool_id               = var.cognito_user_pool_id
  sender                = var.admin_email_sender
  recipients            = var.admin_email_recipients
  email_testing_enabled = var.admin_email_testing_enabled
}

resource "aws_iam_policy" "admin_boundary" {
  for_each = var.enable_admin ? toset(var.admin_email_testing_enabled ? ["admin", "email", "events", "private"] : ["admin", "private"]) : toset([])
  name     = "admin-${each.key}-boundary"
  path     = "/energy-demo-bootstrap/"
  policy   = module.admin_policy.policies[each.key]
}
resource "aws_sesv2_email_identity" "admin" {
  for_each       = var.enable_admin && var.admin_email_testing_enabled ? setunion(var.admin_email_recipients, toset([var.admin_email_sender])) : toset([])
  email_identity = each.value
  lifecycle {
    precondition {
      condition     = length(var.admin_email_recipients) > 0 && length(var.admin_email_recipients) <= 5 && alltrue([for email in setunion(var.admin_email_recipients, toset([var.admin_email_sender])) : can(regex("^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$", email))])
      error_message = "Choose a fixed sender and 1-5 individually verified recipient addresses."
    }
  }
}
resource "aws_sesv2_configuration_set" "admin" {
  count                  = var.enable_admin && var.admin_email_testing_enabled ? 1 : 0
  configuration_set_name = "energy-demo-aws-admin"
  reputation_options { reputation_metrics_enabled = false }
  suppression_options { suppressed_reasons = ["BOUNCE", "COMPLAINT"] }
}
resource "aws_sns_topic" "admin_email" {
  count             = var.enable_admin && var.admin_email_testing_enabled ? 1 : 0
  name              = "energy-demo-aws-admin-email"
  kms_master_key_id = aws_kms_key.admin_email[0].arn
}
resource "aws_kms_key" "admin_email" {
  count                   = var.enable_admin && var.admin_email_testing_enabled ? 1 : 0
  description             = "EnergyDemo admin SES delivery-event encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  lifecycle { prevent_destroy = true }
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Principal = { AWS = "arn:aws:iam::${var.account_id}:root" }, Action = "kms:*", Resource = "*" },
    { Effect = "Allow", Principal = { Service = "ses.amazonaws.com" }, Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = "*",
    Condition = { StringEquals = { "aws:SourceAccount" = var.account_id }, ArnEquals = { "aws:SourceArn" = "arn:aws:ses:eu-north-1:${var.account_id}:configuration-set/energy-demo-aws-admin" } } }
  ] })
}
resource "aws_sns_topic_policy" "admin_email" {
  count = var.enable_admin && var.admin_email_testing_enabled ? 1 : 0
  arn   = aws_sns_topic.admin_email[0].arn
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Service = "ses.amazonaws.com" }, Action = "sns:Publish", Resource = aws_sns_topic.admin_email[0].arn,
    Condition = { StringEquals = { "AWS:SourceAccount" = var.account_id }, ArnEquals = { "AWS:SourceArn" = "arn:aws:ses:eu-north-1:${var.account_id}:configuration-set/energy-demo-aws-admin" } }
  }] })
}
resource "aws_sesv2_configuration_set_event_destination" "admin" {
  count                  = var.enable_admin && var.admin_email_testing_enabled ? 1 : 0
  configuration_set_name = aws_sesv2_configuration_set.admin[0].configuration_set_name
  event_destination_name = "delivery-status"
  event_destination {
    enabled              = true
    matching_event_types = ["SEND", "REJECT", "BOUNCE", "COMPLAINT", "DELIVERY", "DELIVERY_DELAY", "RENDERING_FAILURE"]
    sns_destination { topic_arn = aws_sns_topic.admin_email[0].arn }
  }
  depends_on = [aws_sns_topic_policy.admin_email]
}

locals {
  admin_role_arns    = [for name in(var.admin_email_testing_enabled ? ["admin", "email", "events", "private"] : ["admin", "private"]) : "arn:aws:iam::${var.account_id}:role/energy-demo-aws/admin-${name}"]
  admin_lambda_arns  = [for name in(var.admin_email_testing_enabled ? ["admin", "email", "events"] : ["admin"]) : "arn:aws:lambda:eu-north-1:${var.account_id}:function:energy-demo-aws-admin-${name}"]
  admin_log_arns     = [for name in(var.admin_email_testing_enabled ? ["admin", "email", "events"] : ["admin"]) : "arn:aws:logs:eu-north-1:${var.account_id}:log-group:/aws/lambda/energy-demo-aws-admin-${name}"]
  admin_control_arn  = "arn:aws:dynamodb:eu-north-1:${var.account_id}:table/energy-demo-aws-admin-control"
  admin_function_arn = "arn:aws:cloudfront::${var.account_id}:function/energy-demo-aws-admin-entry"
  admin_topic_arn    = "arn:aws:sns:eu-north-1:${var.account_id}:energy-demo-aws-admin-email"
  admin_ci_read = concat([
    { Effect = "Allow", Action = ["lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:GetFunctionCodeSigningConfig", "lambda:GetPolicy", "lambda:ListVersionsByFunction", "lambda:ListTags"], Resource = local.admin_lambda_arns },
    { Effect = "Allow", Action = ["iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole"], Resource = local.admin_role_arns },
    { Effect = "Allow", Action = ["dynamodb:DescribeTable", "dynamodb:DescribeContinuousBackups", "dynamodb:DescribeTimeToLive", "dynamodb:ListTagsOfResource"], Resource = local.admin_control_arn },
    { Effect = "Allow", Action = ["logs:ListTagsForResource"], Resource = local.admin_log_arns },
    { Effect = "Allow", Action = ["logs:ListTagsLogGroup"], Resource = [for arn in local.admin_log_arns : "${arn}:*"] },
    { Effect = "Allow", Action = ["cloudfront:DescribeFunction", "cloudfront:GetFunction", "cloudfront:ListTagsForResource"], Resource = local.admin_function_arn },
    ], [for statement in [
      { Effect = "Allow", Action = ["sns:GetSubscriptionAttributes"], Resource = "${local.admin_topic_arn}:*" }
  ] : statement if var.admin_email_testing_enabled])
  admin_ci_write = concat([
    { Effect = "Allow", Action = ["lambda:CreateFunction", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration", "lambda:AddPermission", "lambda:RemovePermission", "lambda:TagResource", "lambda:UntagResource"], Resource = local.admin_lambda_arns },
    { Effect = "Allow", Action = ["iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:TagRole", "iam:UntagRole"], Resource = local.admin_role_arns },
    { Effect = "Allow", Action = ["iam:PassRole"], Resource = [for arn in local.admin_role_arns : arn if !endswith(arn, "admin-private")], Condition = { StringEquals = { "iam:PassedToService" = "lambda.amazonaws.com" } } },
    { Effect = "Allow", Action = ["dynamodb:CreateTable", "dynamodb:UpdateTable", "dynamodb:UpdateContinuousBackups", "dynamodb:UpdateTimeToLive", "dynamodb:TagResource", "dynamodb:UntagResource"], Resource = local.admin_control_arn },
    { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:PutRetentionPolicy", "logs:TagLogGroup", "logs:UntagLogGroup"], Resource = [for arn in local.admin_log_arns : "${arn}:*"] },
    { Effect = "Allow", Action = ["logs:TagResource", "logs:UntagResource"], Resource = local.admin_log_arns },
    { Effect = "Allow", Action = ["cloudfront:CreateFunction", "cloudfront:UpdateFunction", "cloudfront:PublishFunction", "cloudfront:TagResource", "cloudfront:UntagResource"], Resource = local.admin_function_arn },
    ], [for statement in [
      { Effect = "Allow", Action = ["sns:Subscribe"], Resource = local.admin_topic_arn, Condition = { StringEquals = { "sns:Protocol" = "lambda", "sns:Endpoint" = "arn:aws:lambda:eu-north-1:${var.account_id}:function:energy-demo-aws-admin-events" } } },
      { Effect = "Allow", Action = ["sns:Unsubscribe", "sns:SetSubscriptionAttributes"], Resource = "${local.admin_topic_arn}:*" }
  ] : statement if var.admin_email_testing_enabled])
}
resource "aws_iam_policy" "github_admin" {
  for_each = var.enable_admin && var.enable_admin_ci ? toset(["read", "write", "create"]) : toset([])
  name     = "energy-demo-admin-ci-${each.key}"
  path     = "/energy-demo-bootstrap/"
  policy = jsonencode({ Version = "2012-10-17", Statement = concat(
    [for statement in local.admin_ci_read : statement if each.key == "read"],
    [for statement in local.admin_ci_write : statement if each.key == "write"],
    [for name in(var.admin_email_testing_enabled ? ["admin", "email", "events", "private"] : ["admin", "private"]) : {
      Effect    = "Allow", Action = ["iam:CreateRole"], Resource = "arn:aws:iam::${var.account_id}:role/energy-demo-aws/admin-${name}",
      Condition = { StringEquals = { "iam:PermissionsBoundary" = aws_iam_policy.admin_boundary[name].arn } }
  } if each.key == "create"]) })
}
resource "aws_iam_role_policy_attachment" "github_admin" {
  for_each   = var.enable_admin && var.enable_admin_ci ? { plan_read = ["plan", "read"], deploy_read = ["deploy", "read"], deploy_write = ["deploy", "write"], deploy_create = ["deploy", "create"] } : {}
  role       = aws_iam_role.github[each.value[0]].name
  policy_arn = aws_iam_policy.github_admin[each.value[1]].arn
}
