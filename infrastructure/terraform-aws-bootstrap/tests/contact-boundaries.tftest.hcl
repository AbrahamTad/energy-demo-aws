# Offline only: real module rendering with a mocked AWS provider, never live state.
mock_provider "aws" {}

variables {
  account_id                    = "628582070745"
  github_subject_prefix         = "repo:AbrahamTad@108827942/energy-demo-aws@1422193057:"
  existing_oidc_provider_arn    = "arn:aws:iam::628582070745:oidc-provider/token.actions.githubusercontent.com"
  enable_admin                  = false
  enable_contact                = true
  enable_contact_ci             = false
  contact_sender                = "sender@example.invalid"
  contact_admin_email           = "admin@example.invalid"
  contact_email_sending_enabled = false
}

run "only_intended_secret_readers" {
  command = plan
  assert {
    condition = alltrue([for k in ["api", "events", "worker"] :
      [for st in jsondecode(module.contact_policy.policies[k]).Statement : st.Resource if contains(st.Action, "secretsmanager:GetSecretValue")] == ["arn:aws:secretsmanager:eu-north-1:628582070745:secret:energy-demo/contact-??????"]
      ]) && alltrue([for k in ["admin", "relay"] :
      alltrue([for st in jsondecode(module.contact_policy.policies[k]).Statement : !contains(st.Action, "secretsmanager:GetSecretValue")])
    ])
    error_message = "Only api/events/worker may read the exact Contact secret name with its six-character ARN suffix."
  }
  assert {
    condition     = length(aws_iam_policy.contact_boundary) == 5 && length(aws_iam_policy.github_contact) == 0 && length(aws_iam_role_policy_attachment.github_contact) == 0 && length(aws_iam_policy.admin_boundary) == 0
    error_message = "This stage must create five boundaries without Admin activation, CI policies or attachments."
  }
}

run "secret_suffix_and_namespace_denials" {
  command = plan
  # Translate only the IAM glob characters used by these ARN patterns. This is not a full IAM simulator.
  assert {
    condition = alltrue(flatten([for k in ["api", "events", "worker"] : [
      for st in jsondecode(module.contact_policy.policies[k]).Statement : alltrue([
        for arn in [
          "arn:aws:secretsmanager:eu-north-1:628582070745:secret:energy-demo/contact-a1B2c3",
          "arn:aws:secretsmanager:eu-north-1:628582070745:secret:energy-demo/contact-ZYX987"
        ] : can(regex("^${replace(replace(st.Resource, "*", ".*"), "?", ".")}$", arn))
      ]) if contains(st.Action, "secretsmanager:GetSecretValue")
    ]]))
    error_message = "The intended Contact secret must remain readable for valid six-character suffixes."
  }
  assert {
    condition = alltrue(flatten([for k in ["api", "events", "worker"] : [
      for st in jsondecode(module.contact_policy.policies[k]).Statement : alltrue([
        for arn in [
          "arn:aws:secretsmanager:eu-north-1:628582070745:secret:energy-demo/contact-other-a1B2c3",
          "arn:aws:secretsmanager:eu-north-1:628582070745:secret:energy-demo/contact-backup-a1B2c3",
          "arn:aws:secretsmanager:eu-north-1:628582070745:secret:energy-demo/contact/a1B2c3",
          "arn:aws:secretsmanager:eu-north-1:628582070745:secret:energy-demo/contact-a1B2c",
          "arn:aws:secretsmanager:eu-north-1:628582070745:secret:energy-demo/contact-a1B2c34",
          "arn:aws:secretsmanager:eu-north-1:628582070745:secret:synthetic-other-project/contact-a1B2c3",
          "arn:aws:secretsmanager:eu-west-1:628582070745:secret:energy-demo/contact-a1B2c3",
          "arn:aws:secretsmanager:eu-north-1:111122223333:secret:energy-demo/contact-a1B2c3"
        ] : !can(regex("^${replace(replace(st.Resource, "*", ".*"), "?", ".")}$", arn))
      ]) if contains(st.Action, "secretsmanager:GetSecretValue")
    ]]))
    error_message = "Similarly named secrets, other synthetic project namespaces, wrong suffix lengths and foreign accounts/regions must not match."
  }
}

run "no_privilege_escalation_actions" {
  command = plan
  assert {
    condition = alltrue(flatten([for k, policy in module.contact_policy.policies : [
      for st in jsondecode(policy).Statement : alltrue([
        for action in st.Action : !strcontains(action, "*") && !strcontains(action, "?") && !can(regex("^(iam|sts|kms|organizations|sso):", lower(action)))
      ]) && !contains(keys(st), "NotAction") && !contains(keys(st), "NotResource")
    ]]))
    error_message = "Runtime boundaries must not admit IAM/PassRole/STS/KMS escalation, wildcard actions or inverse scopes."
  }
  assert {
    condition = alltrue(flatten([for k, policy in module.contact_policy.policies : [
      for st in jsondecode(policy).Statement : (
        st.Resource != "*" || (k == "relay" && st.Action == ["dynamodb:ListStreams"] && try(st.Condition.StringEquals["aws:RequestedRegion"], "") == "eu-north-1")
      ) if st.Effect == "Allow"
    ]]))
    error_message = "Only region-constrained DynamoDB ListStreams may Allow Resource=*."
  }
}

run "no_send_deny_preserved" {
  command = plan
  assert {
    condition = anytrue([for st in jsondecode(module.contact_policy.policies["worker"]).Statement :
      st.Effect == "Deny" && st.Resource == "*" && alltrue([for a in ["ses:SendEmail", "ses:SendRawEmail", "ses:SendBulkEmail"] : contains(st.Action, a)])
      ]) && alltrue([for st in jsondecode(module.contact_policy.policies["worker"]).Statement :
      try(st.Condition.StringEquals["ses:FromAddress"], "") == "sender@example.invalid" if st.Effect == "Allow" && contains(st.Action, "ses:SendEmail")
    ])
    error_message = "No-send must explicitly deny all supported SES send operations while retaining the constrained sender configuration."
  }
}
