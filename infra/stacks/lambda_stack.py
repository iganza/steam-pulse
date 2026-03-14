"""LambdaStack — crawler Lambda functions and EventBridge schedules."""
import aws_cdk as cdk
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_events as events
import aws_cdk.aws_events_targets as events_targets
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_lambda_event_sources as event_sources
import aws_cdk.aws_logs as logs
import aws_cdk.aws_sqs as sqs
import aws_cdk.aws_ssm as ssm
from constructs import Construct


class LambdaStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        is_production: bool = False,
        stage: str = "staging",
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Deploy-time SSM references
        vpc_sg_id = ssm.StringParameter.value_for_string_parameter(
            self, f"/steampulse/{stage}/network/vpc-sg-id"
        )
        intra_sg = ec2.SecurityGroup.from_security_group_id(self, "IntraSg", vpc_sg_id)

        library_layer_arn = ssm.StringParameter.value_for_string_parameter(
            self, f"/steampulse/{stage}/common/library-layer-arn"
        )
        library_layer = lambda_.LayerVersion.from_layer_version_arn(
            self, "LibraryLayer", library_layer_arn
        )

        app_queue_arn = ssm.StringParameter.value_for_string_parameter(
            self, f"/steampulse/{stage}/sqs/app-crawl-queue-arn"
        )
        app_queue_url = ssm.StringParameter.value_for_string_parameter(
            self, f"/steampulse/{stage}/sqs/app-crawl-queue-url"
        )
        app_queue = sqs.Queue.from_queue_arn(self, "AppQueue", app_queue_arn)

        review_queue_arn = ssm.StringParameter.value_for_string_parameter(
            self, f"/steampulse/{stage}/sqs/review-crawl-queue-arn"
        )
        review_queue_url = ssm.StringParameter.value_for_string_parameter(
            self, f"/steampulse/{stage}/sqs/review-crawl-queue-url"
        )
        review_queue = sqs.Queue.from_queue_arn(self, "ReviewQueue", review_queue_arn)

        db_secret_arn = ssm.StringParameter.value_for_string_parameter(
            self, f"/steampulse/{stage}/data/db-secret-arn"
        )

        sfn_arn = ssm.StringParameter.value_for_string_parameter(
            self, f"/steampulse/{stage}/analysis/state-machine-arn"
        )
        steam_api_key = ssm.StringParameter.value_for_string_parameter(
            self, f"/steampulse/{stage}/steam-api-key"
        )

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
        role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
            resources=[db_secret_arn],
        ))
        review_queue.grant_send_messages(role)
        app_queue.grant_send_messages(role)

        common_env = {
            "DB_SECRET_ARN": db_secret_arn,
            "SFN_ARN": sfn_arn,
            "STEAM_API_KEY": steam_api_key,
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
            function_name=f"{stage}-steampulse-app-crawler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_functions.app_crawler.handler.handler",
            code=lambda_.Code.from_asset("src/lambda-functions"),
            layers=[library_layer],
            role=role,
            vpc=vpc,
            vpc_subnets=lambda_subnets,
            security_groups=[intra_sg],
            allow_public_subnet=not is_production,
            timeout=cdk.Duration.minutes(5),
            tracing=lambda_.Tracing.ACTIVE,
            environment={
                **common_env,
                "REVIEW_CRAWL_QUEUE_URL": review_queue_url,
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
            function_name=f"{stage}-steampulse-review-crawler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_functions.review_crawler.handler.handler",
            code=lambda_.Code.from_asset("src/lambda-functions"),
            layers=[library_layer],
            role=role,
            vpc=vpc,
            vpc_subnets=lambda_subnets,
            security_groups=[intra_sg],
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

        # Catalog refresher Lambda — EventBridge weekly schedule
        # Fetches full Steam app list, upserts new appids into app_catalog,
        # enqueues all pending appids onto app-crawl-queue.
        catalog_refresher_log_group = logs.LogGroup(
            self,
            "CatalogRefresherLogs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        self.catalog_refresher_fn = lambda_.Function(
            self,
            "CatalogRefresher",
            function_name=f"{stage}-steampulse-catalog-refresher",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_functions.catalog_refresher.handler.handler",
            code=lambda_.Code.from_asset("src/lambda-functions"),
            layers=[library_layer],
            role=role,
            vpc=vpc,
            vpc_subnets=lambda_subnets,
            security_groups=[intra_sg],
            allow_public_subnet=not is_production,
            # GetAppList + bulk upsert + batch SQS enqueue can take a few minutes
            timeout=cdk.Duration.minutes(10),
            tracing=lambda_.Tracing.ACTIVE,
            environment={
                **common_env,
                "APP_CRAWL_QUEUE_URL": app_queue_url,
                "POWERTOOLS_SERVICE_NAME": "catalog-refresher",
                "POWERTOOLS_METRICS_NAMESPACE": "SteamPulse",
            },
            log_group=catalog_refresher_log_group,
        )
        # Uncomment to enable weekly schedule (every Sunday at 02:00 UTC)
        # events.Rule(
        #     self,
        #     "CatalogRefreshSchedule",
        #     schedule=events.Schedule.cron(minute="0", hour="2", week_day="SUN"),
        #     targets=[events_targets.LambdaFunction(self.catalog_refresher_fn)],
        # )
