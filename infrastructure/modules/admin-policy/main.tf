variable "account_id" { type = string }
variable "pool_id" { type = string }
variable "sender" { type = string }
variable "recipients" { type = set(string) }

locals {
  prefix  = "arn:aws"
  base    = "energy-demo-aws"
  control = "arn:aws:dynamodb:eu-north-1:${var.account_id}:table/${local.base}-admin-control"
  public  = "arn:aws:dynamodb:eu-north-1:${var.account_id}:table/${local.base}-public-energy"
  private = "arn:aws:dynamodb:eu-north-1:${var.account_id}:table/${local.base}-user-energy"
  pool    = "arn:aws:cognito-idp:eu-north-1:${var.account_id}:userpool/${var.pool_id}"
  role    = "arn:aws:iam::${var.account_id}:role/energy-demo-aws/admin-private"
  policies = {
    admin = [
      { Effect = "Allow", Action = ["cognito-idp:AdminGetUser", "cognito-idp:AdminListGroupsForUser", "cognito-idp:ListUsers", "cognito-idp:DescribeUserPool", "cognito-idp:AdminInitiateAuth", "cognito-idp:AdminRespondToAuthChallenge"], Resource = local.pool },
      { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"], Resource = local.control, Condition = { "ForAllValues:StringLike" = { "dynamodb:LeadingKeys" = ["PROOF#*", "CHALLENGE#*", "CURSOR#*", "AUTH#*", "AUDIT#*"] } } },
      { Effect = "Allow", Action = ["dynamodb:Query"], Resource = local.public, Condition = { "ForAllValues:StringEquals" = { "dynamodb:LeadingKeys" = ["PUBLIC"] } } },
      { Effect = "Allow", Action = ["dynamodb:DescribeTable"], Resource = [local.public, local.control] },
      { Effect = "Allow", Action = ["ses:GetAccount"], Resource = "*", Condition = { StringEquals = { "aws:RequestedRegion" = "eu-north-1" } } },
      { Effect = "Allow", Action = ["sts:AssumeRole", "sts:TagSession"], Resource = local.role }
    ]
    email = [
      { Effect = "Allow", Action = ["cognito-idp:AdminGetUser", "cognito-idp:AdminListGroupsForUser"], Resource = local.pool },
      { Effect = "Allow", Action = ["dynamodb:GetItem"], Resource = local.control, Condition = { "ForAllValues:StringLike" = { "dynamodb:LeadingKeys" = ["PROOF#*", "EMAIL#*"] } } },
      { Effect = "Allow", Action = ["dynamodb:PutItem", "dynamodb:UpdateItem"], Resource = local.control, Condition = { "ForAllValues:StringLike" = { "dynamodb:LeadingKeys" = ["EMAIL#*", "SENDDAY#*", "SENDMIN#*"] } } },
      { Effect = "Allow", Action = ["ses:GetEmailIdentity"], Resource = [for address in setunion(var.recipients, toset([var.sender])) : "arn:aws:ses:eu-north-1:${var.account_id}:identity/${address}"] },
      { Effect = "Allow", Action = ["ses:SendEmail"], Resource = ["arn:aws:ses:eu-north-1:${var.account_id}:identity/${var.sender}", "arn:aws:ses:eu-north-1:${var.account_id}:configuration-set/energy-demo-aws-admin"], Condition = { StringEquals = { "ses:FromAddress" = var.sender }, "ForAllValues:StringEquals" = { "ses:Recipients" = sort(tolist(var.recipients)) } } }
    ]
    events = [
      { Effect = "Allow", Action = ["dynamodb:UpdateItem"], Resource = local.control, Condition = { "ForAllValues:StringLike" = { "dynamodb:LeadingKeys" = ["EMAIL#*"] } } }
    ]
    private = [
      { Effect = "Allow", Action = ["dynamodb:Query"], Resource = local.private, Condition = { "ForAllValues:StringEquals" = { "dynamodb:LeadingKeys" = ["$${aws:PrincipalTag/user_sub}"] } } }
    ]
  }
}

output "policies" {
  value = { for name, statements in local.policies : name => jsonencode({
    Version = "2012-10-17"
    Statement = concat(statements, name == "private" ? [] : [{
      Effect   = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"],
      Resource = "arn:aws:logs:eu-north-1:${var.account_id}:log-group:/aws/lambda/energy-demo-aws-admin-${name}:*"
    }])
  }) }
}
