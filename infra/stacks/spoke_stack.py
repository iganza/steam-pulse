"""CrawlSpokeStack — multi-purpose crawl worker for a remote AWS region.

One Lambda per region, fed by a per-spoke SQS queue. The primary crawler
sends messages to the spoke queue; the Lambda consumes via event source
mapping with max_concurrency=3 for backpressure.
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
        environment: str,
        spoke_results_queue_url: str,
        assets_bucket_name: str,
        steam_api_key_secret_name: str,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        spoke_region = cdk.Stack.of(self).region
        account = cdk.Stack.of(self).account

        library_layer = PythonLayerVersion(
            self,
            "LibraryLayer",
            entry="src/library-layer",
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description=f"SteamPulse shared layer (spoke-{spoke_region})",
        )

        role = iam.Role(
            self,
            "SpokeCrawlerRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole",
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AWSXRayDaemonWriteAccess",
                ),
            ],
        )

        # Cross-region SQS: write to results queue
        spoke_results_queue_arn = (
            f"arn:aws:sqs:{primary_region}:{account}:" + spoke_results_queue_url.rsplit("/", 1)[-1]
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["sqs:SendMessage"],
                resources=[spoke_results_queue_arn],
            )
        )

        # Cross-region S3: write results
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:PutObject"],
                resources=[f"arn:aws:s3:::{assets_bucket_name}/spoke-results/*"],
            )
        )

        # Cross-region Secrets Manager: Steam API key only
        steam_api_key_secret_arn = (
            f"arn:aws:secretsmanager:{primary_region}:{account}"
            f":secret:{steam_api_key_secret_name}-*"
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[steam_api_key_secret_arn],
            )
        )

        # DLQ for spoke crawl queue — catches messages after 3 delivery attempts.
        spoke_dlq = sqs.Queue(
            self,
            "SpokeCrawlerDlq",
            retention_period=cdk.Duration.days(14),
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # Per-spoke crawl queue — deterministic name so primary crawler can
        # construct the URL without cross-region lookups.
        queue_name = f"steampulse-spoke-crawl-{spoke_region}-{environment}"
        spoke_crawl_queue = sqs.Queue(
            self,
            "SpokeCrawlQueue",
            queue_name=queue_name,
            visibility_timeout=cdk.Duration.minutes(12),
            retention_period=cdk.Duration.days(14),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=spoke_dlq,
            ),
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # Deterministic function name — primary handler constructs the queue URL
        # from config.spoke_region_list + this naming convention.
        fn_name = f"steampulse-spoke-crawler-{spoke_region}-{environment}"

        spoke_fn = PythonFunction(
            self,
            "SpokeCrawlerFn",
            function_name=fn_name,
            entry="src/lambda-functions",
            index="lambda_functions/crawler/spoke_handler.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[library_layer],
            role=role,
            timeout=cdk.Duration.minutes(10),
            memory_size=256,
            tracing=lambda_.Tracing.ACTIVE,
            log_group=logs.LogGroup(
                self,
                "SpokeLogs",
                log_group_name=f"/steampulse/{environment}/spoke/{spoke_region}",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment=config.to_lambda_env(
                # Spoke-specific overrides — cross-region stack can't resolve SSM,
                # so _PARAM_NAME fields hold ACTUAL values (not SSM paths).
                PRIMARY_REGION=primary_region,
                SPOKE_RESULTS_QUEUE_URL=spoke_results_queue_url,
                ASSETS_BUCKET_PARAM_NAME=assets_bucket_name,
                STEAM_API_KEY_SECRET_NAME=steam_api_key_secret_name,
                POWERTOOLS_SERVICE_NAME=f"crawler-spoke-{spoke_region}",
                POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
            ),
        )

        spoke_fn.add_event_source(
            event_sources.SqsEventSource(
                spoke_crawl_queue,
                batch_size=1,
                max_concurrency=3,
                report_batch_item_failures=True,
            )
        )

        ssm.StringParameter(
            self,
            "SpokeStatus",
            parameter_name=f"/steampulse/{environment}/spokes/{spoke_region}/status",
            string_value="active",
        )

        ssm.StringParameter(
            self,
            "SpokeCrawlQueueUrl",
            parameter_name=f"/steampulse/{environment}/spokes/{spoke_region}/crawl-queue-url",
            string_value=spoke_crawl_queue.queue_url,
        )
