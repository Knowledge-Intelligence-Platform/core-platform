locals {
  valid_fargate_cpu_memory = {
    256   = [512, 1024, 2048]
    512   = [1024, 2048, 3072, 4096]
    1024  = [2048, 3072, 4096, 5120, 6144, 7168, 8192]
    2048  = range(4096, 16385, 1024)
    4096  = range(8192, 30721, 1024)
    8192  = range(16384, 61441, 4096)
    16384 = range(32768, 122881, 8192)
  }
  container_image = format(
    "%s:%s",
    aws_ecr_repository.application.repository_url,
    var.container_image_tag
  )
  application_secret_arn = try(data.aws_secretsmanager_secret.application[0].arn, "")

}

check "valid_fargate_cpu_memory_combination" {
  assert {
    condition = contains(
      local.valid_fargate_cpu_memory[var.ecs_task_cpu],
      var.ecs_task_memory
    )

    error_message = "The configured ECS task CPU and memory combination is not supported by Fargate."
  }
}

resource "aws_ecs_cluster" "application" {
  count = var.application_enabled ? 1 : 0
  name  = local.ecs_cluster_name

  setting {
    name = "containerInsights"

    value = (
      var.enable_container_insights
      ? "enabled"
      : "disabled"
    )
  }

  tags = {
    Name      = local.ecs_cluster_name
    Component = "application-runtime"
  }
}

resource "aws_ecs_task_definition" "application" {
  count  = var.application_enabled ? 1 : 0
  family = local.ecs_task_family

  requires_compatibilities = [
    "FARGATE"
  ]

  network_mode = "awsvpc"

  cpu    = tostring(var.ecs_task_cpu)
  memory = tostring(var.ecs_task_memory)

  execution_role_arn = aws_iam_role.ecs_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.ecs_cpu_architecture
  }

  container_definitions = jsonencode([
    {
      name      = local.container_name
      image     = local.container_image
      essential = true

      portMappings = [
        {
          name          = "http"
          containerPort = local.container_port
          hostPort      = local.container_port
          protocol      = "tcp"
          appProtocol   = "http"
        }
      ]

      environment = [
        { name = "KNOWLEDGE_INTELLIGENCE_AWS_REGION", value = var.aws_region },
        { name = "KNOWLEDGE_INTELLIGENCE_PLATFORM_NAME", value = var.knowledge_base_name },
        { name = "KNOWLEDGE_INTELLIGENCE_KNOWLEDGE_BASE_ID", value = aws_bedrockagent_knowledge_base.this.id },
        { name = "KNOWLEDGE_INTELLIGENCE_KNOWLEDGE_BASE_DATA_SOURCE_ID", value = aws_bedrockagent_data_source.confluence.data_source_id },
        { name = "KNOWLEDGE_INTELLIGENCE_BEDROCK_MODEL_ID", value = var.bedrock_model_id },
        { name = "KNOWLEDGE_INTELLIGENCE_BEDROCK_MAX_TOKENS", value = tostring(var.bedrock_max_tokens) },
        { name = "KNOWLEDGE_INTELLIGENCE_BEDROCK_PROMPT_CACHING_ENABLED", value = tostring(var.bedrock_prompt_caching_enabled) },
        { name = "KNOWLEDGE_INTELLIGENCE_TASKS_ENABLED", value = tostring(var.tasks_enabled) },
        { name = "KNOWLEDGE_INTELLIGENCE_TASK_ALLOWED_IDENTITIES", value = jsonencode(var.task_allowed_identities) },
        { name = "KNOWLEDGE_INTELLIGENCE_TASK_APPROVER_IDENTITIES", value = jsonencode(var.task_approver_identities) },
        { name = "KNOWLEDGE_INTELLIGENCE_TASK_PREFIX", value = var.task_prefix },
        { name = "KNOWLEDGE_INTELLIGENCE_AUDIT_PREFIX", value = var.audit_prefix },
        { name = "KNOWLEDGE_INTELLIGENCE_S3_BUCKET", value = var.knowledge_bucket_name },
        { name = "KNOWLEDGE_INTELLIGENCE_AGENT_MAX_SEARCH_RESULTS", value = tostring(var.agent_max_search_results) },
        { name = "KNOWLEDGE_INTELLIGENCE_SLACK_ENABLED", value = tostring(var.slack_enabled) },
        { name = "KNOWLEDGE_INTELLIGENCE_SLACK_MAX_MESSAGE_LENGTH", value = tostring(var.slack_max_message_length) },
        { name = "KNOWLEDGE_INTELLIGENCE_SLACK_CONVERSATION_WINDOW", value = tostring(var.slack_conversation_window) },
        { name = "KNOWLEDGE_INTELLIGENCE_FEEDBACK_PREFIX", value = var.feedback_prefix }
      ]

      secrets = concat(
        var.query_api_enabled ? [
          {
            name      = "KNOWLEDGE_INTELLIGENCE_QUERY_TOKENS"
            valueFrom = "${local.application_secret_arn}:QUERY_TOKENS::"
          }
        ] : [],
        var.slack_enabled ? [
          {
            name      = "KNOWLEDGE_INTELLIGENCE_SLACK_BOT_TOKEN"
            valueFrom = "${local.application_secret_arn}:SLACK_BOT_TOKEN::"
          },
          {
            name      = "KNOWLEDGE_INTELLIGENCE_SLACK_SIGNING_SECRET"
            valueFrom = "${local.application_secret_arn}:SLACK_SIGNING_SECRET::"
          }
        ] : [],
        var.admin_reindex_enabled ? [
          {
            name      = "KNOWLEDGE_INTELLIGENCE_ADMIN_TOKEN"
            valueFrom = "${local.application_secret_arn}:ADMIN_TOKEN::"
          }
        ] : []
      )

      logConfiguration = {
        logDriver = "awslogs"

        options = {
          awslogs-group         = aws_cloudwatch_log_group.application.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "application"
        }
      }

      healthCheck = {
        command = [
          "CMD-SHELL",
          join(
            "",
            [
              "python -c \"",
              "import urllib.request; ",
              "urllib.request.urlopen(",
              "'http://127.0.0.1:",
              tostring(local.container_port),
              "/health', timeout=",
              "5",
              ")",
              "\" || exit 1"
            ]
          )
        ]

        interval = 30
        timeout  = 5
        retries  = 3

        startPeriod = 60
      }

      readonlyRootFilesystem = true

      linuxParameters = {
        initProcessEnabled = true
      }
    }
  ])

  tags = {
    Name      = local.ecs_task_family
    Component = "application-runtime"
  }

  depends_on = [
    aws_iam_role_policy_attachment.ecs_execution_managed,
    aws_iam_role_policy_attachment.ecs_execution_secrets,
    aws_iam_role_policy_attachment.bedrock_runtime,
    aws_iam_role_policy_attachment.feedback_write,
    aws_cloudwatch_log_group.application
  ]
}

resource "aws_ecs_service" "application" {
  count           = var.application_enabled ? 1 : 0
  name            = local.name_prefix
  cluster         = aws_ecs_cluster.application[0].arn
  task_definition = aws_ecs_task_definition.application[0].arn
  desired_count   = var.ecs_desired_count
  launch_type     = "FARGATE"

  health_check_grace_period_seconds = 120
  enable_execute_command            = false

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.application.arn
    container_name   = local.container_name
    container_port   = local.container_port
  }

  tags = {
    Name      = local.name_prefix
    Component = "application-runtime"
  }

  depends_on = [aws_lb_listener.http]
}
