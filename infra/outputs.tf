output "aws_region" {
  description = "AWS region containing the application infrastructure."
  value       = var.aws_region
}

output "ecr_repository_url" {
  description = "Repository URL used to publish the application container image."
  value       = aws_ecr_repository.application.repository_url
}

output "application_secret_arn" {
  description = "ARN of the application Secrets Manager secret."
  value       = data.aws_secretsmanager_secret.application.arn
}

output "ecs_execution_role_arn" {
  description = "ARN assumed by ECS while starting application tasks."
  value       = aws_iam_role.ecs_execution.arn
}

output "ecs_task_role_arn" {
  description = "ARN assumed by the running application task."
  value       = aws_iam_role.ecs_task.arn
}

output "vector_ingestion_role_arn" {
  value       = aws_iam_role.vector_ingestion.arn
  description = "Role for the explicit vector ingestion command."
}

output "cloudwatch_log_group_name" {
  description = "CloudWatch Logs group used by the application container."
  value       = aws_cloudwatch_log_group.application.name
}

output "alb_arn" {
  description = "ARN of the Knowledge Intelligence Application Load Balancer."
  value       = aws_lb.application.arn
}

output "alb_http_url" {
  description = "Temporary unencrypted URL for the stakeholder demo."
  value       = "http://${aws_lb.application.dns_name}"
}

output "alb_listener_arn" {
  description = "ARN of the HTTP listener."
  value       = aws_lb_listener.http.arn
}

output "api_gateway_url" {
  description = "AWS-managed HTTPS endpoint for the Knowledge Intelligence API."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "slack_events_url" {
  description = "HTTPS endpoint to configure as the Slack Events API Request URL."
  value       = "${trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")}/slack/events"
}

output "slack_interactivity_url" {
  description = "HTTPS endpoint to configure for Slack Block Kit interactions."
  value       = "${trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")}/slack/events"
}

output "target_group_arn" {
  description = "ARN of the FastAPI target group."
  value       = aws_lb_target_group.application.arn
}

output "ecs_cluster_arn" {
  description = "ARN of the ECS cluster."
  value       = aws_ecs_cluster.application.arn
}

output "ecs_task_definition_arn" {
  description = "ARN of the deployed ECS task definition revision."
  value       = aws_ecs_task_definition.application.arn
}

output "ecs_service_name" {
  description = "Name of the ECS service registered with the ALB target group."
  value       = aws_ecs_service.application.name
}

output "vector_bucket_name" {
  value       = aws_s3vectors_vector_bucket.platform_knowledge.vector_bucket_name
  description = "Name of the S3 Vector bucket."
}

output "vector_bucket_arn" {
  value       = aws_s3vectors_vector_bucket.platform_knowledge.vector_bucket_arn
  description = "ARN of the S3 Vector bucket."
}

output "vector_index_name" {
  value       = aws_s3vectors_index.platform_knowledge.index_name
  description = "Name of the platform knowledge vector index."
}

output "vector_index_arn" {
  value       = aws_s3vectors_index.platform_knowledge.index_arn
  description = "ARN of the platform knowledge vector index."
}

output "registry_appconfig_application_id" {
  description = "AppConfig application id for the component registry."
  value       = var.registry_appconfig_enabled ? aws_appconfig_application.registry[0].id : ""
}

output "registry_appconfig_environment_id" {
  description = "AppConfig environment id for the component registry."
  value       = var.registry_appconfig_enabled ? aws_appconfig_environment.registry[0].environment_id : ""
}

output "registry_appconfig_profile_id" {
  description = "AppConfig configuration profile id for the component registry."
  value       = var.registry_appconfig_enabled ? aws_appconfig_configuration_profile.registry[0].configuration_profile_id : ""
}

output "registry_appconfig_strategy_id" {
  description = "AppConfig deployment strategy id for the component registry."
  value       = var.registry_appconfig_enabled ? aws_appconfig_deployment_strategy.registry[0].id : ""
}

output "registry_publish_role_arn" {
  description = "Role the component registry repository assumes to publish and deploy."
  value       = var.registry_publish_enabled ? aws_iam_role.registry_publish[0].arn : ""
}

output "knowledge_bucket_name" {
  description = "Bucket holding the Confluence sources, chunks, diagrams and published registry."
  value       = var.knowledge_bucket_name
}

output "registry_document_key" {
  description = "Key of the published component registry document."
  value       = "${trim(var.registry_prefix, "/")}/registry.yaml"
}
