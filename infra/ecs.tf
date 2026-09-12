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
  openai_api_key_secret_arn = format(
    "%s:OPENAI_API_KEY::",
    data.aws_secretsmanager_secret.application.arn
  )

  slack_bot_token_secret_arn = format(
    "%s:SLACK_BOT_TOKEN::",
    data.aws_secretsmanager_secret.application.arn
  )

  slack_signing_secret_arn = format(
    "%s:SLACK_SIGNING_SECRET::",
    data.aws_secretsmanager_secret.application.arn
  )

  github_token_secret_arn = format(
    "%s:GITHUB_TOKEN::",
    data.aws_secretsmanager_secret.application.arn
  )

  admin_token_secret_arn = format(
    "%s:ADMIN_TOKEN::",
    data.aws_secretsmanager_secret.application.arn
  )
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
  name = local.ecs_cluster_name

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
        {
          name  = "KNOWLEDGE_INTELLIGENCE_AWS_REGION"
          value = var.aws_region
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_S3_BUCKET"
          value = var.knowledge_bucket_name
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_S3_PREFIX"
          value = local.knowledge_s3_prefix
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_MAX_DOCUMENT_SIZE_MB"
          value = tostring(var.max_document_size_mb)
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_OPENAI_MODEL"
          value = var.openai_model
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_AGENT_MAX_SEARCH_RESULTS"
          value = tostring(var.agent_max_search_results)
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_GITHUB_ENABLED"
          value = tostring(var.github_enabled)
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_SLACK_ENABLED"
          value = tostring(var.slack_enabled)
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_SLACK_MAX_MESSAGE_LENGTH"
          value = tostring(var.slack_max_message_length)
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_SLACK_CONVERSATION_WINDOW"
          value = tostring(var.slack_conversation_window)
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_REGISTRY_DOCUMENT_KEY"
          value = "${trim(var.registry_prefix, "/")}/registry.yaml"
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_REGISTRY_APPCONFIG_APPLICATION"
          value = var.registry_appconfig_enabled ? aws_appconfig_application.registry[0].id : ""
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_REGISTRY_APPCONFIG_ENVIRONMENT"
          value = var.registry_appconfig_enabled ? aws_appconfig_environment.registry[0].environment_id : ""
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_REGISTRY_APPCONFIG_PROFILE"
          value = var.registry_appconfig_enabled ? aws_appconfig_configuration_profile.registry[0].configuration_profile_id : ""
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_DIAGRAM_PREFIX"
          value = var.diagram_prefix
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_PUBLIC_BASE_URL"
          value = aws_apigatewayv2_api.application.api_endpoint
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_FEEDBACK_PREFIX"
          value = var.feedback_prefix
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_VECTOR_BUCKET_NAME"
          value = var.vector_bucket_name
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_VECTOR_INDEX_NAME"
          value = var.vector_index_name
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_EMBEDDING_MODEL"
          value = var.embedding_model
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_EMBEDDING_DIMENSIONS"
          value = tostring(var.vector_dimensions)
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_EMBEDDING_BATCH_SIZE"
          value = tostring(var.embedding_batch_size)
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_VISUAL_ANALYSIS_ENABLED"
          value = tostring(var.visual_analysis_enabled)
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_VISUAL_ANALYSIS_MODEL"
          value = var.visual_analysis_model
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_VISUAL_RENDER_DPI"
          value = tostring(var.visual_render_dpi)
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_VISUAL_MAX_PAGES_PER_DOCUMENT"
          value = tostring(var.visual_max_pages_per_document)
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_VECTOR_TOP_K"
          value = tostring(var.vector_top_k)
        },
        {
          name  = "KNOWLEDGE_INTELLIGENCE_REGISTRY_DIRECTORY"
          value = "registry/components"
        }
      ]

      secrets = concat([
        {
          name      = "KNOWLEDGE_INTELLIGENCE_OPENAI_API_KEY"
          valueFrom = local.openai_api_key_secret_arn
        }
        ],
        var.slack_enabled ? [
          {
            name      = "KNOWLEDGE_INTELLIGENCE_SLACK_BOT_TOKEN"
            valueFrom = local.slack_bot_token_secret_arn
          },
          {
            name      = "KNOWLEDGE_INTELLIGENCE_SLACK_SIGNING_SECRET"
            valueFrom = local.slack_signing_secret_arn
          }
        ] : [],
        var.github_enabled ? [
          {
            name      = "KNOWLEDGE_INTELLIGENCE_GITHUB_TOKEN"
            valueFrom = local.github_token_secret_arn
          }
        ] : [],
        var.admin_reindex_enabled ? [
          {
            name      = "KNOWLEDGE_INTELLIGENCE_ADMIN_TOKEN"
            valueFrom = local.admin_token_secret_arn
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
    aws_iam_role_policy_attachment.knowledge_bucket_read,
    aws_iam_role_policy_attachment.feedback_write,
    aws_cloudwatch_log_group.application
  ]
}

resource "aws_ecs_service" "application" {
  name            = local.name_prefix
  cluster         = aws_ecs_cluster.application.arn
  task_definition = aws_ecs_task_definition.application.arn
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
    subnets          = var.ecs_subnet_ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = var.ecs_assign_public_ip
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
