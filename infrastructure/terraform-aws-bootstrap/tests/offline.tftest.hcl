mock_provider "aws" {
  override_during = plan
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:eu-north-1:123456789012:energy-demo-aws-admin-email" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:eu-north-1:123456789012:key/11111111-1111-4111-8111-111111111111" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:s3:::energy-demo-tfstate-123456789012-eu-north-1" }
  }
  mock_resource "aws_iam_policy" {
    defaults = { arn = "arn:aws:iam::123456789012:policy/energy-demo-bootstrap/lambda-logs-boundary" }
  }
}

run "admin_operator_preparation" {
  command = plan
  variables {
    admin_email_testing_enabled = true
    enable_admin_ci             = true
    enable_admin                = true
    admin_email_sender          = "sender@example.invalid"
    admin_email_recipients      = ["test@example.invalid"]
  }
  assert {
    condition     = length(aws_iam_policy.admin_boundary) == 4 && length(aws_sesv2_email_identity.admin) == 2 && aws_sns_topic.admin_email[0].kms_master_key_id == aws_kms_key.admin_email[0].arn && aws_kms_key.admin_email[0].enable_key_rotation
    error_message = "Admin preparation must provision bounded roles and SES events encrypted with a service-authorized customer key."
  }
  assert {
    condition     = alltrue([for p in aws_iam_policy.github_admin : length(p.policy) < 6144]) && !contains(keys(aws_iam_role_policy_attachment.github_admin), "plan_write") && aws_iam_role_policy_attachment.github_admin["plan_read"].role == aws_iam_role.github["plan"].name
    error_message = "Additional managed CI policies must fit AWS limits and grant the plan role read-only permissions."
  }
  assert {
    condition     = alltrue([for s in jsondecode(aws_iam_policy.github_admin["create"].policy).Statement : contains(s.Action, "iam:CreateRole") && can(s.Condition.StringEquals["iam:PermissionsBoundary"])]) && alltrue(flatten([for p in aws_iam_policy.github_admin : [for s in jsondecode(p.policy).Statement : alltrue([for a in s.Action : !startswith(a, "cognito-idp:") && !startswith(a, "ses:") && !contains(["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan", "dynamodb:PutItem", "dynamodb:UpdateItem"], a)])]]))
    error_message = "CI cannot provision unbounded roles, manage identities, send email or access database items."
  }
}

override_resource {
  target          = aws_iam_policy.user_energy_boundary
  override_during = plan
  values          = { arn = "arn:aws:iam::123456789012:policy/energy-demo-bootstrap/user-energy-boundary" }
}

variables {
  account_id                 = "123456789012" # Offline fixture; never authenticated.
  github_subject_prefix      = "repo:AbrahamTad/energy-demo-aws:"
  existing_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
}

run "scoped_bootstrap" {
  command = plan
  assert {
    condition     = aws_s3_bucket_versioning.state.versioning_configuration[0].status == "Enabled"
    error_message = "State recovery requires S3 versioning."
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.state.block_public_policy
    error_message = "State must never be public."
  }
  assert {
    condition     = jsondecode(aws_iam_role.github["deploy"].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:AbrahamTad/energy-demo-aws:environment:aws-production"
    error_message = "Deployment trust must require the exact protected environment."
  }
  assert {
    condition     = jsondecode(aws_iam_role.github["plan"].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:AbrahamTad/energy-demo-aws:ref:refs/heads/main"
    error_message = "Planning trust must require the exact main branch."
  }
  assert {
    condition     = length(aws_iam_role_policy.github["deploy"].policy) < 10240
    error_message = "IAM inline role policy exceeds the AWS size limit."
  }
  assert {
    condition = alltrue(flatten([
      for s in jsondecode(aws_iam_role_policy.github["deploy"].policy).Statement : [
        for action in s.Action : !startswith(action, "apigateway:") && !startswith(action, "cloudfront:")
      ]
    ]))
    error_message = "Before explicit IDs are configured, CI must have no API/CloudFront access."
  }
}

run "mutations_require_exact_ids" {
  command = plan
  variables {
    deployment_resource_ids = {
      api_id                     = "fixture123"
      cloudfront_distribution_id = "FIXTUREDIST"
      cloudfront_oac_id          = "FIXTUREOAC"
    }
  }
  assert {
    condition     = length(aws_iam_role_policy.github["deploy"].policy) < 10240
    error_message = "The full exact-ID deployment policy must stay within AWS's 10,240-byte inline policy limit."
  }
  assert {
    condition = alltrue([
      for s in jsondecode(aws_iam_role_policy.github["deploy"].policy).Statement :
      toset(s.Resource) == toset(["arn:aws:iam::123456789012:role/energy-demo-aws/lambda-execution", "arn:aws:iam::123456789012:role/energy-demo-aws/user-energy-execution"]) &&
      s.Condition.StringEquals["iam:PassedToService"] == "lambda.amazonaws.com"
      if contains(s.Action, "iam:PassRole")
    ])
    error_message = "Only the two bounded EnergyDemo roles may be passed, only to Lambda."
  }
  assert {
    condition = alltrue([
      for s in jsondecode(aws_iam_role_policy.github["deploy"].policy).Statement :
      length(s.Resource) == 1 && s.Condition.StringEquals["iam:PermissionsBoundary"] == lookup({
        "arn:aws:iam::123456789012:role/energy-demo-aws/lambda-execution"      = "arn:aws:iam::123456789012:policy/energy-demo-bootstrap/lambda-logs-boundary"
        "arn:aws:iam::123456789012:role/energy-demo-aws/user-energy-execution" = "arn:aws:iam::123456789012:policy/energy-demo-bootstrap/user-energy-boundary"
      }, s.Resource[0], "INVALID")
      if contains(s.Action, "iam:CreateRole")
    ])
    error_message = "Each execution role must require its own exact administrator-managed boundary."
  }
  assert {
    condition = alltrue(flatten([
      for s in jsondecode(aws_iam_role_policy.github["deploy"].policy).Statement : [
        for arn in s.Resource : contains([
          "arn:aws:cloudfront::123456789012:distribution/FIXTUREDIST",
          "arn:aws:cloudfront::123456789012:origin-access-control/FIXTUREOAC"
        ], arn)
      ] if anytrue([for action in s.Action : startswith(action, "cloudfront:")])
    ]))
    error_message = "CloudFront access must be limited to the two exact administrator-approved IDs."
  }
  assert {
    condition = alltrue(flatten([
      for s in jsondecode(aws_iam_role_policy.github["deploy"].policy).Statement : [
        for arn in s.Resource : contains([
          "arn:aws:apigateway:eu-north-1::/apis/fixture123",
          "arn:aws:apigateway:eu-north-1::/apis/fixture123/*",
          "arn:aws:apigateway:eu-north-1::/tags/${urlencode("arn:aws:apigateway:eu-north-1::/apis/fixture123")}"
        ], arn)
      ] if anytrue([for action in s.Action : startswith(action, "apigateway:")])
    ]))
    error_message = "API access must be limited to the exact API and its children."
  }
  assert {
    condition = alltrue(flatten([
      for s in jsondecode(aws_iam_role_policy.github["deploy"].policy).Statement : [
        for action in s.Action : !contains([
          "cloudfront:CreateDistribution", "cloudfront:CreateDistributionWithTags",
          "cloudfront:DeleteDistribution", "cloudfront:CreateOriginAccessControl",
          "cloudfront:DeleteOriginAccessControl", "iam:PutRolePermissionsBoundary",
          "iam:DeleteRolePermissionsBoundary", "iam:AttachRolePolicy"
        ], action)
      ]
    ]))
    error_message = "CI may not create/delete distributions or change/remove the IAM boundary."
  }
  assert {
    condition = alltrue([
      for s in jsondecode(aws_iam_role_policy.github["deploy"].policy).Statement :
      !contains(s.Resource, "arn:aws:apigateway:eu-north-1::/apis/fixture123") ||
      alltrue([for action in s.Action : contains(["apigateway:GET", "apigateway:PATCH"], action)])
    ])
    error_message = "The API root must not be creatable or deletable by CI."
  }
}

run "log_group_permissions_use_correct_arns" {
  command = plan
  assert {
    condition = alltrue(flatten([
      for role in ["plan", "deploy"] : [
        for s in jsondecode(aws_iam_role_policy.github[role].policy).Statement : [
          for action in s.Action : s.Resource == (
            contains(["logs:ListTagsForResource", "logs:TagResource", "logs:UntagResource"], action) ? [
              "arn:aws:logs:eu-north-1:123456789012:log-group:/aws/lambda/energy-demo-aws-energy",
              "arn:aws:logs:eu-north-1:123456789012:log-group:/energy-demo-aws/http-api",
              "arn:aws:logs:eu-north-1:123456789012:log-group:/aws/lambda/energy-demo-aws-user-energy"
              ] : [
              "arn:aws:logs:eu-north-1:123456789012:log-group:/aws/lambda/energy-demo-aws-energy:*",
              "arn:aws:logs:eu-north-1:123456789012:log-group:/energy-demo-aws/http-api:*",
              "arn:aws:logs:eu-north-1:123456789012:log-group:/aws/lambda/energy-demo-aws-user-energy:*"
            ]
          ) if startswith(action, "logs:") && action != "logs:DescribeLogGroups"
        ]
      ]
    ]))
    error_message = "Log permissions must cover only the three EnergyDemo groups with the ARN form required by each action."
  }
  assert {
    condition = alltrue([
      for role, actions in {
        plan = ["logs:DescribeLogGroups", "logs:ListTagsForResource", "logs:ListTagsLogGroup"]
        deploy = [
          "logs:DescribeLogGroups", "logs:ListTagsForResource", "logs:ListTagsLogGroup",
          "logs:CreateLogGroup", "logs:DeleteLogGroup", "logs:PutRetentionPolicy", "logs:DeleteRetentionPolicy",
          "logs:TagResource", "logs:UntagResource", "logs:TagLogGroup", "logs:UntagLogGroup"
        ]
        } : sort(flatten([
          for s in jsondecode(aws_iam_role_policy.github[role].policy).Statement : [
            for action in s.Action : action if startswith(action, "logs:")
          ]
      ])) == sort(actions)
    ])
    error_message = "Both roles need tag reads; log mutations must remain exclusive to deploy with no extra actions."
  }
  assert {
    condition = alltrue(flatten([
      for role in ["plan", "deploy"] : [
        for s in jsondecode(aws_iam_role_policy.github[role].policy).Statement :
        s.Resource == ["*"] && s.Condition.StringEquals["aws:RequestedRegion"] == "eu-north-1"
        if contains(s.Action, "logs:DescribeLogGroups")
      ]
    ]))
    error_message = "Log discovery must remain restricted to eu-north-1."
  }
}

run "reject_wildcard_resource_ids" {
  command = plan
  variables {
    deployment_resource_ids = {
      api_id = "*", cloudfront_distribution_id = "*", cloudfront_oac_id = "*"
    }
  }
  expect_failures = [var.deployment_resource_ids]
}

run "reject_wildcard_oidc_subject" {
  command = plan
  variables { github_subject_prefix = "repo:AbrahamTad/*:" }
  expect_failures = [var.github_subject_prefix]
}

run "database_iam_stays_bounded" {
  command = plan
  assert {
    condition = alltrue(flatten([
      for role in ["plan", "deploy"] : [for s in jsondecode(aws_iam_role_policy.github[role].policy).Statement :
        s.Action == ["kms:DescribeKey"] && s.Resource == ["arn:aws:kms:eu-north-1:123456789012:key/*"] &&
        s.Condition.StringEquals["kms:RequestAlias"] == "alias/aws/dynamodb"
        if anytrue([for action in s.Action : startswith(action, "kms:")])
      ]]
    ))
    error_message = "Encryption refresh may only describe the regional AWS-managed DynamoDB alias; no key usage or management grants."
  }
  assert {
    condition = alltrue(flatten([
      for role in ["plan", "deploy"] : [for s in jsondecode(aws_iam_role_policy.github[role].policy).Statement : [
        for action in s.Action : !contains(["dynamodb:Scan", "dynamodb:Query", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem", "dynamodb:DeleteTable"], action)
      ]]
    ]))
    error_message = "CI may manage exact table infrastructure but must never access records or delete tables."
  }
  assert {
    condition = alltrue(flatten([
      for role in ["plan", "deploy"] : [for s in jsondecode(aws_iam_role_policy.github[role].policy).Statement :
        toset(s.Resource) == toset([
          "arn:aws:dynamodb:eu-north-1:123456789012:table/energy-demo-aws-public-energy",
          "arn:aws:dynamodb:eu-north-1:123456789012:table/energy-demo-aws-user-energy"
        ]) if anytrue([for action in s.Action : startswith(action, "dynamodb:")])
      ]]
    ))
    error_message = "All CI DynamoDB access must name only the two exact project tables."
  }
  assert {
    condition     = length(aws_iam_role_policy.github["deploy"].policy) < 10240
    error_message = "The IAM inline policy must stay within AWS's 10,240-byte limit."
  }
  assert {
    condition = alltrue([
      for s in jsondecode(aws_iam_policy.lambda_boundary.policy).Statement :
      s.Action == ["dynamodb:Query"] && s.Resource == "arn:aws:dynamodb:eu-north-1:123456789012:table/energy-demo-aws-public-energy" &&
      s.Condition["ForAllValues:StringEquals"]["dynamodb:LeadingKeys"] == ["PUBLIC"]
      if anytrue([for action in s.Action : startswith(action, "dynamodb:")])
    ])
    error_message = "Public Lambda's boundary must restrict database access to read-only PUBLIC records."
  }
}

run "admin_boundaries_only_no_send_no_ci" {
  command = plan
  variables {
    enable_admin      = true
    enable_contact    = true
    enable_contact_ci = false
  }
  assert {
    condition     = toset(keys(aws_iam_policy.admin_boundary)) == toset(["admin", "private"]) && length(aws_iam_policy.contact_boundary) == 5 && length(aws_iam_policy.github_admin) == 0 && length(aws_iam_role_policy_attachment.github_admin) == 0
    error_message = "Only the two required Admin boundaries may accompany existing Contact boundaries, without CI grants."
  }
  assert {
    condition     = length(aws_sesv2_email_identity.admin) == 0 && length(aws_sesv2_configuration_set.admin) == 0 && length(aws_sns_topic.admin_email) == 0 && length(aws_sns_topic_policy.admin_email) == 0 && length(aws_sesv2_configuration_set_event_destination.admin) == 0 && length(aws_kms_key.admin_email) == 0
    error_message = "No-send preparation must not touch SES identities or Admin email event infrastructure."
  }
  assert {
    condition     = alltrue([for p in aws_iam_policy.admin_boundary : anytrue([for s in jsondecode(p.policy).Statement : s.Effect == "Deny" && contains(s.Action, "ses:SendEmail") && s.Resource == "*"])])
    error_message = "Admin boundaries must explicitly deny SES sending."
  }
}
run "admin_ci_requires_explicit_admin_preparation" {
  command = plan
  variables { enable_admin_ci = true }
  expect_failures = [var.enable_admin_ci]
}
