output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint (host:port)"
  value       = aws_db_instance.postgres.endpoint
  sensitive   = true
}

output "rds_database_url" {
  description = "Full DATABASE_URL for the application"
  value = "postgresql://${var.db_username}:${var.db_password}@${aws_db_instance.postgres.endpoint}/${var.db_name}"
  sensitive = true
}

output "sqs_queue_url" {
  description = "SQS crawler queue URL"
  value       = aws_sqs_queue.crawler_queue.url
}

output "sqs_queue_arn" {
  description = "SQS crawler queue ARN"
  value       = aws_sqs_queue.crawler_queue.arn
}

output "lambda_function_arn" {
  description = "Crawler Lambda function ARN"
  value       = aws_lambda_function.crawler.arn
}

output "lambda_function_name" {
  description = "Crawler Lambda function name"
  value       = aws_lambda_function.crawler.function_name
}

output "lambda_role_arn" {
  description = "Lambda IAM role ARN"
  value       = aws_iam_role.lambda_exec.arn
}

output "eventbridge_rule_arn" {
  description = "EventBridge rule ARN for daily crawler schedule"
  value       = aws_cloudwatch_event_rule.daily_seed.arn
}
