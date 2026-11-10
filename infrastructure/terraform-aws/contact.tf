# Contact is independently opt-in. No changes to existing Cognito, tables or SES identities.
variable "enable_contact" {
  type    = bool
  default = false
}
variable "contact_sender" {
  type    = string
  default = ""
}
variable "contact_sender_display_name" {
  description = "Printable ASCII display name for both Contact email kinds."
  type        = string
  default     = "EnergyDemo Support"
  validation {
    condition     = can(regex("^[ -~]{1,80}$", var.contact_sender_display_name)) && length(trimspace(var.contact_sender_display_name)) > 0
    error_message = "Contact sender display name must be 1-80 printable ASCII characters, without control characters."
  }
}
variable "contact_reply_to" {
  description = "Bare reply mailbox; empty uses the configured verified sender."
  type        = string
  default     = ""
  validation {
    condition     = var.contact_reply_to == "" || can(regex("^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)+$", var.contact_reply_to))
    error_message = "Contact Reply-To must be one bare ASCII mailbox, without display names or headers."
  }
}
variable "contact_admin_email" {
  type    = string
  default = ""
}
variable "contact_hostnames" {
  type    = set(string)
  default = []
}
variable "contact_customer_email_enabled" {
  type    = bool
  default = false
}
variable "contact_alarm_topic_arn" {
  description = "Approved, subscribed SNS alarm topic in this account/eu-north-1; required when Contact is enabled."
  type        = string
  default     = ""
}
variable "contact_origin_token" {
  description = "Independent 32-byte random hex origin credential; secret in protected state/plan, never frontend."
  type        = string
  default     = ""
  sensitive   = true
}
variable "contact_site_origin" {
  description = "Approved HTTPS origin of this EnergyDemo CloudFront distribution."
  type        = string
  default     = ""
}
variable "contact_email_sending_enabled" {
  description = "Separate approval required: enables ALL Contact email, including admin notifications."
  type        = bool
  default     = false
}
module "contact_policy" {
  source          = "../modules/contact-policy"
  account_id      = var.account_id
  sender          = var.contact_sender
  admin_email     = var.contact_admin_email
  sending_enabled = var.contact_email_sending_enabled
}
resource "aws_dynamodb_table" "contact" {
  count                       = var.enable_contact ? 1 : 0
  name                        = "${local.name}-contact"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "pk"
  range_key                   = "sk"
  stream_enabled              = true
  stream_view_type            = "KEYS_ONLY"
  deletion_protection_enabled = true
  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
  attribute {
    name = "inbox"
    type = "S"
  }
  attribute {
    name = "order"
    type = "S"
  }
  global_secondary_index {
    name            = "inbox"
    hash_key        = "inbox"
    range_key       = "order"
    projection_type = "KEYS_ONLY"
  }
  server_side_encryption { enabled = true }
  point_in_time_recovery { enabled = true }
  ttl {
    attribute_name = "expires"
    enabled        = true
  }
  on_demand_throughput {
    max_read_request_units  = 10
    max_write_request_units = 10
  }
  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = can(regex("^arn:aws:sns:eu-north-1:${var.account_id}:[A-Za-z0-9_-]+$", var.contact_alarm_topic_arn))
      error_message = "Contact activation requires an approved same-account standard SNS alarm topic with working subscribers."
    }
    precondition {
      condition     = can(regex("^[a-f0-9]{64}$", var.contact_origin_token))
      error_message = "Contact requires an independently generated 32-byte origin credential."
    }
    precondition {
      condition     = var.contact_site_origin == "https://${aws_cloudfront_distribution.frontend.domain_name}" && var.contact_hostnames == toset([aws_cloudfront_distribution.frontend.domain_name])
      error_message = "Approve the exact EnergyDemo distribution origin and matching Turnstile hostname."
    }
    precondition {
      condition     = (!var.contact_customer_email_enabled || var.contact_email_sending_enabled) && (var.contact_email_sending_enabled || !var.admin_email_testing_enabled)
      error_message = "Customer sending requires separate Contact approval; Contact no-send also forbids Admin email testing."
    }
    precondition {
      condition     = var.enable_admin && length(var.contact_hostnames) > 0 && can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.contact_sender)) && can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.contact_admin_email))
      error_message = "Contact activation requires reviewed admin access, approved hostnames and verified sender/admin inbox."
    }
  }
}
resource "aws_secretsmanager_secret" "contact" {
  count                   = var.enable_contact ? 1 : 0
  name                    = "energy-demo/contact"
  recovery_window_in_days = 30
  lifecycle { prevent_destroy = true }
  # No secret_version: value provisioned separately, never in Git or Terraform state.
}
resource "aws_sqs_queue" "contact_dlq" {
  count                     = var.enable_contact ? 1 : 0
  name                      = "${local.name}-contact-dlq.fifo"
  fifo_queue                = true
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
  lifecycle { prevent_destroy = true }
}
resource "aws_sqs_queue" "contact" {
  count                      = var.enable_contact ? 1 : 0
  name                       = "${local.name}-contact.fifo"
  fifo_queue                 = true
  sqs_managed_sse_enabled    = true
  visibility_timeout_seconds = 180
  message_retention_seconds  = 1209600
  redrive_policy             = jsonencode({ deadLetterTargetArn = aws_sqs_queue.contact_dlq[0].arn, maxReceiveCount = 5 })
  lifecycle { prevent_destroy = true }
}
locals {
  contact_handlers = var.enable_contact ? { api = "contact_api.lambda_handler", relay = "contact_jobs.relay", worker = "contact_jobs.worker", admin = "contact_admin.lambda_handler", events = "contact_events.lambda_handler" } : {}
  contact_routes = var.enable_contact ? {
    submit = { method = "POST", path = "/api/contact", handler = "api" }
    list   = { method = "GET", path = "/api/admin/messages", handler = "admin" }
    detail = { method = "GET", path = "/api/admin/messages/{id}", handler = "admin" }
    status = { method = "POST", path = "/api/admin/messages/{id}/status", handler = "admin" }
  } : {}
}
resource "aws_iam_role" "contact" {
  for_each             = local.contact_handlers
  name                 = "contact-${each.key}"
  path                 = "/energy-demo-aws/"
  permissions_boundary = "arn:aws:iam::${var.account_id}:policy/energy-demo-bootstrap/contact-${each.key}-boundary"
  assume_role_policy   = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }] })
}
resource "aws_iam_role_policy" "contact" {
  for_each = local.contact_handlers
  name     = "contact-${each.key}"
  role     = aws_iam_role.contact[each.key].id
  policy   = module.contact_policy.policies[each.key]
}
resource "aws_cloudwatch_log_group" "contact" {
  for_each          = local.contact_handlers
  name              = "/aws/lambda/${local.name}-contact-${each.key}"
  retention_in_days = 7
}
resource "aws_lambda_function" "contact" {
  for_each                       = local.contact_handlers
  function_name                  = "${local.name}-contact-${each.key}"
  handler                        = each.value
  role                           = aws_iam_role.contact[each.key].arn
  runtime                        = "python3.12"
  timeout                        = 20
  memory_size                    = 128
  reserved_concurrent_executions = each.key == "worker" ? (var.contact_email_sending_enabled ? 1 : 0) : -1
  filename                       = "${path.module}/../../artifacts/aws/lambda.zip"
  source_code_hash               = filebase64sha256("${path.module}/../../artifacts/aws/lambda.zip")
  environment {
    variables = {
      CONTACT_TABLE                  = aws_dynamodb_table.contact[0].name
      CONTACT_SECRET_ARN             = aws_secretsmanager_secret.contact[0].arn
      CONTACT_HOSTNAMES              = jsonencode(sort(tolist(var.contact_hostnames)))
      CONTACT_QUEUE_URL              = aws_sqs_queue.contact[0].url
      CONTACT_SENDER                 = var.contact_sender
      CONTACT_SENDER_DISPLAY_NAME    = var.contact_sender_display_name
      CONTACT_REPLY_TO               = var.contact_reply_to != "" ? var.contact_reply_to : var.contact_sender
      CONTACT_ADMIN_EMAIL            = var.contact_admin_email
      CONTACT_SITE_ORIGIN            = var.contact_site_origin
      CONTACT_ORIGIN_TOKEN_SHA256    = sha256(var.contact_origin_token)
      CONTACT_EMAIL_SENDING_ENABLED  = tostring(var.contact_email_sending_enabled)
      CONTACT_CUSTOMER_EMAIL_ENABLED = tostring(var.contact_customer_email_enabled)
      CONTACT_SES_CONFIG             = aws_sesv2_configuration_set.contact[0].configuration_set_name
      CONTACT_TOPIC_ARN              = aws_sns_topic.contact[0].arn
      COGNITO_USER_POOL_ID           = var.cognito_user_pool_id
      COGNITO_CLIENT_ID              = var.cognito_client_id
      ADMIN_CONTROL_TABLE            = var.enable_admin ? aws_dynamodb_table.admin_control[0].name : ""
    }
  }
  depends_on = [aws_cloudwatch_log_group.contact, aws_iam_role_policy.contact]
}
resource "aws_lambda_event_source_mapping" "contact_stream" {
  count                         = var.enable_contact ? 1 : 0
  event_source_arn              = aws_dynamodb_table.contact[0].stream_arn
  function_name                 = aws_lambda_function.contact["relay"].arn
  starting_position             = "TRIM_HORIZON"
  batch_size                    = 10
  function_response_types       = ["ReportBatchItemFailures"]
  maximum_retry_attempts        = 10
  maximum_record_age_in_seconds = 86400
  destination_config {
    on_failure { destination_arn = aws_sqs_queue.contact_stream_dlq[0].arn }
  }
}
resource "aws_lambda_event_source_mapping" "contact_queue" {
  enabled                 = var.contact_email_sending_enabled
  count                   = var.enable_contact ? 1 : 0
  event_source_arn        = aws_sqs_queue.contact[0].arn
  function_name           = aws_lambda_function.contact["worker"].arn
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]
}
resource "aws_apigatewayv2_integration" "contact" {
  for_each               = var.enable_contact ? toset(["api", "admin"]) : toset([])
  api_id                 = aws_apigatewayv2_api.energy.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = aws_lambda_function.contact[each.key].invoke_arn
  payload_format_version = "2.0"
}
resource "aws_apigatewayv2_route" "contact" {
  for_each             = local.contact_routes
  api_id               = aws_apigatewayv2_api.energy.id
  route_key            = "${each.value.method} ${each.value.path}"
  target               = "integrations/${aws_apigatewayv2_integration.contact[each.value.handler].id}"
  authorization_type   = each.key == "submit" ? "NONE" : "JWT"
  authorizer_id        = each.key == "submit" ? null : aws_apigatewayv2_authorizer.users.id
  authorization_scopes = each.key == "submit" ? [] : ["aws.cognito.signin.user.admin"]
}
resource "aws_lambda_permission" "contact_api" {
  for_each       = local.contact_routes
  statement_id   = "Contact${each.key}"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.contact[each.value.handler].function_name
  principal      = "apigateway.amazonaws.com"
  source_account = var.account_id
  source_arn     = "${aws_apigatewayv2_api.energy.execution_arn}/*/${each.value.method}${replace(each.value.path, "{id}", "*")}"
}
resource "aws_sesv2_configuration_set" "contact" {
  count                  = var.enable_contact ? 1 : 0
  configuration_set_name = "${local.name}-contact"
  suppression_options { suppressed_reasons = ["BOUNCE", "COMPLAINT"] }
}
resource "aws_sns_topic" "contact" {
  count             = var.enable_contact ? 1 : 0
  name              = "${local.name}-contact-events"
  kms_master_key_id = aws_kms_key.contact[0].arn
}
resource "aws_sns_topic_policy" "contact" {
  count = var.enable_contact ? 1 : 0
  arn   = aws_sns_topic.contact[0].arn
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ses.amazonaws.com" }, Action = "sns:Publish", Resource = aws_sns_topic.contact[0].arn,
  Condition = { StringEquals = { "AWS:SourceAccount" = var.account_id }, ArnEquals = { "AWS:SourceArn" = aws_sesv2_configuration_set.contact[0].arn } } }] })
}
resource "aws_sesv2_configuration_set_event_destination" "contact" {
  count                  = var.enable_contact ? 1 : 0
  configuration_set_name = aws_sesv2_configuration_set.contact[0].configuration_set_name
  event_destination_name = "contact-status"
  event_destination {
    enabled              = true
    matching_event_types = ["SEND", "REJECT", "BOUNCE", "COMPLAINT", "DELIVERY", "DELIVERY_DELAY", "RENDERING_FAILURE"]
    sns_destination { topic_arn = aws_sns_topic.contact[0].arn }
  }
  depends_on = [aws_sns_topic_policy.contact]
}
resource "aws_lambda_permission" "contact_events" {
  count          = var.enable_contact ? 1 : 0
  statement_id   = "ContactSESEvents"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.contact["events"].function_name
  principal      = "sns.amazonaws.com"
  source_account = var.account_id
  source_arn     = aws_sns_topic.contact[0].arn
}
resource "aws_sns_topic_subscription" "contact_events" {
  count          = var.enable_contact ? 1 : 0
  topic_arn      = aws_sns_topic.contact[0].arn
  protocol       = "lambda"
  endpoint       = aws_lambda_function.contact["events"].arn
  redrive_policy = jsonencode({ deadLetterTargetArn = aws_sqs_queue.contact_sns_dlq[0].arn })
  depends_on     = [aws_lambda_permission.contact_events, aws_sqs_queue_policy.contact_sns_dlq]
}

# Separate stages: SNS cannot deliver to Lambda versus Lambda accepts but cannot process.
resource "aws_sqs_queue" "contact_sns_dlq" {
  count                             = var.enable_contact ? 1 : 0
  name                              = "${local.name}-contact-sns-failures"
  fifo_queue                        = false
  kms_master_key_id                 = aws_kms_key.contact[0].arn
  kms_data_key_reuse_period_seconds = 300
  message_retention_seconds         = 1209600
  lifecycle { prevent_destroy = true }
}
resource "aws_sqs_queue_policy" "contact_sns_dlq" {
  count     = var.enable_contact ? 1 : 0
  queue_url = aws_sqs_queue.contact_sns_dlq[0].url
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Service = "sns.amazonaws.com" }, Action = "sqs:SendMessage",
    Resource  = aws_sqs_queue.contact_sns_dlq[0].arn,
    Condition = { ArnEquals = { "aws:SourceArn" = aws_sns_topic.contact[0].arn }, StringEquals = { "aws:SourceAccount" = var.account_id } }
  }] })
}
resource "aws_sqs_queue" "contact_event_processing_dlq" {
  count                     = var.enable_contact ? 1 : 0
  name                      = "${local.name}-contact-event-processing-failures"
  fifo_queue                = false
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
  lifecycle { prevent_destroy = true }
}
resource "aws_lambda_function_event_invoke_config" "contact_events" {
  count                        = var.enable_contact ? 1 : 0
  function_name                = aws_lambda_function.contact["events"].function_name
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 21600
  destination_config {
    on_failure { destination = aws_sqs_queue.contact_event_processing_dlq[0].arn }
  }
}

resource "aws_kms_key" "contact" {
  count                   = var.enable_contact ? 1 : 0
  description             = "Contact SES event encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  lifecycle { prevent_destroy = true }
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Principal = { AWS = "arn:aws:iam::${var.account_id}:root" }, Action = "kms:*", Resource = "*" },
    { Effect = "Allow", Principal = { Service = "ses.amazonaws.com" }, Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = "*",
    Condition = { StringEquals = { "aws:SourceAccount" = var.account_id }, ArnEquals = { "aws:SourceArn" = aws_sesv2_configuration_set.contact[0].arn } } },
    { Effect = "Allow", Principal = { Service = "sns.amazonaws.com" }, Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = "*",
    Condition = { StringEquals = { "aws:SourceAccount" = var.account_id }, ArnEquals = { "aws:SourceArn" = "arn:aws:sns:eu-north-1:${var.account_id}:${local.name}-contact-events" } } }
  ] })
}
resource "aws_cloudwatch_event_rule" "contact_reconcile" {
  count               = var.enable_contact ? 1 : 0
  name                = "${local.name}-contact-reconcile"
  schedule_expression = "rate(15 minutes)"
}
resource "aws_cloudwatch_event_target" "contact_reconcile" {
  count = var.enable_contact ? 1 : 0
  rule  = aws_cloudwatch_event_rule.contact_reconcile[0].name
  arn   = aws_lambda_function.contact["relay"].arn
}
resource "aws_lambda_permission" "contact_reconcile" {
  count          = var.enable_contact ? 1 : 0
  statement_id   = "ContactReconcile"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.contact["relay"].function_name
  principal      = "events.amazonaws.com"
  source_account = var.account_id
  source_arn     = aws_cloudwatch_event_rule.contact_reconcile[0].arn
}

# Lambda stream failure destinations must be standard queues, not FIFO.
resource "aws_sqs_queue" "contact_stream_dlq" {
  count                     = var.enable_contact ? 1 : 0
  name                      = "${local.name}-contact-stream-failures"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
  lifecycle { prevent_destroy = true }
}
resource "aws_cloudwatch_metric_alarm" "contact_dlq" {
  for_each = var.enable_contact ? {
    worker = aws_sqs_queue.contact_dlq[0].name, stream = aws_sqs_queue.contact_stream_dlq[0].name,
    sns    = aws_sqs_queue.contact_sns_dlq[0].name, events = aws_sqs_queue.contact_event_processing_dlq[0].name
  } : {}
  alarm_name          = "${local.name}-contact-${each.key}-failures"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.contact_alarm_topic_arn]
  ok_actions          = [var.contact_alarm_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "contact_uncertain" {
  count               = var.enable_contact ? 1 : 0
  alarm_name          = "${local.name}-contact-uncertain-delivery"
  namespace           = "EnergyDemo/Contact"
  metric_name         = "UncertainJobs"
  dimensions          = { Service = "Contact" }
  statistic           = "Maximum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "ignore"
  alarm_actions       = [var.contact_alarm_topic_arn]
}
resource "aws_cloudwatch_metric_alarm" "contact_failed" {
  count               = var.enable_contact ? 1 : 0
  alarm_name          = "${local.name}-contact-failed-delivery"
  namespace           = "EnergyDemo/Contact"
  metric_name         = "FailedJobs"
  dimensions          = { Service = "Contact" }
  statistic           = "Maximum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "ignore"
  alarm_actions       = [var.contact_alarm_topic_arn]
}
resource "aws_cloudwatch_metric_alarm" "contact_reconcile_heartbeat" {
  count               = var.enable_contact ? 1 : 0
  alarm_name          = "${local.name}-contact-reconcile-missing"
  namespace           = "EnergyDemo/Contact"
  metric_name         = "ReconcileSuccess"
  dimensions          = { Service = "Contact" }
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [var.contact_alarm_topic_arn]
}
locals {
  contact_failure_metrics = {
    worker             = { namespace = "AWS/Lambda", metric = "Errors", dimensions = { FunctionName = "${local.name}-contact-worker" } }
    reconcile          = { namespace = "AWS/Lambda", metric = "Errors", dimensions = { FunctionName = "${local.name}-contact-relay" } }
    events             = { namespace = "AWS/Lambda", metric = "Errors", dimensions = { FunctionName = "${local.name}-contact-events" } }
    destination        = { namespace = "AWS/Lambda", metric = "DestinationDeliveryFailures", dimensions = { FunctionName = "${local.name}-contact-events" } }
    stream_destination = { namespace = "AWS/Lambda", metric = "DestinationDeliveryFailures", dimensions = { FunctionName = "${local.name}-contact-relay" } }
    schedule           = { namespace = "AWS/Events", metric = "FailedInvocations", dimensions = { RuleName = "${local.name}-contact-reconcile" } }
    sns_redrive        = { namespace = "AWS/SNS", metric = "NumberOfNotificationsFailedToRedriveToDlq", dimensions = { TopicName = "${local.name}-contact-events" } }
  }
}
resource "aws_cloudwatch_metric_alarm" "contact_failure" {
  for_each            = var.enable_contact ? local.contact_failure_metrics : {}
  alarm_name          = "${local.name}-contact-${each.key}-errors"
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  dimensions          = each.value.dimensions
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.contact_alarm_topic_arn]
}

resource "aws_cloudfront_function" "contact_viewer" {
  count   = var.enable_contact ? 1 : 0
  name    = "${local.name}-contact-viewer"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = file("${path.module}/contact-viewer.js")
}
resource "aws_cloudwatch_metric_alarm" "contact_backlog" {
  for_each            = var.enable_contact ? toset(["PendingJobs", "UnconfirmedJobs"]) : toset([])
  alarm_name          = "${local.name}-contact-${each.key}"
  namespace           = "EnergyDemo/Contact"
  metric_name         = each.key
  dimensions          = { Service = "Contact" }
  statistic           = "Maximum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "ignore"
  alarm_actions       = [var.contact_alarm_topic_arn]
  ok_actions          = [var.contact_alarm_topic_arn]
}
