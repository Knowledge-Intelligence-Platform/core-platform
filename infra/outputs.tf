output "aws_region" {
  description = "AWS region containing the application infrastructure."
  value       = var.aws_region
}

output "vpc_id" {
  description = "VPC created for the Core Platform deployment."
  value       = aws_vpc.this.id
}

output "public_subnet_ids" {
  description = "Public subnet IDs used by the Application Load Balancer."
  value       = aws_subnet.public[*].id
}

output "ecr_repository_url" {
  description = "Repository URL used to publish the application container image."
  value       = aws_ecr_repository.application.repository_url
}

output "application_secret_arn" {
  description = "ARN of the application Secrets Manager secret."
  value       = try(data.aws_secretsmanager_secret.application[0].arn, null)
}

output "ecs_execution_role_arn" {
  description = "ARN assumed by ECS while starting application tasks."
  value       = aws_iam_role.ecs_execution.arn
}

output "ecs_task_role_arn" {
  description = "ARN assumed by the running application task."
  value       = aws_iam_role.ecs_task.arn
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
  value       = one(aws_ecs_cluster.application[*].arn)
}

output "ecs_task_definition_arn" {
  description = "ARN of the deployed ECS task definition revision."
  value       = one(aws_ecs_task_definition.application[*].arn)
}

output "ecs_service_name" {
  description = "Name of the ECS service registered with the ALB target group."
  value       = one(aws_ecs_service.application[*].name)
}

output "knowledge_bucket_name" {
  description = "Bucket holding feedback and task records."
  value       = var.knowledge_bucket_name
}

output "knowledge_base_id" {
  value = aws_bedrockagent_knowledge_base.this.id
}

output "knowledge_base_data_source_id" {
  value = aws_bedrockagent_data_source.confluence.data_source_id
}

output "bedrock_model_id" {
  value = var.bedrock_model_id
}

output "task_state_machine_arn" {
  description = "Step Functions workflow that runs approved tasks, when task_runner is step_functions."
  value       = try(aws_sfn_state_machine.tasks[0].arn, "")
}
