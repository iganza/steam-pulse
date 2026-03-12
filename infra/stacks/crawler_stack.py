"""Crawler stack — SQS queues + Lambda crawlers + EventBridge nightly schedule."""

import aws_cdk as cdk
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_events as events
import aws_cdk.aws_events_targets as targets
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_lambda_event_sources as event_sources
import aws_cdk.aws_logs as logs
import aws_cdk.aws_secretsmanager as secretsmanager
import aws_cdk.aws_sqs as sqs
from constructs import Construct

_PLACEHOLDER = "def handler(event, context): return {'statusCode': 200}"


class CrawlerStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.Vpc,
        db_secret: secretsmanager.ISecret,
        sfn_arn: str,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Dead-letter queues
        app_dlq = sqs.Queue(self, "AppCrawlDlq",
                            retention_period=cdk.Duration.days(14))
        review_dlq = sqs.Queue(self, "ReviewCrawlDlq",
                               retention_period=cdk.Duration.days(14))

        # App crawl queue — batch 10, 5 min visibility
        self.app_queue = sqs.Queue(
            self,
            "AppCrawlQueue",
            visibility_timeout=cdk.Duration.minutes(5),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=app_dlq,
            ),
        )

        # Review crawl queue — batch 1, 10 min visibility
        self.review_queue = sqs.Queue(
            self,
            "ReviewCrawlQueue",
            visibility_timeout=cdk.Duration.minutes(10),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=review_dlq,
            ),
        )

        # Shared IAM role
        role = iam.Role(
            self,
            "CrawlerRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole"
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaSQSQueueExecutionRole"
                ),
            ],
        )
        db_secret.grant_read(role)

        common_env = {
            "DB_SECRET_ARN": db_secret.secret_arn,
            "SFN_ARN": sfn_arn,
        }

        # App crawler Lambda — triggered by app-crawl-queue
        app_crawler_log_group = logs.LogGroup(
            self,
            "AppCrawlerLogs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        app_crawler = lambda_.Function(
            self,
            "AppCrawler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="app_crawler.handler",
            code=lambda_.Code.from_inline(_PLACEHOLDER),
            role=role,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            timeout=cdk.Duration.minutes(5),
            environment=common_env,
            log_group=app_crawler_log_group,
        )
        app_crawler.add_event_source(
            event_sources.SqsEventSource(self.app_queue, batch_size=10)
        )

        # Review crawler Lambda — triggered by review-crawl-queue
        review_crawler_log_group = logs.LogGroup(
            self,
            "ReviewCrawlerLogs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        review_crawler = lambda_.Function(
            self,
            "ReviewCrawler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="review_crawler.handler",
            code=lambda_.Code.from_inline(_PLACEHOLDER),
            role=role,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            timeout=cdk.Duration.minutes(10),
            environment=common_env,
            log_group=review_crawler_log_group,
        )
        review_crawler.add_event_source(
            event_sources.SqsEventSource(self.review_queue, batch_size=1)
        )

        # EventBridge: nightly re-crawl of top 500 (kicks off app crawler)
        nightly_rule = events.Rule(
            self,
            "NightlyRecrawl",
            schedule=events.Schedule.cron(hour="2", minute="0"),
            description="Nightly re-crawl of top 500 games",
        )
        nightly_rule.add_target(
            targets.SqsQueue(self.app_queue)
        )
