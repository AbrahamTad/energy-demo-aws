# Mock provider: these plans never authenticate to AWS or access the backend.
mock_provider "aws" {
  override_during = plan
  mock_resource "aws_sqs_queue" {
    defaults = {
      arn = "arn:aws:sqs:eu-north-1:123456789012:fixture-queue"
      url = "https://sqs.eu-north-1.amazonaws.com/123456789012/fixture-queue"
    }
  }
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:eu-north-1:123456789012:fixture-topic" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:eu-north-1:123456789012:key/11111111-1111-1111-1111-111111111111" }
  }
  mock_resource "aws_sesv2_configuration_set" {
    defaults = { arn = "arn:aws:ses:eu-north-1:123456789012:configuration-set/energy-demo-aws-contact" }
  }
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
    defaults = {
      arn         = "arn:aws:cloudfront::123456789012:distribution/TESTFIXTURE"
      domain_name = "energy.example.invalid"
    }
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
override_resource {
  target          = aws_sqs_queue.contact_sns_dlq[0]
  override_during = plan
  values = {
    arn = "arn:aws:sqs:eu-north-1:123456789012:energy-demo-aws-contact-sns-failures"
    url = "https://sqs.eu-north-1.amazonaws.com/123456789012/energy-demo-aws-contact-sns-failures"
  }
}
override_resource {
  target          = aws_sqs_queue.contact_event_processing_dlq[0]
  override_during = plan
  values = {
    arn = "arn:aws:sqs:eu-north-1:123456789012:energy-demo-aws-contact-event-processing-failures"
    url = "https://sqs.eu-north-1.amazonaws.com/123456789012/energy-demo-aws-contact-event-processing-failures"
  }
}

variables {
  budget_email            = "budget@example.invalid"
  account_id              = "123456789012"
  enable_admin            = true
  admin_cognito_client_id = "fixtureadminclient"
  admin_email_sender      = "sender@example.invalid"
  admin_email_recipients  = ["admin@example.invalid"]
  enable_contact          = true
  contact_origin_token    = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  contact_site_origin     = "https://energy.example.invalid"
  contact_sender          = "sender@example.invalid"
  contact_admin_email     = "admin@example.invalid"
  contact_hostnames       = ["energy.example.invalid"]
  contact_alarm_topic_arn = "arn:aws:sns:eu-north-1:123456789012:contact-operator-alerts"
}
run "contact_security" {
  command = plan
  assert {
    condition     = !aws_lambda_event_source_mapping.contact_queue[0].enabled && aws_lambda_function.contact["worker"].reserved_concurrent_executions == 0 && aws_lambda_function.contact["worker"].environment[0].variables.CONTACT_EMAIL_SENDING_ENABLED == "false" && jsondecode(module.contact_policy.policies["worker"]).Statement[0].Effect == "Deny"
    error_message = "No-send must disable the consumer, throttle worker concurrency to zero and deny SES in IAM."
  }
  assert {
    condition     = alltrue([for a in aws_cloudwatch_metric_alarm.contact_backlog : a.alarm_actions == toset([var.contact_alarm_topic_arn]) && a.treat_missing_data == "ignore"]) && length(aws_cloudwatch_metric_alarm.contact_backlog) == 2 && aws_cloudwatch_metric_alarm.contact_failure["worker"].metric_name == "Errors"
    error_message = "Pending, missing confirmation and worker alarms must notify operators."
  }
  assert {
    condition     = length(aws_cloudfront_function.contact_viewer) == 1 && anytrue([for o in aws_cloudfront_distribution.frontend.origin : o.origin_id == "energy-api" && anytrue([for h in o.custom_header : h.name == "X-Energy-Contact-Origin" && h.value == var.contact_origin_token])]) && aws_lambda_function.contact["api"].environment[0].variables.CONTACT_ORIGIN_TOKEN_SHA256 == sha256(var.contact_origin_token)
    error_message = "Contact origin authentication must connect CloudFront to API verification."
  }
  assert {
    condition     = jsondecode(module.contact_policy.policies["relay"]).Statement[3].Resource == "*" && !can(regex("TransactWriteItems|contact-dlq.fifo", module.contact_policy.policies["relay"])) && !can(regex("TransactWriteItems", module.contact_policy.policies["api"]))
    error_message = "ListStreams requires star; remove invalid transaction and unnecessary DLQ permissions."
  }
  assert {
    condition     = aws_lambda_function.contact["worker"].environment[0].variables.CONTACT_SITE_ORIGIN == "https://energy.example.invalid" && aws_lambda_function.contact["worker"].environment[0].variables.CONTACT_SENDER == var.contact_sender && aws_lambda_function.contact["worker"].environment[0].variables.CONTACT_ADMIN_EMAIL == var.contact_admin_email
    error_message = "Contact templates require the owned distribution origin and configured sender/inbox."
  }
  assert {
    condition     = aws_dynamodb_table.contact[0].deletion_protection_enabled && aws_dynamodb_table.contact[0].point_in_time_recovery[0].enabled && aws_dynamodb_table.contact[0].stream_view_type == "KEYS_ONLY"
    error_message = "Inquiries require deletion protection, PITR and keys-only streams."
  }
  assert {
    condition     = aws_apigatewayv2_route.contact["submit"].authorization_type == "NONE" && aws_apigatewayv2_route.contact["detail"].authorization_type == "JWT" && aws_apigatewayv2_route.contact["status"].authorization_type == "JWT"
    error_message = "Only contact submission is public."
  }
  assert {
    condition     = aws_sqs_queue.contact[0].fifo_queue && aws_sqs_queue.contact[0].sqs_managed_sse_enabled && aws_lambda_event_source_mapping.contact_queue[0].batch_size == 1 && !var.contact_customer_email_enabled
    error_message = "Contact delivery must use encrypted FIFO and keep arbitrary customer email off by default."
  }
  assert {
    condition     = !can(regex("ses:SendEmail", module.contact_policy.policies["api"])) && !can(regex("ses:SendEmail", module.contact_policy.policies["admin"])) && can(regex("ses:FromAddress", module.contact_policy.policies["worker"]))
    error_message = "Only the worker may send, from its fixed sender."
  }
  assert {
    condition     = !aws_sqs_queue.contact_sns_dlq[0].fifo_queue && aws_sqs_queue.contact_sns_dlq[0].kms_master_key_id == aws_kms_key.contact[0].arn && aws_sqs_queue.contact_sns_dlq[0].message_retention_seconds == 1209600 && aws_sqs_queue.contact_event_processing_dlq[0].sqs_managed_sse_enabled && aws_sqs_queue.contact_event_processing_dlq[0].message_retention_seconds == 1209600
    error_message = "SES failure queues must be standard, encrypted and retained for 14 days."
  }
  assert {
    condition     = jsondecode(aws_sns_topic_subscription.contact_events[0].redrive_policy).deadLetterTargetArn == aws_sqs_queue.contact_sns_dlq[0].arn && aws_lambda_function_event_invoke_config.contact_events[0].destination_config[0].on_failure[0].destination == aws_sqs_queue.contact_event_processing_dlq[0].arn && aws_lambda_function_event_invoke_config.contact_events[0].maximum_retry_attempts == 2
    error_message = "Both SNS delivery and asynchronous execution failures must be retained."
  }
  assert {
    condition     = jsondecode(aws_sqs_queue_policy.contact_sns_dlq[0].policy).Statement[0].Principal.Service == "sns.amazonaws.com" && jsondecode(aws_sqs_queue_policy.contact_sns_dlq[0].policy).Statement[0].Condition.ArnEquals["aws:SourceArn"] == aws_sns_topic.contact[0].arn && can(regex("sns.amazonaws.com", aws_kms_key.contact[0].policy)) && can(regex("contact-event-processing-failures", module.contact_policy.policies["events"])) && !can(regex("sqs:ReceiveMessage", module.contact_policy.policies["events"]))
    error_message = "Failure publication must be scoped; processing has no automatic recovery consumer."
  }
  assert {
    condition     = length(aws_cloudwatch_metric_alarm.contact_dlq) == 4 && alltrue([for alarm in aws_cloudwatch_metric_alarm.contact_dlq : alarm.alarm_actions == toset([var.contact_alarm_topic_arn])]) && alltrue([for alarm in aws_cloudwatch_metric_alarm.contact_failure : alarm.alarm_actions == toset([var.contact_alarm_topic_arn])]) && aws_cloudwatch_metric_alarm.contact_failed[0].alarm_actions == toset([var.contact_alarm_topic_arn]) && aws_cloudwatch_metric_alarm.contact_uncertain[0].alarm_actions == toset([var.contact_alarm_topic_arn]) && aws_cloudwatch_metric_alarm.contact_reconcile_heartbeat[0].alarm_actions == toset([var.contact_alarm_topic_arn])
    error_message = "Every failure queue, delivery ambiguity and reconciliation alarm must notify operators."
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.contact_failed[0].metric_name == "FailedJobs" && aws_cloudwatch_metric_alarm.contact_failed[0].treat_missing_data == "ignore" && aws_cloudwatch_metric_alarm.contact_uncertain[0].metric_name == "UncertainJobs" && aws_cloudwatch_metric_alarm.contact_reconcile_heartbeat[0].treat_missing_data == "breaching" && aws_cloudwatch_metric_alarm.contact_reconcile_heartbeat[0].evaluation_periods == 3 && aws_cloudwatch_metric_alarm.contact_failure["reconcile"].metric_name == "Errors" && aws_cloudwatch_metric_alarm.contact_failure["destination"].metric_name == "DestinationDeliveryFailures" && aws_cloudwatch_metric_alarm.contact_failure["sns_redrive"].metric_name == "NumberOfNotificationsFailedToRedriveToDlq"
    error_message = "Monitoring must detect missing reconciliation, uncertainty and failed recovery publication."
  }
}
run "contact_requires_alarm_destination" {
  command = plan
  variables { contact_alarm_topic_arn = "" }
  expect_failures = [aws_dynamodb_table.contact[0]]
}
run "contact_rejects_cross_account_alarm_destination" {
  command = plan
  variables { contact_alarm_topic_arn = "arn:aws:sns:eu-north-1:999999999999:operator-alerts" }
  expect_failures = [aws_dynamodb_table.contact[0]]
}
run "contact_defaults_off" {
  command = plan
  variables { enable_contact = false }
  assert {
    condition     = length(aws_lambda_function.contact) == 0 && length(aws_dynamodb_table.contact) == 0
    error_message = "Contact must not provision resources by default."
  }
}

run "contact_rejects_wrong_origin" {
  command = plan
  variables { contact_site_origin = "https://attacker.invalid" }
  expect_failures = [aws_dynamodb_table.contact[0]]
}
run "contact_rejects_wrong_turnstile_hostname" {
  command = plan
  variables { contact_hostnames = ["attacker.invalid"] }
  expect_failures = [aws_dynamodb_table.contact[0]]
}
run "contact_requires_origin_credential" {
  command = plan
  variables { contact_origin_token = "" }
  expect_failures = [aws_dynamodb_table.contact[0]]
}

run "contact_sender_headers" {
  command = plan
  variables {
    contact_reply_to = "support@example.invalid"
  }
  assert {
    condition     = aws_lambda_function.contact["worker"].environment[0].variables.CONTACT_SENDER_DISPLAY_NAME == "EnergyDemo Support" && aws_lambda_function.contact["worker"].environment[0].variables.CONTACT_REPLY_TO == "support@example.invalid" && aws_lambda_function.contact["worker"].environment[0].variables.CONTACT_SENDER == var.contact_sender
    error_message = "Contact sender display name and Reply-To must be configured independently of the bare SES identity."
  }
}
run "contact_sender_reply_fallback" {
  command = plan
  assert {
    condition     = aws_lambda_function.contact["worker"].environment[0].variables.CONTACT_REPLY_TO == var.contact_sender
    error_message = "An empty Reply-To must use the configured sender."
  }
}
run "contact_rejects_sender_name_header_injection" {
  command = plan
  variables { contact_sender_display_name = "EnergyDemo\r\nBcc: victim@example.invalid" }
  expect_failures = [var.contact_sender_display_name]
}
run "contact_rejects_reply_header_injection" {
  command = plan
  variables { contact_reply_to = "support@example.invalid\r\nBcc: victim@example.invalid" }
  expect_failures = [var.contact_reply_to]
}

run "contact_no_send_omits_admin_email" {
  command = plan
  variables {
    admin_email_sender     = ""
    admin_email_recipients = []
  }
  assert {
    condition     = toset(keys(aws_lambda_function.admin)) == toset(["admin"]) && !contains(keys(aws_apigatewayv2_route.admin), "email_post") && !aws_lambda_event_source_mapping.contact_queue[0].enabled && aws_lambda_function.contact["worker"].reserved_concurrent_executions == 0 && aws_lambda_function.contact["worker"].environment[0].variables.CONTACT_CUSTOMER_EMAIL_ENABLED == "false"
    error_message = "Contact must work with no Admin SES configuration while both sending paths remain disabled."
  }
}
run "contact_no_send_rejects_admin_email_testing" {
  command = plan
  variables { admin_email_testing_enabled = true }
  expect_failures = [aws_dynamodb_table.contact[0]]
}
