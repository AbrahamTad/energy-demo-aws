# Administrator-reviewed Contact CI policy extension, separate from runtime boundaries.
variable "account_id" { type = string }
variable "key_arn" { type = string }
variable "mapping_ids" { type = map(string) }
locals {
  kinds          = ["api", "relay", "worker", "admin", "events"]
  prefix         = "energy-demo-aws-contact"
  regional       = "eu-north-1:${var.account_id}"
  function_arns  = [for k in local.kinds : "arn:aws:lambda:${local.regional}:function:${local.prefix}-${k}"]
  role_arns      = [for k in local.kinds : "arn:aws:iam::${var.account_id}:role/energy-demo-aws/contact-${k}"]
  log_group_arns = [for k in local.kinds : "arn:aws:logs:${local.regional}:log-group:/aws/lambda/${local.prefix}-${k}"]
  table_arn      = "arn:aws:dynamodb:${local.regional}:table/${local.prefix}"
  queue_arns = [for q in [".fifo", "-dlq.fifo", "-stream-failures", "-sns-failures", "-event-processing-failures"] :
  "arn:aws:sqs:${local.regional}:${local.prefix}${q}"]
  topic_arn = "arn:aws:sns:${local.regional}:${local.prefix}-events"
  alarm_names = concat(
    [for k in ["worker", "stream", "sns", "events"] : "${local.prefix}-${k}-failures"],
    [for k in ["worker", "reconcile", "events", "destination", "stream_destination", "schedule", "sns_redrive"] : "${local.prefix}-${k}-errors"],
    [for k in ["uncertain-delivery", "failed-delivery", "reconcile-missing", "PendingJobs", "UnconfirmedJobs"] : "${local.prefix}-${k}"]
  )
  mapping_arns = [for k in sort(keys(var.mapping_ids)) : "arn:aws:lambda:${local.regional}:event-source-mapping:${var.mapping_ids[k]}"]
  context = {
    mapping_arns  = jsonencode(local.mapping_arns)
    function_arns = jsonencode(local.function_arns)
    mapping_update_statements = join(",", [for k, id in var.mapping_ids : jsonencode({
      Sid       = "Contact${title(k)}MappingUpdate"
      Effect    = "Allow"
      Action    = ["lambda:UpdateEventSourceMapping"]
      Resource  = "arn:aws:lambda:${local.regional}:event-source-mapping:${id}"
      Condition = { ArnEquals = { "lambda:FunctionArn" = "arn:aws:lambda:${local.regional}:function:${local.prefix}-${k == "stream" ? "relay" : "worker"}" } }
    })])
    worker_function   = jsonencode(local.function_arns[2])
    events_function   = jsonencode(local.function_arns[4])
    relay_function    = jsonencode(local.function_arns[1])
    role_arns         = jsonencode(local.role_arns)
    log_group_arns    = jsonencode(local.log_group_arns)
    log_stream_arns   = jsonencode([for a in local.log_group_arns : "${a}:*"])
    table_arn         = jsonencode(local.table_arn)
    queue_arns        = jsonencode(local.queue_arns)
    topic_arn         = jsonencode(local.topic_arn)
    subscription_arn  = jsonencode("${local.topic_arn}:*")
    configuration_arn = jsonencode("arn:aws:ses:${local.regional}:configuration-set/${local.prefix}")
    secret_arn        = jsonencode("arn:aws:secretsmanager:${local.regional}:secret:energy-demo/contact-??????")
    key_arn           = jsonencode(var.key_arn)
    rule_arn          = jsonencode("arn:aws:events:${local.regional}:rule/${local.prefix}-reconcile")
    alarm_arns        = jsonencode([for n in local.alarm_names : "arn:aws:cloudwatch:${local.regional}:alarm:${n}"])
    edge_arn          = jsonencode("arn:aws:cloudfront::${var.account_id}:function/${local.prefix}-viewer")
    create_statements = jsonencode([for k in local.kinds : {
      Sid      = "CreateContact${title(k)}"
      Effect   = "Allow"
      Action   = ["iam:CreateRole"]
      Resource = "arn:aws:iam::${var.account_id}:role/energy-demo-aws/contact-${k}"
      Condition = { StringEquals = {
        "iam:PermissionsBoundary" = "arn:aws:iam::${var.account_id}:policy/energy-demo-bootstrap/contact-${k}-boundary"
      } }
    }])
  }
  policies = { for name in ["read-runtime", "read-delivery", "write-runtime", "write-delivery", "create", "guard"] :
    name => templatefile("${path.module}/${name}.json.tftpl", local.context)
  }
}
output "policies" { value = local.policies }
