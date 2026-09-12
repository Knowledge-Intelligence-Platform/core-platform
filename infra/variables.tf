variable "name_prefix" {
  description = "Prefix for every resource this deployment creates. One tenant, one prefix."
  type        = string
  default     = "knowledge-intelligence"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,26}[a-z0-9]$", var.name_prefix)) && !startswith(var.name_prefix, "internal-")
    error_message = "name_prefix must be 3-28 characters of lowercase letters, digits and hyphens, start with a letter, end with a letter or digit, and not start with \"internal-\"."
  }
}

variable "aws_region" {
  description = "AWS region where Knowledge Intelligence resources are deployed. S3 Vectors uses ap-south-1."
  type        = string

  validation {
    condition     = var.aws_region == "ap-south-1"
    error_message = "aws_region must be ap-south-1 for S3 Vectors."
  }
}

variable "additional_tags" {
  description = "Additional tags applied to all supported resources."
  type        = map(string)
  default     = {}
}

variable "knowledge_bucket_name" {
  description = "Name of the S3 bucket containing knowledge documents."
  type        = string

  validation {
    condition     = length(trimspace(var.knowledge_bucket_name)) > 0
    error_message = "knowledge_bucket_name cannot be empty."
  }
}

variable "knowledge_s3_prefix" {
  description = "S3 prefix containing approved Confluence PDF exports."
  type        = string
  default     = "raw/confluence/"

  validation {
    condition = (
      length(trimspace(var.knowledge_s3_prefix)) > 0 &&
      !startswith(var.knowledge_s3_prefix, "/")
    )
    error_message = "knowledge_s3_prefix must be non-empty and must not start with '/'."
  }
}

variable "vpc_id" {
  description = "Existing VPC ID used by the ALB and ECS Fargate service."
  type        = string

  validation {
    condition     = can(regex("^vpc-[0-9a-fA-F]+$", var.vpc_id))
    error_message = "vpc_id must be a valid VPC ID."
  }
}

variable "alb_subnet_ids" {
  description = "Existing subnet IDs used by the internet-facing Application Load Balancer."
  type        = set(string)

  validation {
    condition = (
      length(var.alb_subnet_ids) >= 2 &&
      alltrue([
        for subnet_id in var.alb_subnet_ids :
        can(regex("^subnet-[0-9a-fA-F]+$", subnet_id))
      ])
    )
    error_message = "alb_subnet_ids must contain at least two valid subnet IDs."
  }
}

variable "ecs_subnet_ids" {
  description = "Existing private subnet IDs used by ECS Fargate tasks."
  type        = set(string)

  validation {
    condition = (
      length(var.ecs_subnet_ids) >= 2 &&
      alltrue([
        for subnet_id in var.ecs_subnet_ids :
        can(regex("^subnet-[0-9a-fA-F]+$", subnet_id))
      ])
    )
    error_message = "ecs_subnet_ids must contain at least two valid subnet IDs."
  }
}

variable "alb_ingress_ipv4_cidrs" {
  description = "IPv4 CIDR ranges permitted to reach the demo ALB over HTTP."
  type        = set(string)
  default     = ["0.0.0.0/0"]

  validation {
    condition = alltrue([
      for cidr in var.alb_ingress_ipv4_cidrs : can(cidrnetmask(cidr))
    ])
    error_message = "Every ALB ingress value must be a valid IPv4 CIDR."
  }
}

variable "ecs_outbound_https_ipv4_cidrs" {
  description = "IPv4 CIDRs ECS tasks may access over HTTPS."
  type        = set(string)
  default     = ["0.0.0.0/0"]

  validation {
    condition = alltrue([
      for cidr in var.ecs_outbound_https_ipv4_cidrs : can(cidrnetmask(cidr))
    ])
    error_message = "Every ECS outbound value must be a valid IPv4 CIDR."
  }
}

variable "container_image_tag" {
  description = "ECR image tag deployed by the task definition. The demo workflow uses latest."
  type        = string

  validation {
    condition     = var.container_image_tag == "latest"
    error_message = "container_image_tag must be latest."
  }
}

variable "ecs_task_cpu" {
  description = "CPU units allocated to the Fargate task."
  type        = number
  default     = 1024

  validation {
    condition     = contains([256, 512, 1024, 2048, 4096, 8192, 16384], var.ecs_task_cpu)
    error_message = "ecs_task_cpu must be a supported Fargate CPU value."
  }
}

variable "ecs_task_memory" {
  description = "Memory in MiB allocated to the Fargate task."
  type        = number
  default     = 2048

  validation {
    condition     = var.ecs_task_memory >= 512
    error_message = "ecs_task_memory must be at least 512 MiB."
  }
}

variable "ecs_cpu_architecture" {
  description = "CPU architecture used by the Fargate task and container image."
  type        = string
  default     = "X86_64"

  validation {
    condition     = contains(["X86_64", "ARM64"], var.ecs_cpu_architecture)
    error_message = "ecs_cpu_architecture must be X86_64 or ARM64."
  }
}

variable "enable_container_insights" {
  description = "Whether CloudWatch Container Insights is enabled for the ECS cluster."
  type        = bool
  default     = true
}

variable "ecs_desired_count" {
  description = "Number of application tasks maintained by the ECS service."
  type        = number
  default     = 1

  validation {
    condition     = var.ecs_desired_count >= 1
    error_message = "ecs_desired_count must be at least 1."
  }
}

variable "ecs_assign_public_ip" {
  description = "Whether demo tasks receive public IPs for outbound API access. Disable when private subnets have NAT or VPC endpoints."
  type        = bool
  default     = true
}

variable "alb_deletion_protection_enabled" {
  description = "Whether deletion protection is enabled for the ALB."
  type        = bool
  default     = false
}

variable "ecr_untagged_retention_days" {
  description = "Number of days untagged images are retained."
  type        = number
  default     = 7

  validation {
    condition     = var.ecr_untagged_retention_days >= 1
    error_message = "ecr_untagged_retention_days must be at least 1."
  }
}

variable "cloudwatch_log_retention_days" {
  description = "Number of days application logs are retained."
  type        = number
  default     = 30

  validation {
    condition = contains(
      [1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096],
      var.cloudwatch_log_retention_days
    )
    error_message = "cloudwatch_log_retention_days must be a supported retention value."
  }
}

variable "cloudwatch_log_kms_key_arn" {
  description = "Optional KMS key ARN used to encrypt the CloudWatch log group."
  type        = string
  default     = null

  validation {
    condition = (
      var.cloudwatch_log_kms_key_arn == null ||
      can(regex("^arn:aws[a-zA-Z-]*:kms:", var.cloudwatch_log_kms_key_arn))
    )
    error_message = "cloudwatch_log_kms_key_arn must be null or a valid KMS key ARN."
  }
}

variable "permissions_boundary_arn" {
  description = "Optional permissions boundary applied to ECS IAM roles."
  type        = string
  default     = null
}

variable "openai_model" {
  description = "Approved OpenAI model identifier used by the Strands agent."
  type        = string

  validation {
    condition     = length(trimspace(var.openai_model)) > 0
    error_message = "openai_model cannot be empty."
  }
}

variable "max_document_size_mb" {
  description = "Maximum supported S3 document size in MiB."
  type        = number
  default     = 50

  validation {
    condition     = var.max_document_size_mb >= 1 && var.max_document_size_mb <= 500
    error_message = "max_document_size_mb must be between 1 and 500."
  }
}

variable "agent_max_search_results" {
  description = "Maximum number of knowledge chunks returned to the agent."
  type        = number
  default     = 5

  validation {
    condition     = var.agent_max_search_results >= 1 && var.agent_max_search_results <= 10
    error_message = "agent_max_search_results must be between 1 and 10."
  }
}

variable "github_enabled" {
  description = "Whether registry-mapped GitHub README ingestion is enabled."
  type        = bool
  default     = false
}

variable "admin_reindex_enabled" {
  description = "Whether ECS receives the secret required by the administrative reindex endpoint."
  type        = bool
  default     = false
}

variable "slack_enabled" {
  description = "Whether the optional Slack delivery channel is enabled."
  type        = bool
  default     = false
}

variable "slack_max_message_length" {
  description = "Maximum Slack response length."
  type        = number
  default     = 3500

  validation {
    condition     = var.slack_max_message_length >= 500 && var.slack_max_message_length <= 4000
    error_message = "slack_max_message_length must be between 500 and 4000."
  }
}

variable "slack_conversation_window" {
  description = "Maximum recent Strands conversation messages retained per Slack thread."
  type        = number
  default     = 20

  validation {
    condition     = var.slack_conversation_window >= 6 && var.slack_conversation_window <= 100
    error_message = "slack_conversation_window must be between 6 and 100."
  }
}

variable "feedback_prefix" {
  description = "S3 prefix used for privacy-safe Slack feedback events."
  type        = string
  default     = "feedback/slack"

  validation {
    condition = (
      length(trimspace(var.feedback_prefix)) > 0 &&
      !startswith(var.feedback_prefix, "/")
    )
    error_message = "feedback_prefix must be non-empty and must not start with '/'."
  }
}

variable "vector_bucket_name" {
  description = "Name of the S3 vector bucket."
  type        = string

  validation {
    condition = (
      length(var.vector_bucket_name) >= 3 &&
      length(var.vector_bucket_name) <= 63 &&
      can(regex("^[a-z0-9-]+$", var.vector_bucket_name))
    )

    error_message = "vector_bucket_name must contain only lowercase letters, numbers and hyphens."
  }
}

variable "diagram_prefix" {
  description = "S3 prefix holding rendered Slack flow diagrams."
  type        = string
  default     = "diagrams/slack"
}

variable "registry_appconfig_enabled" {
  description = "Serve the component registry through AWS AppConfig."
  type        = bool
  default     = false
}

variable "registry_bake_time_in_minutes" {
  description = "Minutes AppConfig monitors alarms before a registry deployment is final."
  type        = number
  default     = 5
}

variable "registry_publish_enabled" {
  description = "Create the IAM role the component registry repository assumes to publish."
  type        = bool
  default     = false
}

variable "create_github_oidc_provider" {
  description = "Create the account-wide GitHub Actions OIDC provider rather than reusing an existing one."
  type        = bool
  default     = true
}

variable "registry_repository" {
  description = "GitHub repository allowed to publish the component registry."
  type        = string
  default     = "example-org/kip-component-registry"
}

variable "registry_version_retention_days" {
  description = "Days a superseded component registry version stays available for rollback."
  type        = number
  default     = 90
}

variable "registry_prefix" {
  description = "S3 prefix holding the published component registry document."
  type        = string
  default     = "registry"
}

variable "vector_index_name" {
  description = "Name of the platform knowledge vector index."
  type        = string
  default     = "platform-knowledge"
}

variable "vector_dimensions" {
  description = "Number of dimensions in each embedding."
  type        = number
  default     = 1536

  validation {
    condition = (
      var.vector_dimensions >= 1 &&
      var.vector_dimensions <= 4096
    )

    error_message = "vector_dimensions must be between 1 and 4096."
  }
}

variable "embedding_model" {
  description = "OpenAI embedding model used for ingestion and search."
  type        = string
  default     = "text-embedding-3-small"
}

variable "embedding_batch_size" {
  description = "Number of chunks embedded in each ingestion request."
  type        = number
  default     = 16

  validation {
    condition     = var.embedding_batch_size >= 1 && var.embedding_batch_size <= 256
    error_message = "embedding_batch_size must be between 1 and 256."
  }
}

variable "visual_analysis_enabled" {
  description = "Whether ingestion uses a vision-capable Strands agent to understand PDF diagrams."
  type        = bool
  default     = true
}

variable "visual_analysis_model" {
  description = "Optional vision-capable model override; empty uses openai_model."
  type        = string
  default     = ""
}

variable "visual_render_dpi" {
  description = "DPI used to render candidate diagram pages."
  type        = number
  default     = 144

  validation {
    condition     = var.visual_render_dpi >= 72 && var.visual_render_dpi <= 300
    error_message = "visual_render_dpi must be between 72 and 300."
  }
}

variable "visual_max_pages_per_document" {
  description = "Maximum candidate diagram pages analyzed per PDF."
  type        = number
  default     = 10

  validation {
    condition     = var.visual_max_pages_per_document >= 1 && var.visual_max_pages_per_document <= 100
    error_message = "visual_max_pages_per_document must be between 1 and 100."
  }
}

variable "vector_top_k" {
  description = "Maximum semantic results considered for each query."
  type        = number
  default     = 25

  validation {
    condition     = var.vector_top_k >= 1 && var.vector_top_k <= 100
    error_message = "vector_top_k must be between 1 and 100."
  }
}
