locals {
  runtime_secrets_enabled = var.application_enabled && (var.slack_enabled || var.query_api_enabled || var.admin_reindex_enabled)
}

data "aws_secretsmanager_secret" "application" {
  count = local.runtime_secrets_enabled ? 1 : 0
  name  = local.application_secret
}
