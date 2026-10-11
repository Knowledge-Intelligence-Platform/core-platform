locals {
  workflow_enabled = var.application_enabled && var.tasks_enabled && var.task_runner == "step_functions"
  executor_family  = "${local.name_prefix}-executor"
  executor_name    = "executor"
  task_objects     = "arn:aws:s3:::${var.knowledge_bucket_name}/${trim(var.task_prefix, "/")}/*"
  audit_objects    = "arn:aws:s3:::${var.knowledge_bucket_name}/${trim(var.audit_prefix, "/")}/*"
}

resource "aws_iam_role" "task_executor" {
  count                = local.workflow_enabled ? 1 : 0
  name                 = "${local.name_prefix}-executor-role"
  description          = "Runs approved Knowledge Intelligence task steps. The application never assumes it."
  assume_role_policy   = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  permissions_boundary = var.permissions_boundary_arn

  tags = {
    Component = "task-executor"
  }
}

data "aws_iam_policy_document" "task_executor" {
  count = local.workflow_enabled ? 1 : 0

  statement {
    sid       = "RunApprovedKnowledgeSync"
    actions   = ["bedrock:StartIngestionJob", "bedrock:GetIngestionJob", "bedrock:GetDataSource"]
    resources = [aws_bedrockagent_knowledge_base.this.arn]
  }

  statement {
    sid       = "UpdateTaskRecords"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = [local.task_objects]
  }

  statement {
    sid       = "AppendTaskAudit"
    actions   = ["s3:PutObject"]
    resources = [local.audit_objects]
  }
}

resource "aws_iam_policy" "task_executor" {
  count       = local.workflow_enabled ? 1 : 0
  name        = "${local.name_prefix}-executor-policy"
  description = "Exactly the actions approved task steps need, plus task and audit records."
  policy      = data.aws_iam_policy_document.task_executor[0].json
}

resource "aws_iam_role_policy_attachment" "task_executor" {
  count      = local.workflow_enabled ? 1 : 0
  role       = aws_iam_role.task_executor[0].name
  policy_arn = aws_iam_policy.task_executor[0].arn
}

resource "aws_security_group" "task_executor" {
  count       = local.workflow_enabled ? 1 : 0
  name        = "${local.name_prefix}-executor-sg"
  description = "Executor tasks accept no inbound traffic and call AWS APIs over HTTPS."
  vpc_id      = aws_vpc.this.id

  tags = {
    Name      = "${local.name_prefix}-executor-sg"
    Component = "task-executor"
  }
}

resource "aws_vpc_security_group_egress_rule" "task_executor_https" {
  for_each = local.workflow_enabled ? var.ecs_outbound_https_ipv4_cidrs : toset([])

  security_group_id = aws_security_group.task_executor[0].id
  description       = "Allow AWS API access over HTTPS."
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = each.value
}

resource "aws_ecs_task_definition" "executor" {
  count  = local.workflow_enabled ? 1 : 0
  family = local.executor_family

  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.task_executor[0].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.ecs_cpu_architecture
  }

  container_definitions = jsonencode([
    {
      name      = local.executor_name
      image     = local.container_image
      essential = true
      command   = ["python", "-m", "scripts.run_task"]

      environment = [
        { name = "KNOWLEDGE_INTELLIGENCE_AWS_REGION", value = var.aws_region },
        { name = "KNOWLEDGE_INTELLIGENCE_KNOWLEDGE_BASE_ID", value = aws_bedrockagent_knowledge_base.this.id },
        { name = "KNOWLEDGE_INTELLIGENCE_KNOWLEDGE_BASE_DATA_SOURCE_ID", value = aws_bedrockagent_data_source.confluence.data_source_id },
        { name = "KNOWLEDGE_INTELLIGENCE_S3_BUCKET", value = var.knowledge_bucket_name },
        { name = "KNOWLEDGE_INTELLIGENCE_TASK_PREFIX", value = var.task_prefix },
        { name = "KNOWLEDGE_INTELLIGENCE_AUDIT_PREFIX", value = var.audit_prefix }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.application.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = local.executor_name
        }
      }

      readonlyRootFilesystem = true
    }
  ])

  tags = {
    Name      = local.executor_family
    Component = "task-executor"
  }
}

data "aws_iam_policy_document" "task_workflow_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_workflow" {
  count                = local.workflow_enabled ? 1 : 0
  name                 = "${local.name_prefix}-task-workflow-role"
  description          = "Lets Step Functions run executor tasks for approved work."
  assume_role_policy   = data.aws_iam_policy_document.task_workflow_assume_role.json
  permissions_boundary = var.permissions_boundary_arn
}

data "aws_iam_policy_document" "task_workflow" {
  count = local.workflow_enabled ? 1 : 0

  statement {
    sid     = "RunExecutorTask"
    actions = ["ecs:RunTask"]
    resources = [
      "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${local.executor_family}:*"
    ]
  }

  statement {
    sid       = "TrackExecutorTask"
    actions   = ["ecs:StopTask", "ecs:DescribeTasks"]
    resources = ["*"]
  }

  statement {
    sid       = "PassExecutorRoles"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.ecs_execution.arn, aws_iam_role.task_executor[0].arn]
  }

  statement {
    sid     = "WaitForExecutorTask"
    actions = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
    resources = [
      "arn:aws:events:${var.aws_region}:${var.aws_account_id}:rule/StepFunctionsGetEventsForECSTaskRule"
    ]
  }
}

resource "aws_iam_role_policy" "task_workflow" {
  count  = local.workflow_enabled ? 1 : 0
  name   = "${local.name_prefix}-task-workflow"
  role   = aws_iam_role.task_workflow[0].id
  policy = data.aws_iam_policy_document.task_workflow[0].json
}

resource "aws_sfn_state_machine" "tasks" {
  count    = local.workflow_enabled ? 1 : 0
  name     = "${local.name_prefix}-tasks"
  type     = "STANDARD"
  role_arn = aws_iam_role.task_workflow[0].arn

  definition = jsonencode({
    Comment = "Runs one approved Knowledge Intelligence task in a separate executor task."
    StartAt = "RunExecutor"
    States = {
      RunExecutor = {
        Type     = "Task"
        Resource = "arn:aws:states:::ecs:runTask.sync"
        Parameters = {
          Cluster        = aws_ecs_cluster.application[0].arn
          TaskDefinition = aws_ecs_task_definition.executor[0].arn
          LaunchType     = "FARGATE"
          NetworkConfiguration = {
            AwsvpcConfiguration = {
              Subnets        = aws_subnet.public[*].id
              SecurityGroups = [aws_security_group.task_executor[0].id]
              AssignPublicIp = "ENABLED"
            }
          }
          Overrides = {
            ContainerOverrides = [
              {
                Name        = local.executor_name
                "Command.$" = "States.Array('python', '-m', 'scripts.run_task', $.task_id)"
              }
            ]
          }
        }
        Retry = [
          {
            ErrorEquals     = ["States.TaskFailed"]
            IntervalSeconds = 30
            MaxAttempts     = 2
            BackoffRate     = 2
          }
        ]
        End = true
      }
    }
  })

  tags = {
    Component = "task-workflow"
  }

  depends_on = [aws_iam_role_policy.task_workflow]
}
