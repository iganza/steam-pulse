"""LambdaStack — crawler Lambda functions and EventBridge schedules."""
import aws_cdk as cdk
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_lambda_event_sources as event_sources
import aws_cdk.aws_logs as logs
import aws_cdk.aws_secretsmanager as secretsmanager
import aws_cdk.aws_sqs as sqs
from aws_cdk.aws_lambda_python_alpha import PythonLayerVersion
from constructs import Construct


class LambdaStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        library_layer: PythonLayerVersion,
        app_queue: sqs.IQueue,
        review_queue: sqs.IQueue,
        vpc: ec2.Vpc,
        db_secret: secretsmanager.ISecret,
        sfn_arn: str,
        is_production: bool = False,
        stage: str = "staging",
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Staging: public subnets give free internet egress for Steam API calls.
        # Production: private subnets with NAT gateway for better isolation.
        lambda_subnet_type = (
            ec2.SubnetType.PRIVATE_WITH_EGRESS if is_production else ec2.SubnetType.PUBLIC
        )
        lambda_subnets = ec2.SubnetSelection(subnet_type=lambda_subnet_type)

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
        review_queue.grant_send_messages(role)

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
        self.app_crawler_fn = lambda_.Function(
            self,
            "AppCrawler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_functions.app_crawler.handler.handler",
            code=lambda_.Code.from_asset("src/lambda-functions"),
            layers=[library_layer],
            role=role,
            vpc=vpc,
            vpc_subnets=lambda_subnets,
            allow_public_subnet=not is_production,
            timeout=cdk.Duration.minutes(5),
            tracing=lambda_.Tracing.ACTIVE,
            environment={
                **common_env,
                "REVIEW_CRAWL_QUEUE_URL": review_queue.queue_url,
                "POWERTOOLS_SERVICE_NAME": "app-crawler",
                "POWERTOOLS_METRICS_NAMESPACE": "SteamPulse",
            },
            log_group=app_crawler_log_group,
        )
        self.app_crawler_fn.add_event_source(
            event_sources.SqsEventSource(
                app_queue,
                batch_size=10,
                report_batch_item_failures=True,
            )
        )

        # Review crawler Lambda — triggered by review-crawl-queue
        review_crawler_log_group = logs.LogGroup(
            self,
            "ReviewCrawlerLogs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        self.review_crawler_fn = lambda_.Function(
            self,
            "ReviewCrawler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_functions.review_crawler.handler.handler",
            code=lambda_.Code.from_asset("src/lambda-functions"),
            layers=[library_layer],
            role=role,
            vpc=vpc,
            vpc_subnets=lambda_subnets,
            allow_public_subnet=not is_production,
            timeout=cdk.Duration.minutes(10),
            tracing=lambda_.Tracing.ACTIVE,
            environment={
                **common_env,
                "POWERTOOLS_SERVICE_NAME": "review-crawler",
                "POWERTOOLS_METRICS_NAMESPACE": "SteamPulse",
            },
            log_group=review_crawler_log_group,
        )
        self.review_crawler_fn.add_event_source(
            event_sources.SqsEventSource(
                review_queue,
                batch_size=1,
                report_batch_item_failures=True,
            )
        )
