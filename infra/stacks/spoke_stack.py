"""CrawlSpokeStack — multi-purpose crawl worker for a remote AWS region.

One Lambda, two event sources (metadata + reviews), reserved concurrency = 3.
No DB access. Connects to public internet (Steam) and cross-region S3/SQS.
"""

import aws_cdk as cdk
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_lambda_event_sources as event_sources
import aws_cdk.aws_logs as logs
import aws_cdk.aws_sqs as sqs
import aws_cdk.aws_ssm as ssm
from aws_cdk.aws_lambda_python_alpha import PythonFunction, PythonLayerVersion
from constructs import Construct
from library_layer.config import SteamPulseConfig


class CrawlSpokeStack(cdk.Stack):

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: SteamPulseConfig,
        primary_region: str,
        app_crawl_queue_arn: str,
        review_crawl_queue_arn: str,
        spoke_results_queue_url: str,
        assets_bucket_name: str,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        spoke_region = cdk.Stack.of(self).region
        account = cdk.Stack.of(self).account

        library_layer = PythonLayerVersion(
            self, "LibraryLayer",
            entry="src/library-layer",
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description=f"SteamPulse shared layer (spoke-{spoke_region})",
        )

        role = iam.Role(
            self, "SpokeCrawlerRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole",
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaSQSQueueExecutionRole",
                ),
            ],
        )

        # Cross-region SQS: read both work queues
        role.add_to_policy(iam.PolicyStatement(
            actions=[
                "sqs:ReceiveMessage", "sqs:DeleteMessage",
                "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility",
            ],
            resources=[app_crawl_queue_arn, review_crawl_queue_arn],
        ))

        # Cross-region SQS: write to results queue
        # Construct ARN from URL: https://sqs.{region}.amazonaws.com/{account}/{name}
        spoke_results_queue_arn = (
            f"arn:aws:sqs:{primary_region}:{account}:"
            + spoke_results_queue_url.rsplit("/", 1)[-1]
        )
        role.add_to_policy(iam.PolicyStatement(
            actions=["sqs:SendMessage"],
            resources=[spoke_results_queue_arn],
        ))

        # Cross-region S3: write results
        role.add_to_policy(iam.PolicyStatement(
            actions=["s3:PutObject"],
            resources=[f"arn:aws:s3:::{assets_bucket_name}/spoke-results/*"],
        ))

        # Cross-region Secrets Manager: Steam API key only
        steam_api_key_secret_arn = (
            f"arn:aws:secretsmanager:{primary_region}:{account}"
            f":secret:{config.STEAM_API_KEY_SECRET_NAME}-??????"
        )
        role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue"],
            resources=[steam_api_key_secret_arn],
        ))

        crawler_fn = PythonFunction(
            self, "SpokeCrawlerFn",
            entry="src/lambda-functions",
            index="lambda_functions/crawler/spoke_handler.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[library_layer],
            role=role,
            timeout=cdk.Duration.minutes(10),
            memory_size=256,
            reserved_concurrent_executions=3,
            tracing=lambda_.Tracing.ACTIVE,
            log_group=logs.LogGroup(self, "SpokeLogs",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment=config.to_lambda_env(
                # Spoke Lambda uses inline env — cross-region stack, can't resolve
                # SSM from primary region. ASSETS_BUCKET_PARAM_NAME is overridden
                # with the actual bucket name rather than an SSM path.
                PRIMARY_REGION=primary_region,
                SPOKE_RESULTS_QUEUE_URL=spoke_results_queue_url,
                ASSETS_BUCKET_PARAM_NAME=assets_bucket_name,
                POWERTOOLS_SERVICE_NAME=f"crawler-spoke-{spoke_region}",
                POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
            ),
        )

        # Two event sources — one per work type, shared concurrency pool
        for queue_arn, source_id in [
            (app_crawl_queue_arn, "AppCrawlSource"),
            (review_crawl_queue_arn, "ReviewCrawlSource"),
        ]:
            queue = sqs.Queue.from_queue_arn(self, source_id, queue_arn=queue_arn)
            crawler_fn.add_event_source(
                event_sources.SqsEventSource(
                    queue, batch_size=1, report_batch_item_failures=True,
                )
            )

        ssm.StringParameter(
            self, "SpokeStatus",
            parameter_name=f"/steampulse/{config.ENVIRONMENT}/spokes/{spoke_region}/status",
            string_value="active",
        )
