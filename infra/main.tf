terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Uncomment and configure for remote state:
  # backend "s3" {
  #   bucket = "steampulse-tfstate"
  #   key    = "production/terraform.tfstate"
  #   region = "us-east-1"
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# ── Data sources ────────────────────────────────────────────────────────────

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

# Use default VPC/subnets when none specified
data "aws_vpc" "default" {
  count   = var.vpc_id == "" ? 1 : 0
  default = true
}

data "aws_subnets" "default" {
  count = var.vpc_id == "" && length(var.subnet_ids) == 0 ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default[0].id]
  }
}

locals {
  vpc_id     = var.vpc_id != "" ? var.vpc_id : (length(data.aws_vpc.default) > 0 ? data.aws_vpc.default[0].id : "")
  subnet_ids = length(var.subnet_ids) > 0 ? var.subnet_ids : (length(data.aws_subnets.default) > 0 ? data.aws_subnets.default[0].ids : [])
}

# ── Security Group for RDS ───────────────────────────────────────────────────

resource "aws_security_group" "rds" {
  name        = "${var.project_name}-rds-sg"
  description = "Allow PostgreSQL access from Lambda"
  vpc_id      = local.vpc_id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    security_groups = [aws_security_group.lambda.id]
    description = "PostgreSQL from Lambda"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-rds-sg"
  }
}

resource "aws_security_group" "lambda" {
  name        = "${var.project_name}-lambda-sg"
  description = "Lambda crawler outbound access"
  vpc_id      = local.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound (Steam API, SteamSpy)"
  }

  tags = {
    Name = "${var.project_name}-lambda-sg"
  }
}

# ── RDS PostgreSQL ───────────────────────────────────────────────────────────

resource "aws_db_subnet_group" "postgres" {
  name       = "${var.project_name}-subnet-group"
  subnet_ids = local.subnet_ids

  tags = {
    Name = "${var.project_name}-subnet-group"
  }
}

resource "aws_db_instance" "postgres" {
  identifier        = "${var.project_name}-db"
  engine            = "postgres"
  engine_version    = "15.6"
  instance_class    = var.db_instance_class
  allocated_storage = 20
  storage_type      = "gp3"

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.postgres.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  # Cost-saving settings for V2 POC
  multi_az               = false
  publicly_accessible    = false
  skip_final_snapshot    = true
  deletion_protection    = false
  backup_retention_period = 7
  backup_window          = "03:00-04:00"
  maintenance_window     = "sun:04:00-sun:05:00"

  performance_insights_enabled = false
  monitoring_interval          = 0

  tags = {
    Name = "${var.project_name}-db"
  }
}

# ── SQS Queue ────────────────────────────────────────────────────────────────

resource "aws_sqs_queue" "crawler_queue" {
  name                      = "${var.project_name}-crawler-queue"
  visibility_timeout_seconds = var.lambda_timeout_sec + 30
  message_retention_seconds  = 86400   # 1 day
  receive_wait_time_seconds  = 20      # Long polling

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.crawler_dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Name = "${var.project_name}-crawler-queue"
  }
}

resource "aws_sqs_queue" "crawler_dlq" {
  name                      = "${var.project_name}-crawler-dlq"
  message_retention_seconds = 1209600  # 14 days

  tags = {
    Name = "${var.project_name}-crawler-dlq"
  }
}

# ── IAM Role for Lambda ──────────────────────────────────────────────────────

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_exec" {
  name               = "${var.project_name}-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "lambda_policy" {
  # CloudWatch Logs
  statement {
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"]
  }

  # SQS — read from crawler queue
  statement {
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ChangeMessageVisibility",
    ]
    resources = [
      aws_sqs_queue.crawler_queue.arn,
      aws_sqs_queue.crawler_dlq.arn,
    ]
  }

  # SQS — send to queue (for seeding)
  statement {
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.crawler_queue.arn]
  }

  # VPC networking (ENI management for VPC Lambda)
  statement {
    effect = "Allow"
    actions = [
      "ec2:CreateNetworkInterface",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DeleteNetworkInterface",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "lambda_policy" {
  name   = "${var.project_name}-lambda-policy"
  policy = data.aws_iam_policy_document.lambda_policy.json
}

resource "aws_iam_role_policy_attachment" "lambda_attach" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_policy.arn
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# ── Lambda Function ──────────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "crawler_logs" {
  name              = "/aws/lambda/${var.project_name}-crawler"
  retention_in_days = 14
}

resource "aws_lambda_function" "crawler" {
  function_name = "${var.project_name}-crawler"
  role          = aws_iam_role.lambda_exec.arn
  filename      = var.lambda_zip_path
  handler       = "steampulse.crawler.handler.handler"
  runtime       = "python3.10"
  timeout       = var.lambda_timeout_sec
  memory_size   = var.lambda_memory_mb

  source_code_hash = fileexists(var.lambda_zip_path) ? filebase64sha256(var.lambda_zip_path) : null

  vpc_config {
    subnet_ids         = local.subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      DATABASE_URL = "postgresql://${var.db_username}:${var.db_password}@${aws_db_instance.postgres.endpoint}/${var.db_name}"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.crawler_logs,
    aws_iam_role_policy_attachment.lambda_attach,
  ]

  tags = {
    Name = "${var.project_name}-crawler"
  }
}

# ── SQS → Lambda trigger ─────────────────────────────────────────────────────

resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  event_source_arn = aws_sqs_queue.crawler_queue.arn
  function_name    = aws_lambda_function.crawler.arn
  batch_size       = 10
  enabled          = true
}

# ── EventBridge — daily seeder ───────────────────────────────────────────────

data "aws_iam_policy_document" "eventbridge_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eventbridge_scheduler" {
  name               = "${var.project_name}-eventbridge-role"
  assume_role_policy = data.aws_iam_policy_document.eventbridge_assume.json
}

data "aws_iam_policy_document" "eventbridge_policy" {
  statement {
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.crawler_queue.arn]
  }
}

resource "aws_iam_policy" "eventbridge_policy" {
  name   = "${var.project_name}-eventbridge-policy"
  policy = data.aws_iam_policy_document.eventbridge_policy.json
}

resource "aws_iam_role_policy_attachment" "eventbridge_attach" {
  role       = aws_iam_role.eventbridge_scheduler.name
  policy_arn = aws_iam_policy.eventbridge_policy.arn
}

# CloudWatch Events rule (classic EventBridge)
resource "aws_cloudwatch_event_rule" "daily_seed" {
  name                = "${var.project_name}-daily-seed"
  description         = "Daily trigger to seed the crawler SQS queue with popular Steam app IDs"
  schedule_expression = var.crawler_schedule
  state               = "ENABLED"

  tags = {
    Name = "${var.project_name}-daily-seed"
  }
}

# Lambda seeder function — sends app IDs to SQS on a schedule
resource "aws_cloudwatch_event_target" "daily_seed_target" {
  rule      = aws_cloudwatch_event_rule.daily_seed.name
  target_id = "${var.project_name}-seed-lambda"
  arn       = aws_lambda_function.crawler.arn

  # The event payload instructs the handler to run in "seed" mode
  input = jsonencode({
    source  = "scheduled-seed"
    action  = "seed_queue"
    appids  = []  # Populated by a separate seeder or kept empty to trigger SteamSpy top-100
  })
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.crawler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_seed.arn
}
