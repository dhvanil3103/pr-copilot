# Email alerts as actual spend crosses each threshold. The first two budgets in
# an account are free.
resource "aws_budgets_budget" "credits" {
  name              = "${var.cluster_name}-credits"
  budget_type       = "COST"
  limit_amount      = tostring(var.budget_limit_usd)
  limit_unit        = "USD"
  time_unit         = "ANNUALLY"
  time_period_start = var.budget_start

  cost_types {
    # Track gross spend. With credits included, spend paid by credits nets to $0
    # and the alerts would never fire while the credits are being used up.
    include_credit = false
    include_refund = false
  }

  dynamic "notification" {
    for_each = var.budget_alert_thresholds_usd
    content {
      comparison_operator        = "GREATER_THAN"
      notification_type          = "ACTUAL"
      threshold                  = notification.value
      threshold_type             = "ABSOLUTE_VALUE"
      subscriber_email_addresses = [var.budget_email]
    }
  }
}
