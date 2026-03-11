variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used as a prefix for all resources"
  type        = string
  default     = "steampulse"
}

variable "environment" {
  description = "Deployment environment (staging, production)"
  type        = string
  default     = "production"
}

variable "db_username" {
  description = "PostgreSQL master username"
  type        = string
  default     = "steampulse"
  sensitive   = true
}

variable "db_password" {
  description = "PostgreSQL master password"
  type        = string
  sensitive   = true
}

variable "db_name" {
  description = "PostgreSQL database name"
  type        = string
  default     = "steampulse"
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
}

variable "lambda_memory_mb" {
  description = "Lambda function memory in MB"
  type        = number
  default     = 512
}

variable "lambda_timeout_sec" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 300
}

variable "lambda_zip_path" {
  description = "Path to the Lambda deployment ZIP"
  type        = string
  default     = "../dist/crawler.zip"
}

variable "crawler_schedule" {
  description = "EventBridge cron for seeding the crawler queue (UTC)"
  type        = string
  default     = "cron(0 3 * * ? *)"  # Daily at 03:00 UTC
}

variable "vpc_id" {
  description = "VPC ID for RDS and Lambda (optional — uses default VPC if empty)"
  type        = string
  default     = ""
}

variable "subnet_ids" {
  description = "Subnet IDs for RDS subnet group"
  type        = list(string)
  default     = []
}
