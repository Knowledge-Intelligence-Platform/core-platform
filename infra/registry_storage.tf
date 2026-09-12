resource "aws_s3_bucket_versioning" "knowledge" {
  count  = var.registry_appconfig_enabled ? 1 : 0
  bucket = var.knowledge_bucket_name

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "knowledge" {
  count      = var.registry_appconfig_enabled ? 1 : 0
  bucket     = var.knowledge_bucket_name
  depends_on = [aws_s3_bucket_versioning.knowledge]

  rule {
    id     = "retain-registry-versions-for-rollback"
    status = "Enabled"

    filter {
      prefix = "${trim(var.registry_prefix, "/")}/"
    }

    noncurrent_version_expiration {
      newer_noncurrent_versions = 10
      noncurrent_days           = var.registry_version_retention_days
    }
  }

  dynamic "rule" {
    for_each = toset(["processed", "raw", "diagrams", "feedback", "sessions"])

    content {
      id     = "expire-superseded-${rule.value}"
      status = "Enabled"

      filter {
        prefix = "${rule.value}/"
      }

      noncurrent_version_expiration {
        noncurrent_days = 7
      }
    }
  }

  rule {
    id     = "abandon-incomplete-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}
