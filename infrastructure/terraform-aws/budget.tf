resource "aws_budgets_budget" "learning" {
  account_id   = var.account_id
  name         = "energy-demo-aws-monthly"
  budget_type  = "COST"
  limit_amount = "5"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  cost_types {
    include_credit = false
    include_refund = false
  }
  # Account-wide: avoids depending on delayed cost-allocation tag activation.
  dynamic "notification" {
    for_each = [1, 3, 5]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "ABSOLUTE_VALUE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_email]
    }
  }
}
