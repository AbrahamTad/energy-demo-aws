# Boundaries only; CI grants require a separately reviewed bootstrap extension.
variable "enable_contact" {
  type    = bool
  default = false
}
variable "contact_sender" {
  type    = string
  default = ""
}
variable "contact_admin_email" {
  type    = string
  default = ""
}
variable "contact_email_sending_enabled" {
  type    = bool
  default = false
}
module "contact_policy" {
  source          = "../modules/contact-policy"
  account_id      = var.account_id
  sender          = var.contact_sender
  admin_email     = var.contact_admin_email
  sending_enabled = var.contact_email_sending_enabled
}
resource "aws_iam_policy" "contact_boundary" {
  for_each = var.enable_contact ? module.contact_policy.policies : {}
  name     = "contact-${each.key}-boundary"
  path     = "/energy-demo-bootstrap/"
  policy   = each.value
}
