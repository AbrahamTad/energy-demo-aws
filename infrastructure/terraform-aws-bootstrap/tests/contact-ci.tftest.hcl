# Offline mock plans only. These IDs are synthetic; no backend or credentials.
mock_provider "aws" {
  override_during = plan
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:s3:::energy-demo-tfstate-628582070745-eu-north-1" }
  }
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:eu-north-1:628582070745:energy-demo-aws-admin-email" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:eu-north-1:628582070745:key/11111111-1111-4111-8111-111111111111" }
  }
}
variables {
  account_id                 = "628582070745"
  github_subject_prefix      = "repo:AbrahamTad@108827942/energy-demo-aws@1422193057:"
  existing_oidc_provider_arn = "arn:aws:iam::628582070745:oidc-provider/token.actions.githubusercontent.com"
  enable_admin               = true
  admin_email_sender         = "sender@example.invalid"
  admin_email_recipients     = ["admin@example.invalid"]
  enable_contact             = true
  enable_contact_ci          = true
  contact_sender             = "sender@example.invalid"
  contact_admin_email        = "admin@example.invalid"
  contact_ci_key_arn         = "arn:aws:kms:eu-north-1:628582070745:key/11111111-1111-4111-8111-111111111111"
  contact_ci_mapping_ids = {
    stream = "22222222-2222-4222-8222-222222222222"
    queue  = "33333333-3333-4333-8333-333333333333"
  }
  deployment_resource_ids = {
    api_id                     = "fixture123"
    cloudfront_distribution_id = "FIXTUREDIST"
    cloudfront_oac_id          = "FIXTUREOAC"
  }
}
run "contact_ci_scoped_draft" {
  command = plan
  variables { enable_admin_ci = true }
  assert {
    condition     = length(aws_iam_policy.github_contact) == 5 && length(aws_iam_role_policy_attachment.github_contact) == 8 && alltrue([for p in aws_iam_policy.github_contact : length(jsonencode(jsondecode(p.policy))) <= 6144])
    error_message = "Contact CI policies must be split below IAM size limits with only intended attachments."
  }
  assert {
    condition     = alltrue([for k, v in local.contact_ci_attachments : contains(["read-runtime", "read-delivery", "guard"], v.policy) if v.role == "plan"]) && alltrue(flatten([for n in ["read-runtime", "read-delivery"] : [for st in jsondecode(module.contact_ci_policy.policies[n]).Statement : alltrue([for a in st.Action : can(regex(":(Get|List|Describe)", a))])]]))
    error_message = "Contact Plan additions must be metadata reads and explicit denies only."
  }
  assert {
    condition     = !contains(keys(module.contact_ci_policy.policies), "create") && alltrue(flatten([for p in module.contact_ci_policy.policies : [for st in jsondecode(p).Statement : !contains(st.Action, "iam:CreateRole") if st.Effect == "Allow"]])) && anytrue([for st in jsondecode(module.contact_ci_policy.policies["guard"]).Statement : st.Effect == "Deny" && contains(st.Action, "iam:CreateRole") && contains(st.Action, "iam:DeleteRolePermissionsBoundary") && contains(st.Action, "iam:UpdateAssumeRolePolicy") && st.Resource == "*"])
    error_message = "CI must never create roles, remove boundaries or modify trust, even with an exact boundary."
  }
  assert {
    condition     = jsondecode(aws_iam_role.github["plan"].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:AbrahamTad@108827942/energy-demo-aws@1422193057:ref:refs/heads/main" && jsondecode(aws_iam_role.github["deploy"].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:AbrahamTad@108827942/energy-demo-aws@1422193057:environment:aws-production"
    error_message = "Contact must preserve immutable repository-ID trust and production environment scope."
  }
  assert {
    condition     = alltrue([for st in jsondecode(module.contact_ci_policy.policies["guard"]).Statement : st.Effect == "Deny"]) && alltrue(flatten([for n in ["read-runtime", "read-delivery", "write-runtime", "write-delivery"] : [for st in jsondecode(module.contact_ci_policy.policies[n]).Statement : st.Resource != "*"]]))
    error_message = "No Contact Allow may use Resource=*; direct data access and escalation must be explicitly denied."
  }
  assert {
    condition     = length(aws_iam_role_policy_attachment.github_admin) + length(aws_iam_role_policy_attachment.github_contact) == 12
    error_message = "Existing Admin attachments must be preserved (Deploy 8 managed policies, Plan 4)."
  }
}
run "contact_ci_default_off" {
  command = plan
  variables { enable_contact_ci = false }
  assert {
    condition     = length(aws_iam_policy.github_contact) == 0 && length(aws_iam_role_policy_attachment.github_contact) == 0
    error_message = "Contact CI must remain opt-in with no new grants by default."
  }
}
run "contact_ci_requires_exact_key" {
  command = plan
  variables { contact_ci_key_arn = "" }
  expect_failures = [aws_iam_policy.github_contact]
}
run "contact_ci_rejects_foreign_key" {
  command = plan
  variables { contact_ci_key_arn = "arn:aws:kms:eu-north-1:123456789012:key/11111111-1111-4111-8111-111111111111" }
  expect_failures = [var.contact_ci_key_arn]
}
run "contact_ci_requires_two_mapping_ids" {
  command = plan
  variables { contact_ci_mapping_ids = {} }
  expect_failures = [aws_iam_policy.github_contact]
}
run "contact_ci_rejects_wildcard_mapping" {
  command = plan
  variables { contact_ci_mapping_ids = { stream = "*", queue = "33333333-3333-4333-8333-333333333333" } }
  expect_failures = [var.contact_ci_mapping_ids]
}
run "contact_ci_rejects_mutable_oidc_subject" {
  command = plan
  variables { github_subject_prefix = "repo:AbrahamTad/energy-demo-aws:" }
  expect_failures = [aws_iam_policy.github_contact]
}
run "contact_ci_requires_admin_review" {
  command = plan
  variables { enable_admin = false }
  expect_failures = [aws_iam_policy.github_contact]
}
run "contact_ci_requires_no_send_boundary" {
  command = plan
  variables { contact_email_sending_enabled = true }
  expect_failures = [aws_iam_policy.github_contact]
}

override_data {
  target = data.aws_iam_role.contact_ci["api"]
  values = {
    arn                  = "arn:aws:iam::628582070745:role/energy-demo-aws/contact-api"
    path                 = "/energy-demo-aws/"
    permissions_boundary = "arn:aws:iam::628582070745:policy/energy-demo-bootstrap/contact-api-boundary"
    assume_role_policy   = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Principal\":{\"Service\":\"lambda.amazonaws.com\"}}]}"
  }
}

override_data {
  target = data.aws_iam_role.contact_ci["relay"]
  values = {
    arn                  = "arn:aws:iam::628582070745:role/energy-demo-aws/contact-relay"
    path                 = "/energy-demo-aws/"
    permissions_boundary = "arn:aws:iam::628582070745:policy/energy-demo-bootstrap/contact-relay-boundary"
    assume_role_policy   = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Principal\":{\"Service\":\"lambda.amazonaws.com\"}}]}"
  }
}

override_data {
  target = data.aws_iam_role.contact_ci["worker"]
  values = {
    arn                  = "arn:aws:iam::628582070745:role/energy-demo-aws/contact-worker"
    path                 = "/energy-demo-aws/"
    permissions_boundary = "arn:aws:iam::628582070745:policy/energy-demo-bootstrap/contact-worker-boundary"
    assume_role_policy   = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Principal\":{\"Service\":\"lambda.amazonaws.com\"}}]}"
  }
}

override_data {
  target = data.aws_iam_role.contact_ci["admin"]
  values = {
    arn                  = "arn:aws:iam::628582070745:role/energy-demo-aws/contact-admin"
    path                 = "/energy-demo-aws/"
    permissions_boundary = "arn:aws:iam::628582070745:policy/energy-demo-bootstrap/contact-admin-boundary"
    assume_role_policy   = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Principal\":{\"Service\":\"lambda.amazonaws.com\"}}]}"
  }
}

override_data {
  target = data.aws_iam_role.contact_ci["events"]
  values = {
    arn                  = "arn:aws:iam::628582070745:role/energy-demo-aws/contact-events"
    path                 = "/energy-demo-aws/"
    permissions_boundary = "arn:aws:iam::628582070745:policy/energy-demo-bootstrap/contact-events-boundary"
    assume_role_policy   = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Principal\":{\"Service\":\"lambda.amazonaws.com\"}}]}"
  }
}

run "reject_preprovisioned_attacker_trust" {
  command = plan
  override_data {
    target = data.aws_iam_role.contact_ci["api"]
    values = {
      arn                  = "arn:aws:iam::628582070745:role/energy-demo-aws/contact-api"
      path                 = "/energy-demo-aws/"
      permissions_boundary = "arn:aws:iam::628582070745:policy/energy-demo-bootstrap/contact-api-boundary"
      assume_role_policy   = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Principal\":{\"AWS\":\"*\"}}]}"
    }
  }
  expect_failures = [data.aws_iam_role.contact_ci["api"]]
}

run "reject_preprovisioned_wrong_boundary" {
  command = plan
  override_data {
    target = data.aws_iam_role.contact_ci["api"]
    values = {
      arn                  = "arn:aws:iam::628582070745:role/energy-demo-aws/contact-api"
      path                 = "/energy-demo-aws/"
      permissions_boundary = "arn:aws:iam::628582070745:policy/AdministratorAccess"
      assume_role_policy   = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Principal\":{\"Service\":\"lambda.amazonaws.com\"}}]}"
    }
  }
  expect_failures = [data.aws_iam_role.contact_ci["api"]]
}

run "reject_preprovisioned_wrong_path" {
  command = plan
  override_data {
    target = data.aws_iam_role.contact_ci["api"]
    values = {
      arn                  = "arn:aws:iam::628582070745:role/energy-demo-aws/contact-api"
      path                 = "/unrelated/"
      permissions_boundary = "arn:aws:iam::628582070745:policy/energy-demo-bootstrap/contact-api-boundary"
      assume_role_policy   = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Principal\":{\"Service\":\"lambda.amazonaws.com\"}}]}"
    }
  }
  expect_failures = [data.aws_iam_role.contact_ci["api"]]
}
