import {
  to = aws_bedrockagent_knowledge_base.this
  id = var.knowledge_base_id
}

import {
  to = aws_bedrockagent_data_source.confluence
  id = "${var.confluence_data_source_id},${var.knowledge_base_id}"
}

resource "aws_bedrockagent_knowledge_base" "this" {
  provider = aws.bedrock
  name     = var.knowledge_base_name
  role_arn = var.knowledge_base_role_arn
  tags     = var.tags

  knowledge_base_configuration {
    type = "MANAGED"

    managed_knowledge_base_configuration {
      embedding_model_type = "MANAGED"
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

data "aws_iam_policy_document" "bedrock_runtime" {
  statement {
    sid       = "RetrieveApprovedKnowledge"
    actions   = ["bedrock:Retrieve", "bedrock:GetKnowledgeBase"]
    resources = [aws_bedrockagent_knowledge_base.this.arn]
  }

  statement {
    sid       = "InvokeAmazonModel"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["arn:aws:bedrock:${var.aws_region}::foundation-model/${var.bedrock_model_id}"]
  }

  dynamic "statement" {
    for_each = var.admin_reindex_enabled || var.tasks_enabled ? [1] : []
    content {
      sid       = "SyncKnowledgeDataSource"
      actions   = ["bedrock:StartIngestionJob"]
      resources = [aws_bedrockagent_knowledge_base.this.arn]
    }
  }
  dynamic "statement" {
    for_each = var.tasks_enabled ? [1] : []
    content {
      sid       = "InspectKnowledgeSync"
      actions   = ["bedrock:GetDataSource", "bedrock:ListIngestionJobs", "bedrock:GetIngestionJob"]
      resources = [aws_bedrockagent_knowledge_base.this.arn]
    }
  }
  dynamic "statement" {
    for_each = var.tasks_enabled ? [1] : []
    content {
      sid       = "PersistKnowledgeTasks"
      actions   = ["s3:GetObject", "s3:PutObject"]
      resources = ["arn:aws:s3:::${var.knowledge_bucket_name}/${trim(var.task_prefix, "/")}/*"]
    }
  }
  dynamic "statement" {
    for_each = var.tasks_enabled ? [1] : []
    content {
      sid       = "CheckKnowledgeTaskExistence"
      actions   = ["s3:ListBucket"]
      resources = ["arn:aws:s3:::${var.knowledge_bucket_name}"]
      condition {
        test     = "StringLike"
        variable = "s3:prefix"
        values   = ["${trim(var.task_prefix, "/")}/*"]
      }
    }
  }
}

resource "aws_iam_policy" "bedrock_runtime" {
  name   = "${local.name_prefix}-bedrock-runtime-policy"
  policy = data.aws_iam_policy_document.bedrock_runtime.json
}

resource "aws_iam_role_policy_attachment" "bedrock_runtime" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.bedrock_runtime.arn
}

resource "aws_bedrockagent_data_source" "confluence" {
  provider             = aws.bedrock
  knowledge_base_id    = aws_bedrockagent_knowledge_base.this.id
  name                 = var.confluence_data_source_name
  data_deletion_policy = var.data_deletion_policy

  data_source_configuration {
    type = "MANAGED_KNOWLEDGE_BASE_CONNECTOR"

    managed_knowledge_base_connector_configuration {
      connector_parameters = trimspace(var.confluence_connector_parameters)

      deletion_protection_configuration {
        deletion_protection_status    = var.sync_deletion_protection.enabled ? "ENABLED" : "DISABLED"
        deletion_protection_threshold = var.sync_deletion_protection.threshold
      }

      media_extraction_configuration {
        image_extraction_configuration {
          image_extraction_status = var.media_extraction.image ? "ENABLED" : "DISABLED"
        }

        audio_extraction_configuration {
          audio_extraction_status = var.media_extraction.audio ? "ENABLED" : "DISABLED"
        }

        video_extraction_configuration {
          video_extraction_status = var.media_extraction.video ? "ENABLED" : "DISABLED"
        }
      }
    }
  }

  vector_ingestion_configuration {
    parsing_configuration {
      parsing_strategy = "SMART_PARSING"
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}
