data "aws_iam_policy_document" "ecs_tasks_assume_role" {
  statement {
    sid     = "AllowECSTasksToAssumeRole"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_execution" {
  name                 = "${local.name_prefix}-execution-role"
  description          = "Allows ECS to start Knowledge Intelligence tasks."
  assume_role_policy   = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  permissions_boundary = var.permissions_boundary_arn

  tags = {
    Component = "ecs-execution"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "ecs_execution_secrets" {
  count = local.runtime_secrets_enabled ? 1 : 0
  statement {
    sid    = "ReadApplicationSecret"
    effect = "Allow"

    actions = [
      "secretsmanager:GetSecretValue"
    ]

    resources = [
      data.aws_secretsmanager_secret.application[0].arn
    ]
  }
}

resource "aws_iam_policy" "ecs_execution_secrets" {
  count       = local.runtime_secrets_enabled ? 1 : 0
  name        = "${local.name_prefix}-execution-secrets-policy"
  description = "Allows ECS to inject Knowledge Intelligence application secrets."
  policy      = data.aws_iam_policy_document.ecs_execution_secrets[0].json

  tags = {
    Component = "ecs-execution"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_execution_secrets" {
  count      = local.runtime_secrets_enabled ? 1 : 0
  role       = aws_iam_role.ecs_execution.name
  policy_arn = aws_iam_policy.ecs_execution_secrets[0].arn
}

resource "aws_iam_role" "ecs_task" {
  name                 = "${local.name_prefix}-task-role"
  description          = "AWS permissions used by the Knowledge Intelligence application."
  assume_role_policy   = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  permissions_boundary = var.permissions_boundary_arn

  tags = {
    Component = "application-runtime"
  }
}

data "aws_iam_policy_document" "knowledge_bucket_read" {
  statement {
    sid    = "ListKnowledgePrefix"
    effect = "Allow"

    actions = [
      "s3:ListBucket"
    ]

    resources = [
      "arn:aws:s3:::${var.knowledge_bucket_name}"
    ]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"

      values = [
        local.knowledge_s3_prefix,
        "${local.knowledge_s3_prefix}/*"
      ]
    }
  }

  statement {
    sid    = "ReadKnowledgeDocuments"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion"
    ]

    resources = [
      "arn:aws:s3:::${var.knowledge_bucket_name}/${local.knowledge_s3_prefix}/*"
    ]
  }
}

resource "aws_iam_policy" "knowledge_bucket_read" {
  name        = "${local.name_prefix}-knowledge-bucket-read-policy"
  description = "Read-only access to approved Knowledge Intelligence documents."
  policy      = data.aws_iam_policy_document.knowledge_bucket_read.json

  tags = {
    Component = "knowledge-source"
  }
}

resource "aws_iam_role_policy_attachment" "knowledge_bucket_read" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.knowledge_bucket_read.arn
}

data "aws_iam_policy_document" "vector_runtime" {
  statement {
    sid       = "QueryPlatformKnowledgeVectors"
    effect    = "Allow"
    actions   = ["s3vectors:GetIndex", "s3vectors:QueryVectors", "s3vectors:GetVectors", "s3vectors:PutVectors", "s3vectors:DeleteVectors"]
    resources = [aws_s3vectors_index.platform_knowledge.index_arn]
  }

  statement {
    sid       = "ReadProcessedChunks"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["arn:aws:s3:::${var.knowledge_bucket_name}/processed/*"]
  }
}

resource "aws_iam_policy" "vector_runtime" {
  name        = "${local.name_prefix}-vector-runtime-policy"
  description = "Read-only vector retrieval for the API runtime."
  policy      = data.aws_iam_policy_document.vector_runtime.json
}

resource "aws_iam_role_policy_attachment" "vector_runtime" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.vector_runtime.arn
}

data "aws_iam_policy_document" "feedback_write" {
  statement {
    sid       = "WriteKnowledgeFeedback"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["arn:aws:s3:::${var.knowledge_bucket_name}/${trim(var.feedback_prefix, "/")}/*"]
  }

  statement {
    sid       = "ReadPublishedComponentRegistry"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["arn:aws:s3:::${var.knowledge_bucket_name}/${trim(var.registry_prefix, "/")}/*"]
  }

  statement {
    sid       = "ListComponentRegistryVersions"
    effect    = "Allow"
    actions   = ["s3:ListBucketVersions"]
    resources = ["arn:aws:s3:::${var.knowledge_bucket_name}"]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${trim(var.registry_prefix, "/")}/*"]
    }
  }

  statement {
    sid       = "WriteSlackDiagrams"
    effect    = "Allow"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["arn:aws:s3:::${var.knowledge_bucket_name}/${trim(var.diagram_prefix, "/")}/*"]
  }
}

resource "aws_iam_policy" "feedback_write" {
  name        = "${local.name_prefix}-feedback-write-policy"
  description = "Writes privacy-safe Knowledge Intelligence feedback events."
  policy      = data.aws_iam_policy_document.feedback_write.json
}

resource "aws_iam_role_policy_attachment" "feedback_write" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.feedback_write.arn
}

resource "aws_iam_role" "vector_ingestion" {
  name                 = "${local.name_prefix}-vector-ingestion-role"
  description          = "Writes normalized chunks and S3 Vectors during explicit ingestion."
  assume_role_policy   = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  permissions_boundary = var.permissions_boundary_arn
}

data "aws_iam_policy_document" "vector_ingestion" {
  statement {
    sid       = "ManagePlatformKnowledgeVectors"
    effect    = "Allow"
    actions   = ["s3vectors:GetIndex", "s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:DeleteVectors", "s3vectors:ListVectors"]
    resources = [aws_s3vectors_index.platform_knowledge.index_arn]
  }
  statement {
    sid       = "ManageProcessedChunks"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["arn:aws:s3:::${var.knowledge_bucket_name}/processed/*"]
  }
}

resource "aws_iam_policy" "vector_ingestion" {
  name        = "${local.name_prefix}-vector-ingestion-policy"
  description = "S3 Vectors mutation and processed chunk storage for explicit ingestion."
  policy      = data.aws_iam_policy_document.vector_ingestion.json
}

resource "aws_iam_role_policy_attachment" "vector_ingestion" {
  role       = aws_iam_role.vector_ingestion.name
  policy_arn = aws_iam_policy.vector_ingestion.arn
}
