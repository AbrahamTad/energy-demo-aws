# Local draft only. Opt-in is separate from creation of Contact runtime boundaries.
variable "enable_contact_ci" {
  type    = bool
  default = false
}
variable "contact_ci_key_arn" {
  description = "Exact administrator-provisioned Contact KMS key; no CI key creation, usage or management."
  type        = string
  default     = ""
  validation {
    condition     = var.contact_ci_key_arn == "" || can(regex("^arn:aws:kms:eu-north-1:${var.account_id}:key/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", var.contact_ci_key_arn))
    error_message = "Contact CI requires an exact same-account eu-north-1 key UUID ARN."
  }
}
variable "contact_ci_mapping_ids" {
  description = "Exact administrator-provisioned Contact stream and queue mapping UUIDs; no discovery or wildcard mutation."
  type        = map(string)
  default     = {}
  validation {
    condition = alltrue([for k, id in var.contact_ci_mapping_ids :
      contains(["stream", "queue"], k) && can(regex("^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", id))
    ])
    error_message = "Only exact Contact stream/queue mapping UUIDs are accepted."
  }
}
module "contact_ci_policy" {
  source      = "../modules/contact-ci-policy"
  account_id  = var.account_id
  key_arn     = var.contact_ci_key_arn
  mapping_ids = var.contact_ci_mapping_ids
}
resource "aws_iam_policy" "github_contact" {
  for_each = var.enable_contact_ci ? module.contact_ci_policy.policies : {}
  name     = "energy-demo-contact-ci-${each.key}"
  path     = "/energy-demo-bootstrap/"
  policy   = each.value
  lifecycle {
    precondition {
      condition     = var.account_id == "628582070745" && var.enable_contact && var.enable_admin && !var.contact_email_sending_enabled && var.deployment_resource_ids != null
      error_message = "Contact CI needs the EnergyDemo account, reviewed Admin/Contact bootstrap, exact deployment IDs and no-send boundaries."
    }
    precondition {
      condition     = var.github_subject_prefix == "repo:AbrahamTad@108827942/energy-demo-aws@1422193057:" && var.existing_oidc_provider_arn == "arn:aws:iam::${var.account_id}:oidc-provider/token.actions.githubusercontent.com"
      error_message = "Preserve the verified immutable repository-ID OIDC prefix and existing provider."
    }
    precondition {
      condition     = var.contact_ci_key_arn != "" && toset(keys(var.contact_ci_mapping_ids)) == toset(["stream", "queue"]) && length(toset(values(var.contact_ci_mapping_ids))) == 2
      error_message = "An administrator must first provision/review the Contact key and two distinct exact mapping UUIDs."
    }
    precondition {
      condition     = length(jsonencode(jsondecode(each.value))) <= 6144
      error_message = "Contact managed CI policies must fit the 6,144-character IAM limit."
    }
  }
}
locals {
  contact_ci_attachments = var.enable_contact_ci ? merge(
    { for name in ["read-runtime", "read-delivery", "guard"] : "plan-${name}" => { role = "plan", policy = name } },
    { for name in keys(module.contact_ci_policy.policies) : "deploy-${name}" => { role = "deploy", policy = name } }
  ) : {}
}
resource "aws_iam_role_policy_attachment" "github_contact" {
  for_each   = local.contact_ci_attachments
  role       = aws_iam_role.github[each.value.role].name
  policy_arn = aws_iam_policy.github_contact[each.value.policy].arn
}
