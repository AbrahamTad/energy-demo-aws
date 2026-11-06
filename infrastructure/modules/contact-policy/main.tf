variable "sending_enabled" {
  type    = bool
  default = false
}
variable "account_id" { type = string }
variable "sender" { type = string }
variable "admin_email" { type = string }
locals {
  policies = {
    api = jsonencode({
      "Version" : "2012-10-17",
      "Statement" : [
        {
          "Effect" : "Allow",
          "Action" : [
            "logs:CreateLogStream",
            "logs:PutLogEvents"
          ],
          "Resource" : "arn:aws:logs:eu-north-1:${var.account_id}:log-group:/aws/lambda/energy-demo-aws-contact-api:*"
        },
        {
          "Effect" : "Allow",
          "Action" : [
            "dynamodb:GetItem",
            "dynamodb:UpdateItem",
            "dynamodb:PutItem"
          ],
          "Resource" : "arn:aws:dynamodb:eu-north-1:${var.account_id}:table/energy-demo-aws-contact"
        },
        {
          "Effect" : "Allow",
          "Action" : [
            "secretsmanager:GetSecretValue"
          ],
          "Resource" : "arn:aws:secretsmanager:eu-north-1:${var.account_id}:secret:energy-demo/contact-??????"
        }
      ]
    })
    relay = jsonencode({
      "Version" : "2012-10-17",
      "Statement" : [
        {
          "Effect" : "Allow",
          "Action" : [
            "logs:CreateLogStream",
            "logs:PutLogEvents"
          ],
          "Resource" : "arn:aws:logs:eu-north-1:${var.account_id}:log-group:/aws/lambda/energy-demo-aws-contact-relay:*"
        },
        {
          "Effect" : "Allow",
          "Action" : [
            "dynamodb:Scan",
            "dynamodb:GetItem",
            "dynamodb:PutItem"
          ],
          "Resource" : "arn:aws:dynamodb:eu-north-1:${var.account_id}:table/energy-demo-aws-contact"
        },
        {
          "Effect" : "Allow",
          "Action" : [
            "dynamodb:DescribeStream",
            "dynamodb:GetRecords",
            "dynamodb:GetShardIterator"
          ],
          "Resource" : "arn:aws:dynamodb:eu-north-1:${var.account_id}:table/energy-demo-aws-contact/stream/*"
        },
        {
          "Effect" : "Allow",
          "Action" : [
            "dynamodb:ListStreams"
          ],
          "Resource" : "*",
          "Condition" : { "StringEquals" : { "aws:RequestedRegion" : "eu-north-1" } }
        },
        {
          "Effect" : "Allow",
          "Action" : [
            "sqs:SendMessage"
          ],
          "Resource" : [
            "arn:aws:sqs:eu-north-1:${var.account_id}:energy-demo-aws-contact.fifo",
            "arn:aws:sqs:eu-north-1:${var.account_id}:energy-demo-aws-contact-stream-failures"
          ]
        }
      ]
    })
    worker = jsonencode({
      "Version" : "2012-10-17",
      "Statement" : concat(var.sending_enabled ? [] : [{ Effect = "Deny", Action = ["ses:SendEmail", "ses:SendRawEmail", "ses:SendBulkEmail"], Resource = "*" }], [
        {
          "Effect" : "Allow",
          "Action" : [
            "logs:CreateLogStream",
            "logs:PutLogEvents"
          ],
          "Resource" : "arn:aws:logs:eu-north-1:${var.account_id}:log-group:/aws/lambda/energy-demo-aws-contact-worker:*"
        },
        {
          "Effect" : "Allow",
          "Action" : [
            "dynamodb:GetItem",
            "dynamodb:UpdateItem"
          ],
          "Resource" : "arn:aws:dynamodb:eu-north-1:${var.account_id}:table/energy-demo-aws-contact"
        },
        {
          "Effect" : "Allow",
          "Action" : [
            "secretsmanager:GetSecretValue"
          ],
          "Resource" : "arn:aws:secretsmanager:eu-north-1:${var.account_id}:secret:energy-demo/contact-??????"
        },
        {
          "Effect" : "Allow",
          "Action" : [
            "sqs:ReceiveMessage",
            "sqs:DeleteMessage",
            "sqs:GetQueueAttributes"
          ],
          "Resource" : "arn:aws:sqs:eu-north-1:${var.account_id}:energy-demo-aws-contact.fifo"
        },
        {
          "Effect" : "Allow",
          "Action" : [
            "ses:GetEmailIdentity"
          ],
          "Resource" : "arn:aws:ses:eu-north-1:${var.account_id}:identity/*"
        },
        {
          "Effect" : "Allow",
          "Action" : [
            "ses:SendEmail"
          ],
          "Resource" : [
            "arn:aws:ses:eu-north-1:${var.account_id}:identity/${var.sender}",
            "arn:aws:ses:eu-north-1:${var.account_id}:configuration-set/energy-demo-aws-contact"
          ],
          "Condition" : {
            "StringEquals" : {
              "ses:FromAddress" : "${var.sender}"
            }
          }
        }
      ])
    })
    admin = jsonencode({
      "Version" : "2012-10-17",
      "Statement" : [
        {
          "Effect" : "Allow",
          "Action" : [
            "logs:CreateLogStream",
            "logs:PutLogEvents"
          ],
          "Resource" : "arn:aws:logs:eu-north-1:${var.account_id}:log-group:/aws/lambda/energy-demo-aws-contact-admin:*"
        },
        {
          "Effect" : "Allow",
          "Action" : [
            "dynamodb:GetItem",
            "dynamodb:Query",
            "dynamodb:UpdateItem"
          ],
          "Resource" : [
            "arn:aws:dynamodb:eu-north-1:${var.account_id}:table/energy-demo-aws-contact",
            "arn:aws:dynamodb:eu-north-1:${var.account_id}:table/energy-demo-aws-contact/index/inbox"
          ]
        },
        {
          "Effect" : "Allow",
          "Action" : [
            "cognito-idp:AdminGetUser",
            "cognito-idp:AdminListGroupsForUser"
          ],
          "Resource" : "arn:aws:cognito-idp:eu-north-1:${var.account_id}:userpool/eu-north-1_6m60ePWS0"
        },
        {
          "Effect" : "Allow",
          "Action" : [
            "dynamodb:GetItem"
          ],
          "Resource" : "arn:aws:dynamodb:eu-north-1:${var.account_id}:table/energy-demo-aws-admin-control"
        }
      ]
    })
    events = jsonencode({
      "Version" : "2012-10-17",
      "Statement" : [
        {
          "Effect" : "Allow",
          "Action" : ["sqs:SendMessage"],
          "Resource" : "arn:aws:sqs:eu-north-1:${var.account_id}:energy-demo-aws-contact-event-processing-failures"
        },
        {
          "Effect" : "Allow",
          "Action" : [
            "logs:CreateLogStream",
            "logs:PutLogEvents"
          ],
          "Resource" : "arn:aws:logs:eu-north-1:${var.account_id}:log-group:/aws/lambda/energy-demo-aws-contact-events:*"
        },
        {
          "Effect" : "Allow",
          "Action" : [
            "dynamodb:GetItem",
            "dynamodb:UpdateItem",
            "dynamodb:PutItem"
          ],
          "Resource" : "arn:aws:dynamodb:eu-north-1:${var.account_id}:table/energy-demo-aws-contact"
        },
        {
          "Effect" : "Allow",
          "Action" : [
            "secretsmanager:GetSecretValue"
          ],
          "Resource" : "arn:aws:secretsmanager:eu-north-1:${var.account_id}:secret:energy-demo/contact-??????"
        }
      ]
    })
  }
}
output "policies" { value = local.policies }
