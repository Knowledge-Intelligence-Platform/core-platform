terraform {
  required_version = ">= 1.8.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.54, < 7.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

locals {
  name_prefix         = var.name_prefix
  alb_name            = local.name_prefix
  target_group_name   = "${local.name_prefix}-api"
  ecs_cluster_name    = local.name_prefix
  ecs_task_family     = local.name_prefix
  container_name      = local.name_prefix
  container_port      = 8000
  application_secret  = "${local.name_prefix}/application"
  cloudwatch_log_name = "/ecs/${local.name_prefix}"

  knowledge_s3_prefix = trimsuffix(
    trimspace(var.knowledge_s3_prefix),
    "/"
  )

  common_tags = merge(
    var.additional_tags,
    {
      Project   = "Knowledge-Intelligence"
      Component = "VectorSearch"
      ManagedBy = "Terraform"
    }
  )
}
