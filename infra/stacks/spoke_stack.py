"""CrawlSpokeStack — multi-purpose crawl worker for a remote AWS region.

One Lambda per region, fed by a per-spoke SQS queue. The primary crawler
sends messages to the spoke queue; the Lambda consumes via event source
mapping with max_concurrency=3 for backpressure.
No DB access. Connects to public internet (Steam) and cross-region S3/SQS.
"""

import aws_cdk as cdk
import aws_cdk.aws_cloudwatch as cloudwatch
import aws_cdk.aws_cloudwatch_actions as cw_actions
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_lambda_event_sources as event_sources
import aws_cdk.aws_logs as logs
import aws_cdk.aws_sns as sns
import aws_cdk.aws_sqs as sqs
import aws_cdk.aws_ssm as ssm
from aws_cdk.aws_lambda_python_alpha import BundlingOptions, PythonFunction, PythonLayerVersion
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
        steam_api_key_param_name: str,
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
            compatible_architectures=[lambda_.Architecture.ARM_64],
            # Pin Docker bundling to arm64 — psycopg2-binary / pydantic-core wheels
            # would otherwise resolve to host arch and crash at import on Lambda.
            bundling=BundlingOptions(platform="linux/arm64"),
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

        # Cross-region SSM SecureString: Steam API key only.
        # parameter_name has a leading slash, so concatenate as parameter{name} (no extra /).
        steam_api_key_param_arn = (
            f"arn:aws:ssm:{primary_region}:{account}:parameter{steam_api_key_param_name}"
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[steam_api_key_param_arn],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt"],
                resources=[f"arn:aws:kms:{primary_region}:{account}:alias/aws/ssm"],
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
            architecture=lambda_.Architecture.ARM_64,
            layers=[library_layer],
            role=role,
            timeout=cdk.Duration.minutes(10),
            memory_size=256,
            # X-Ray disabled on spokes — high-volume simple Steam fetchers where
            # CloudWatch logs + Lambda duration/error metrics give enough signal.
            # Keep ACTIVE on crawler/ingest where cross-service traces matter.
            tracing=lambda_.Tracing.DISABLED,
            recursive_loop=lambda_.RecursiveLoop.ALLOW,
            log_group=logs.LogGroup(
                self,
                "SpokeLogs",
                log_group_name=f"/steampulse/{environment}/spoke/{spoke_region}",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment=config.to_lambda_env(
                # Spoke-specific overrides — cross-region stack can't resolve SSM,
                # so _PARAM_NAME fields hold ACTUAL values (not SSM paths).
                PRIMARY_REGION=primary_region,
                SPOKE_RESULTS_QUEUE_URL=spoke_results_queue_url,
                ASSETS_BUCKET_PARAM_NAME=assets_bucket_name,
                STEAM_API_KEY_PARAM_NAME=steam_api_key_param_name,
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

        # ── Tags ────────────────────────────────────────────────────────────
        for resource in (spoke_fn, spoke_crawl_queue, spoke_dlq):
            cdk.Tags.of(resource).add("steampulse:service", "spoke")
            cdk.Tags.of(resource).add("steampulse:tier", "critical")

        # ── Local Alarms (same region as metrics) ──────────────────────────
        alarm_topic = sns.Topic(
            self,
            "SpokeAlarmTopic",
            display_name=f"SteamPulse {environment.capitalize()} Spoke {spoke_region} Alarms",
        )
        cdk.Tags.of(alarm_topic).add("steampulse:service", "spoke")
        cdk.Tags.of(alarm_topic).add("steampulse:tier", "critical")

        cdk.CfnOutput(
            self,
            "SpokeAlarmTopicArn",
            value=alarm_topic.topic_arn,
            description=f"Spoke alarm topic for {spoke_region}",
        )

        # Two raw alarms only — replaces cdk-monitoring-constructs MonitoringFacade
        # to drop the auto-tracked metrics it subscribes for the dashboard layer
        # (the real CloudWatch cost driver across 11 spoke regions).
        sns_action = cw_actions.SnsAction(alarm_topic)
        alarm_prefix = f"SteamPulse-{environment.capitalize()}-Spoke-{spoke_region}"

        cloudwatch.Alarm(
            self,
            "SpokeErrorsAlarm",
            alarm_name=f"{alarm_prefix}-SpokeErrors",
            metric=spoke_fn.metric_errors(
                period=cdk.Duration.minutes(5),
                statistic="Sum",
            ),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        ).add_alarm_action(sns_action)

        cloudwatch.Alarm(
            self,
            "SpokeDlqAlarm",
            alarm_name=f"{alarm_prefix}-SpokeDlq",
            metric=spoke_dlq.metric_approximate_number_of_messages_visible(
                period=cdk.Duration.minutes(5),
                statistic="Maximum",
            ),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        ).add_alarm_action(sns_action)
