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

data "aws_iam_policy_document" "feedback_write" {
  statement {
    sid       = "WriteKnowledgeFeedback"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["arn:aws:s3:::${var.knowledge_bucket_name}/${trim(var.feedback_prefix, "/")}/*"]
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
