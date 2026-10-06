variable "name_prefix" {
  description = "Prefix for every resource this deployment creates. One tenant, one prefix."
  type        = string
  default     = "knowledge-intelligence"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,26}[a-z0-9]$", var.name_prefix)) && !startswith(var.name_prefix, "internal-")
    error_message = "name_prefix must be 3-28 characters of lowercase letters, digits and hyphens, start with a letter, end with a letter or digit, and not start with \"internal-\"."
  }
}

variable "application_secret_name" {
  description = "Secrets Manager secret containing the enabled application credentials."
  type        = string
  default     = "knowledge-intelligence/application"

  validation {
    condition     = length(trimspace(var.application_secret_name)) > 0
    error_message = "application_secret_name cannot be empty."
  }
}

variable "aws_region" {
  description = "AWS region where Knowledge Intelligence resources are deployed."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "aws_region must be us-east-1."
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

variable "vpc_cidr" {
  description = "CIDR block for the Core Platform VPC."
  type        = string

  validation {
    condition     = can(cidrnetmask(var.vpc_cidr))
    error_message = "vpc_cidr must be a valid IPv4 CIDR block."
  }
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for the public subnets used by the ALB and ECS service."
  type        = list(string)

  validation {
    condition = (
      length(var.public_subnet_cidrs) >= 2 &&
      length(var.public_subnet_cidrs) <= 3 &&
      alltrue([for cidr in var.public_subnet_cidrs : can(cidrnetmask(cidr))])
    )
    error_message = "public_subnet_cidrs must contain two or three valid IPv4 CIDR blocks."
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

variable "tasks_enabled" {
  description = "Enable approval-gated knowledge-source tasks through the authenticated API."
  type        = bool
  default     = false

  validation {
    condition = !var.tasks_enabled || (
      var.query_api_enabled
      && length(var.task_allowed_identities) > 0
      && alltrue([for requester in var.task_allowed_identities : length(setsubtract(var.task_approver_identities, [requester])) > 0])
    )
    error_message = "Tasks require the query API, requester identities and an approver other than each requester."
  }
}

variable "task_allowed_identities" {
  description = "Query identities allowed to request, inspect and resume their own sync tasks."
  type        = set(string)
  default     = []
}

variable "task_approver_identities" {
  description = "Query identities allowed to approve or reject sync tasks requested by someone else."
  type        = set(string)
  default     = []
}

variable "task_prefix" {
  description = "Dedicated S3 prefix for durable task records."
  type        = string
  default     = "tasks"

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9/_-]*$", var.task_prefix))
    error_message = "Use a non-empty S3 prefix containing letters, digits, slash, underscore or hyphen."
  }
}

variable "bedrock_prompt_caching_enabled" {
  description = "Add an explicit cache checkpoint after stable system instructions; requires model support."
  type        = bool
  default     = false
}

variable "bedrock_model_id" {
  description = "Amazon model invoked by the Strands agent through Bedrock."
  type        = string
  default     = "amazon.nova-lite-v1:0"

  validation {
    condition     = startswith(var.bedrock_model_id, "amazon.")
    error_message = "bedrock_model_id must identify an Amazon foundation model."
  }
}

variable "bedrock_max_tokens" {
  description = "Maximum generated tokens for each model response."
  type        = number
  default     = 4096

  validation {
    condition     = var.bedrock_max_tokens >= 256 && var.bedrock_max_tokens <= 10000 && floor(var.bedrock_max_tokens) == var.bedrock_max_tokens
    error_message = "bedrock_max_tokens must be an integer from 256 to 10000."
  }
}

variable "application_enabled" {
  description = "Enable ECS application resources once the runtime deployment is ready."
  type        = bool
  default     = false
}

variable "query_api_enabled" {
  description = "Inject the QUERY_TOKENS identity mapping from the application secret."
  type        = bool
  default     = false
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

variable "aws_account_id" {
  description = "Account authorized to host this deployment."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must contain 12 digits."
  }
}

variable "knowledge_base_name" {
  description = "Name of the managed Bedrock knowledge base."
  type        = string
}

variable "knowledge_base_role_arn" {
  description = "Existing Bedrock execution role ARN; this stack does not manage its policies."
  type        = string
}

variable "confluence_data_source_name" {
  description = "Name of the managed Confluence connector."
  type        = string
}

variable "confluence_connector_parameters" {
  description = "Confluence connector JSON, including the credentials secret ARN, never secret values."
  type        = string

  validation {
    condition = try(
      jsondecode(var.confluence_connector_parameters).type == "CONFLUENCE" &&
      startswith(
        jsondecode(var.confluence_connector_parameters).connectionConfiguration.secretArn,
        "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:"
      ),
      false
    )
    error_message = "Provide Confluence connector JSON referencing a secret in the configured account and region."
  }
}

variable "data_deletion_policy" {
  description = "Whether Bedrock deletes indexed content if the data source is removed."
  type        = string
  default     = "DELETE"

  validation {
    condition     = contains(["DELETE", "RETAIN"], var.data_deletion_policy)
    error_message = "data_deletion_policy must be DELETE or RETAIN."
  }
}

variable "sync_deletion_protection" {
  description = "Protection against large deletions during connector syncs."
  type = object({
    enabled   = bool
    threshold = number
  })
}

variable "media_extraction" {
  description = "Media types extracted by the managed connector."
  type = object({
    image = bool
    audio = bool
    video = bool
  })
}

variable "tags" {
  description = "Knowledge base tags. Match existing tags when importing."
  type        = map(string)
  default     = null
}
