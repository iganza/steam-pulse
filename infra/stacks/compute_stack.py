"""ComputeStack — Lambda layer, Lambda functions, Step Functions.

The fastest-changing stack: deploys on every code commit. Receives stable
infra (VPC, DB secret, SQS queues) from upstream stacks as CDK objects.

EventBridge rules that target Lambda functions live here (not MessagingStack)
because they hold a direct CDK reference to the function.
"""

import os

import aws_cdk as cdk
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_events as events
import aws_cdk.aws_events_targets as events_targets
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_lambda_event_sources as event_sources
import aws_cdk.aws_logs as logs
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_secretsmanager as secretsmanager
import aws_cdk.aws_sns as sns
import aws_cdk.aws_sqs as sqs
import aws_cdk.aws_dynamodb as dynamodb
import aws_cdk.aws_ssm as ssm
import aws_cdk.aws_stepfunctions as sfn
import aws_cdk.aws_stepfunctions_tasks as tasks
from aws_cdk.aws_lambda_python_alpha import PythonFunction, PythonLayerVersion
from constructs import Construct
from library_layer.config import SteamPulseConfig

_PLACEHOLDER_HANDLER = (
    "def handler(event, context): "
    "return {'statusCode': 200, "
    "'headers': {'content-type': 'text/html'}, "
    "'body': '<h1>Frontend not yet deployed</h1>'}"
)
_OPEN_NEXT_SERVER = "frontend/.open-next/server-functions/default"


class ComputeStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: SteamPulseConfig,
        vpc: ec2.IVpc,
        intra_sg: ec2.ISecurityGroup,
        db_secret: secretsmanager.ISecret,
        app_crawl_queue: sqs.IQueue,
        review_crawl_queue: sqs.IQueue,
        game_events_topic: sns.ITopic,
        content_events_topic: sns.ITopic,
        system_events_topic: sns.ITopic,
        spoke_results_queue: sqs.IQueue,
        email_queue: sqs.IQueue,
        cache_invalidation_queue: sqs.IQueue,
        genre_synthesis_queue: sqs.IQueue,
        spoke_crawl_queue_urls: str,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env = config.ENVIRONMENT
        private_subnets = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)

        assets_bucket = s3.Bucket.from_bucket_name(
            self,
            "AssetsBucket",
            f"steampulse-assets-{env}",
        )
        frontend_bucket = s3.Bucket.from_bucket_name(
            self,
            "FrontendBucket",
            f"steampulse-frontend-{env}",
        )

        # ── Shared Lambda Layer ───────────────────────────────────────────────
        self.library_layer = PythonLayerVersion(
            self,
            "LibraryLayer",
            entry="src/library-layer",
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            layer_version_name=f"{config.ENVIRONMENT}-steampulse-lambda-library-layer",
            description="Shared deps (httpx, psycopg2, boto3, anthropic) + steampulse framework",
        )
        library_layer = self.library_layer
        ssm.StringParameter(
            self,
            "LibraryLayerArnParam",
            parameter_name=config.library_layer_ssm_path,
            string_value=self.library_layer.layer_version_arn,
        )

        # ── Analysis Lambda ───────────────────────────────────────────────────
        analysis_role = iam.Role(
            self,
            "AnalysisRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole",
                ),
            ],
        )
        db_secret.grant_read(analysis_role)
        anthropic_secret = secretsmanager.Secret.from_secret_name_v2(
            self,
            "AnalysisAnthropicApiKey",
            f"/steampulse/{env}/anthropic-api-key",
        )
        anthropic_secret.grant_read(analysis_role)
        analysis_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=["*"],
            )
        )
        analysis_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/steampulse/{env}/*"
                ],
            )
        )
        content_events_topic.grant_publish(analysis_role)

        analysis_fn = PythonFunction(
            self,
            "AnalysisFn",
            entry="src/lambda-functions",
            index="lambda_functions/analysis/handler.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[library_layer],
            role=analysis_role,
            vpc=vpc,
            vpc_subnets=private_subnets,
            security_groups=[intra_sg],
            timeout=cdk.Duration.minutes(10),
            memory_size=1024,
            tracing=lambda_.Tracing.ACTIVE,
            log_group=logs.LogGroup(
                self,
                "AnalysisLogs",
                log_group_name=f"/steampulse/{env}/analysis",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment=config.to_lambda_env(),
        )
        cdk.Tags.of(analysis_fn).add("steampulse:service", "analysis")
        cdk.Tags.of(analysis_fn).add("steampulse:tier", "standard")

        # ── Step Functions ────────────────────────────────────────────────────
        analyze_task = tasks.LambdaInvoke(
            self,
            "AnalyzeGame",
            lambda_function=analysis_fn,
            output_path="$.Payload",
        )
        analyze_task.add_retry(
            max_attempts=2,
            interval=cdk.Duration.seconds(10),
            backoff_rate=2,
        )

        state_machine = sfn.StateMachine(
            self,
            "AnalysisMachine",
            definition_body=sfn.DefinitionBody.from_chainable(analyze_task),
            state_machine_type=sfn.StateMachineType.EXPRESS,
            timeout=cdk.Duration.minutes(15),
            logs=sfn.LogOptions(
                destination=logs.LogGroup(
                    self,
                    "SfnLogs",
                    retention=logs.RetentionDays.ONE_WEEK,
                    removal_policy=cdk.RemovalPolicy.DESTROY,
                ),
                level=sfn.LogLevel.ERROR,
            ),
        )

        # ── API Lambda ────────────────────────────────────────────────────────
        api_role = iam.Role(
            self,
            "ApiRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole",
                ),
            ],
        )
        db_secret.grant_read(api_role)
        api_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=["*"],
            )
        )
        api_role.add_to_policy(
            iam.PolicyStatement(
                actions=["states:StartExecution", "states:DescribeExecution"],
                resources=[state_machine.state_machine_arn],
            )
        )
        api_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/steampulse/{env}/*"
                ],
            )
        )
        email_queue.grant_send_messages(api_role)

        api_fn = PythonFunction(
            self,
            "ApiFn",
            entry="src/lambda-functions",
            index="lambda_functions/api/handler.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[library_layer],
            role=api_role,
            vpc=vpc,
            vpc_subnets=private_subnets,
            security_groups=[intra_sg],
            memory_size=512,
            timeout=cdk.Duration.seconds(30),
            tracing=lambda_.Tracing.ACTIVE,
            log_group=logs.LogGroup(
                self,
                "ApiLogs",
                log_group_name=f"/steampulse/{env}/api",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment=config.to_lambda_env(PORT="8080"),
        )

        cdk.Tags.of(api_fn).add("steampulse:service", "api")
        cdk.Tags.of(api_fn).add("steampulse:tier", "critical")

        self.api_fn_url = api_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=["*"],
                allowed_methods=[lambda_.HttpMethod.ALL],
                allowed_headers=["*"],
            ),
        )

        # ── Frontend SSR Lambda ───────────────────────────────────────────────
        # OpenNext ISR revalidation table — tag-based on-demand revalidation.
        # Schema: hash key `tag` (S), range key `path` (S).
        # GSI `revalidate`: hash key `path` (S) — queried by OpenNext cache layer.
        opennext_cache_table = dynamodb.Table(
            self,
            "OpenNextCacheTable",
            partition_key=dynamodb.Attribute(name="tag", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="path", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        opennext_cache_table.add_global_secondary_index(
            index_name="revalidate",
            partition_key=dynamodb.Attribute(name="path", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="revalidatedAt", type=dynamodb.AttributeType.NUMBER),
        )

        if os.path.isdir(_OPEN_NEXT_SERVER):
            frontend_code = lambda_.Code.from_asset(_OPEN_NEXT_SERVER)
            frontend_handler = "index.handler"
            frontend_runtime = lambda_.Runtime.NODEJS_22_X
        else:
            frontend_code = lambda_.Code.from_inline(_PLACEHOLDER_HANDLER)
            frontend_handler = "index.handler"
            frontend_runtime = lambda_.Runtime.PYTHON_3_12

        frontend_fn = lambda_.Function(
            self,
            "FrontendFn",
            runtime=frontend_runtime,
            handler=frontend_handler,
            code=frontend_code,
            memory_size=512,
            timeout=cdk.Duration.seconds(30),
            log_group=logs.LogGroup(
                self,
                "FrontendFnLogs",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment={
                "NODE_ENV": "production",
                # Absolute URL for SSR — Next.js server components need this to call
                # the API from inside Lambda (relative URLs don't work in Lambda).
                "API_URL": self.api_fn_url.url,
                # OpenNext ISR cache — must point at a real bucket or every
                # cache read/write will fail with NoSuchBucket.
                "CACHE_BUCKET_NAME": frontend_bucket.bucket_name,
                "CACHE_BUCKET_REGION": self.region,
                # Per-build key prefix — each deploy writes to a fresh
                # cache/{BUILD_ID}/ namespace, so the new Lambda can never
                # read pre-deploy HTML. Old prefixes age out via the 7-day
                # S3 lifecycle rule on frontend_bucket (data_stack.py).
                # BUILD_ID comes from the CDK context var `build-id`
                # (set by scripts/deploy.sh from `git rev-parse --short HEAD`),
                # with a `local` fallback for dev synth.
                "CACHE_BUCKET_KEY_PREFIX": f"cache/{self.node.try_get_context('build-id') or 'local'}/",
                "CACHE_DYNAMO_TABLE": opennext_cache_table.table_name,
            },
        )
        cdk.Tags.of(frontend_fn).add("steampulse:service", "frontend")
        cdk.Tags.of(frontend_fn).add("steampulse:tier", "critical")

        frontend_bucket.grant_read_write(frontend_fn)
        opennext_cache_table.grant_read_write_data(frontend_fn)

        self.frontend_fn_url = frontend_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
        )

        # ── Crawler Lambda ────────────────────────────────────────────────────
        steam_secret = secretsmanager.Secret.from_secret_name_v2(
            self,
            "SteamApiKey",
            f"steampulse/{env}/steam-api-key",
        )

        crawler_role = iam.Role(
            self,
            "CrawlerRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole",
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaSQSQueueExecutionRole",
                ),  # IngestFn (shared role) consumes spoke_results_queue
            ],
        )
        db_secret.grant_read(crawler_role)
        steam_secret.grant_read(crawler_role)
        crawler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["states:StartExecution"],
                resources=[state_machine.state_machine_arn],
            )
        )
        crawler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/steampulse/{env}/*"
                ],
            )
        )
        app_crawl_queue.grant_send_messages(crawler_role)
        review_crawl_queue.grant_send_messages(crawler_role)
        game_events_topic.grant_publish(crawler_role)
        content_events_topic.grant_publish(crawler_role)
        system_events_topic.grant_publish(crawler_role)
        assets_bucket.grant_read_write(crawler_role)

        crawler_fn = PythonFunction(
            self,
            "CrawlerFn",
            entry="src/lambda-functions",
            index="lambda_functions/crawler/handler.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[library_layer],
            role=crawler_role,
            vpc=vpc,
            vpc_subnets=private_subnets,
            security_groups=[intra_sg],
            timeout=cdk.Duration.minutes(10),
            memory_size=1024,
            tracing=lambda_.Tracing.ACTIVE,
            log_group=logs.LogGroup(
                self,
                "CrawlerLogs",
                log_group_name=f"/steampulse/{env}/crawler",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment=config.to_lambda_env(
                POWERTOOLS_SERVICE_NAME="crawler",
                POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
                SPOKE_CRAWL_QUEUE_URLS=spoke_crawl_queue_urls,
            ),
        )

        cdk.Tags.of(crawler_fn).add("steampulse:service", "crawler")
        cdk.Tags.of(crawler_fn).add("steampulse:tier", "critical")

        # SQS event sources — crawler dispatches work to spoke Lambdas
        for queue, _source_id in [
            (app_crawl_queue, "AppCrawlSource"),
            (review_crawl_queue, "ReviewCrawlSource"),
        ]:
            crawler_fn.add_event_source(
                event_sources.SqsEventSource(
                    queue,
                    batch_size=10,
                    max_concurrency=3,
                    report_batch_item_failures=True,
                )
            )

        # Override logical IDs to match the pipeline-era CloudFormation stack so
        # CDK doesn't try to delete+recreate existing EventSourceMappings.
        # Staging only — production was never deployed via CDK Pipelines.
        if not config.is_production:
            crawler_fn.node.find_child(
                "SqsEventSource:SteamPulseStagingMessagingMetadataEnrichmentQueue3591136B"
            ).node.default_child.override_logical_id(
                "CrawlerFnSqsEventSourceSteamPulsePipelineSteamPulseStagingMessagingMetadataEnrichmentQueueA474040326CE7FBE"
            )
            crawler_fn.node.find_child(
                "SqsEventSource:SteamPulseStagingMessagingReviewCrawlQueue7583C282"
            ).node.default_child.override_logical_id(
                "CrawlerFnSqsEventSourceSteamPulsePipelineSteamPulseStagingMessagingReviewCrawlQueue69735A7ED670F960"
            )

        # Cross-region SQS send to per-spoke crawl queues (deterministic names)
        spoke_regions = config.spoke_region_list
        if spoke_regions:
            spoke_queue_arns = [
                f"arn:aws:sqs:{r}:{self.account}:steampulse-spoke-crawl-{r}-{env}"
                for r in spoke_regions
            ]
            crawler_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["sqs:SendMessage"],
                    resources=spoke_queue_arns,
                )
            )

        # ── Ingest Lambda (spoke results → DB) ────────────────────────────
        ingest_fn = PythonFunction(
            self,
            "SpokeIngestFn",
            entry="src/lambda-functions",
            index="lambda_functions/crawler/ingest_handler.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[library_layer],
            role=crawler_role,
            vpc=vpc,
            vpc_subnets=private_subnets,
            security_groups=[intra_sg],
            timeout=cdk.Duration.minutes(15),
            memory_size=1024,
            tracing=lambda_.Tracing.ACTIVE,
            recursive_loop=lambda_.RecursiveLoop.ALLOW,
            log_group=logs.LogGroup(
                self,
                "SpokeIngestLogs",
                log_group_name=f"/steampulse/{env}/ingest",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment=config.to_lambda_env(
                POWERTOOLS_SERVICE_NAME="spoke-ingest",
                POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
                SPOKE_CRAWL_QUEUE_URLS=spoke_crawl_queue_urls,
            ),
        )
        cdk.Tags.of(ingest_fn).add("steampulse:service", "ingest")
        cdk.Tags.of(ingest_fn).add("steampulse:tier", "critical")

        ingest_fn.add_event_source(
            event_sources.SqsEventSource(
                spoke_results_queue,
                batch_size=40,
                max_batching_window=cdk.Duration.seconds(5),
                max_concurrency=6,
                report_batch_item_failures=True,
            )
        )
        if not config.is_production:
            ingest_fn.node.find_child(
                "SqsEventSource:SteamPulseStagingMessagingSpokeResultsQueue052BE137"
            ).node.default_child.override_logical_id(
                "SpokeIngestFnSqsEventSourceSteamPulsePipelineSteamPulseStagingMessagingSpokeResultsQueueEFF7E445BA6FB25C"
            )

        # ── Admin Lambda (DB operations — invoked by sp.py) ──────────────────
        admin_fn = PythonFunction(
            self,
            "AdminFn",
            entry="src/lambda-functions",
            index="lambda_functions/admin/handler.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[library_layer],
            role=iam.Role(
                self,
                "AdminRole",
                assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
                managed_policies=[
                    iam.ManagedPolicy.from_aws_managed_policy_name(
                        "service-role/AWSLambdaVPCAccessExecutionRole",
                    ),
                ],
            ),
            vpc=vpc,
            vpc_subnets=private_subnets,
            security_groups=[intra_sg],
            timeout=cdk.Duration.seconds(30),
            memory_size=256,
            log_group=logs.LogGroup(
                self,
                "AdminLogs",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment=config.to_lambda_env(),
        )
        cdk.Tags.of(admin_fn).add("steampulse:service", "admin")
        cdk.Tags.of(admin_fn).add("steampulse:tier", "internal")
        db_secret.grant_read(admin_fn)

        # ── Migration Lambda (applies pending yoyo migrations post-deployment) ───
        migration_fn = PythonFunction(
            self,
            "MigrationFn",
            entry="src/lambda-functions",
            index="lambda_functions/admin/migrate_handler.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[library_layer],
            role=iam.Role(
                self,
                "MigrationRole",
                assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
                managed_policies=[
                    iam.ManagedPolicy.from_aws_managed_policy_name(
                        "service-role/AWSLambdaVPCAccessExecutionRole",
                    ),
                ],
            ),
            vpc=vpc,
            vpc_subnets=private_subnets,
            security_groups=[intra_sg],
            timeout=cdk.Duration.minutes(10),  # 4 retries × 15s wait + migration time
            memory_size=256,
            reserved_concurrent_executions=1,
            log_group=logs.LogGroup(
                self,
                "MigrationLogs",
                log_group_name=f"/steampulse/{env}/migration",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment=config.to_lambda_env(
                POWERTOOLS_SERVICE_NAME="migration",
                POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
            ),
        )
        cdk.Tags.of(migration_fn).add("steampulse:service", "migration")
        cdk.Tags.of(migration_fn).add("steampulse:tier", "internal")
        db_secret.grant_read(migration_fn)

        # ── Matview Refresh Lambda (keeps materialized views up-to-date) ────────
        matview_refresh_fn = PythonFunction(
            self,
            "MatviewRefreshFn",
            entry="src/lambda-functions",
            index="lambda_functions/admin/matview_refresh_handler.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[library_layer],
            role=iam.Role(
                self,
                "MatviewRefreshRole",
                assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
                managed_policies=[
                    iam.ManagedPolicy.from_aws_managed_policy_name(
                        "service-role/AWSLambdaVPCAccessExecutionRole",
                    ),
                ],
            ),
            vpc=vpc,
            vpc_subnets=private_subnets,
            security_groups=[intra_sg],
            timeout=cdk.Duration.minutes(5),
            memory_size=256,
            reserved_concurrent_executions=1,
            log_group=logs.LogGroup(
                self,
                "MatviewRefreshLogs",
                log_group_name=f"/steampulse/{env}/matview-refresh",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment=config.to_lambda_env(
                POWERTOOLS_SERVICE_NAME="matview-refresh",
                POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
            ),
        )
        cdk.Tags.of(matview_refresh_fn).add("steampulse:service", "matview-refresh")
        cdk.Tags.of(matview_refresh_fn).add("steampulse:tier", "internal")
        db_secret.grant_read(matview_refresh_fn)

        # SQS event source — consumes from cache_invalidation_queue
        matview_refresh_fn.add_event_source(
            event_sources.SqsEventSource(
                cache_invalidation_queue,
                batch_size=1,
            )
        )

        # EventBridge fallback — refresh every 6 hours.
        # Staging: schedule disabled by convention (no cron in non-prod envs).
        # Staging operators refresh matviews ad-hoc via sp.py.
        events.Rule(
            self,
            "MatviewRefreshSchedule",
            schedule=events.Schedule.rate(cdk.Duration.hours(6)),
            enabled=config.is_production,
        ).add_target(events_targets.LambdaFunction(matview_refresh_fn))

        # ── DB Loader Lambda (staging only — never deploy to production) ────────
        # This Lambda drops and recreates the public schema. It must never exist
        # in production — an accidental invoke would wipe prod data irreversibly.
        if not config.is_production:
            db_loader_role = iam.Role(
                self,
                "DbLoaderRole",
                assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
                managed_policies=[
                    iam.ManagedPolicy.from_aws_managed_policy_name(
                        "service-role/AWSLambdaVPCAccessExecutionRole",
                    ),
                ],
            )
            db_secret.grant_read(db_loader_role)
            db_loader_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["s3:GetObject"],
                    resources=[
                        assets_bucket.arn_for_objects("db-snapshots/*"),
                        assets_bucket.arn_for_objects("db-dumps/*"),
                    ],
                ),
            )

            PythonFunction(
                self,
                "DbLoaderFn",
                entry="src/lambda-functions",
                index="lambda_functions/db_loader/handler.py",
                handler="handler",
                runtime=lambda_.Runtime.PYTHON_3_12,
                layers=[library_layer],
                role=db_loader_role,
                vpc=vpc,
                vpc_subnets=private_subnets,
                security_groups=[intra_sg],
                timeout=cdk.Duration.minutes(15),
                memory_size=512,
                reserved_concurrent_executions=1,
                log_group=logs.LogGroup(
                    self,
                    "DbLoaderLogs",
                    retention=logs.RetentionDays.ONE_WEEK,
                    removal_policy=cdk.RemovalPolicy.DESTROY,
                ),
                environment=config.to_lambda_env(),
            )

        # ── Email Lambda (SQS-triggered transactional email sender) ─────────────
        resend_secret = secretsmanager.Secret.from_secret_name_v2(
            self,
            "ResendApiKey",
            config.RESEND_API_KEY_SECRET_NAME,
        )

        email_role = iam.Role(
            self,
            "EmailRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaSQSQueueExecutionRole",
                ),
            ],
        )
        resend_secret.grant_read(email_role)
        email_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/steampulse/{env}/*"
                ],
            )
        )

        email_fn = PythonFunction(
            self,
            "EmailFn",
            entry="src/lambda-functions",
            index="lambda_functions/email/handler.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[library_layer],
            role=email_role,
            timeout=cdk.Duration.seconds(30),
            memory_size=256,
            tracing=lambda_.Tracing.ACTIVE,
            log_group=logs.LogGroup(
                self,
                "EmailLogs",
                log_group_name=f"/steampulse/{env}/email",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment=config.to_lambda_env(
                POWERTOOLS_SERVICE_NAME="email",
                POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
            ),
        )
        cdk.Tags.of(email_fn).add("steampulse:service", "email")
        cdk.Tags.of(email_fn).add("steampulse:tier", "standard")

        email_fn.add_event_source(
            event_sources.SqsEventSource(
                email_queue,
                batch_size=1,
                report_batch_item_failures=True,
            )
        )

        # ── Phase-4 Genre Synthesis Lambda ────────────────────────────────────
        # One invocation per SQS message synthesizes one genre slug. Also
        # handles the weekly EventBridge scan (stale-slug enqueue).
        genre_synthesis_role = iam.Role(
            self,
            "GenreSynthesisRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole",
                ),
            ],
        )
        db_secret.grant_read(genre_synthesis_role)
        anthropic_secret.grant_read(genre_synthesis_role)
        genre_synthesis_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=["*"],
            )
        )
        genre_synthesis_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/steampulse/{env}/*"
                ],
            )
        )
        genre_synthesis_queue.grant_consume_messages(genre_synthesis_role)
        genre_synthesis_queue.grant_send_messages(genre_synthesis_role)

        genre_synthesis_fn = PythonFunction(
            self,
            "GenreSynthesisFn",
            entry="src/lambda-functions",
            index="lambda_functions/genre_synthesis/handler.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[library_layer],
            role=genre_synthesis_role,
            vpc=vpc,
            vpc_subnets=private_subnets,
            security_groups=[intra_sg],
            timeout=cdk.Duration.minutes(5),
            memory_size=1024,
            tracing=lambda_.Tracing.ACTIVE,
            log_group=logs.LogGroup(
                self,
                "GenreSynthesisLogs",
                log_group_name=f"/steampulse/{env}/genre-synthesis",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment=config.to_lambda_env(
                POWERTOOLS_SERVICE_NAME="genre-synthesis",
                POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
            ),
        )
        cdk.Tags.of(genre_synthesis_fn).add("steampulse:service", "genre-synthesis")
        cdk.Tags.of(genre_synthesis_fn).add("steampulse:tier", "standard")

        # One SQS message = one slug synthesis = one Bedrock call. Serialise
        # with batch_size=1 + max_concurrency=2 so weekly bursts don't stampede
        # Bedrock rate limits.
        genre_synthesis_fn.add_event_source(
            event_sources.SqsEventSource(
                genre_synthesis_queue,
                batch_size=1,
                max_concurrency=2,
                report_batch_item_failures=True,
            )
        )

        # Weekly stale-scan — enqueues re-synthesis jobs for any slug whose
        # synthesis row is older than GENRE_SYNTHESIS_MAX_AGE_DAYS.
        # Deployed `enabled=False` per ARCHITECTURE.org rule — enable manually
        # once the first slug has been seeded and the prompt has stabilised.
        genre_synthesis_rule = events.Rule(
            self,
            "GenreSynthesisWeeklyRule",
            schedule=events.Schedule.cron(
                week_day="SUN", hour="2", minute="0"
            ),
            description="Weekly Phase-4 genre-synthesis stale-slug scan",
            enabled=False,
        )
        genre_synthesis_rule.add_target(
            events_targets.LambdaFunction(
                genre_synthesis_fn,
                event=events.RuleTargetInput.from_object({"action": "scan_stale"}),
            )
        )

        # Hourly catalog refresh — fetches Steam GetAppList, upserts new apps,
        # and enqueues any pending metadata crawls.
        # Prod-only: no cron in staging (catalog discovery is ad-hoc via sp.py).
        catalog_rule = events.Rule(
            self,
            "CatalogRefreshRule",
            schedule=events.Schedule.rate(cdk.Duration.hours(1)),
            enabled=config.is_production,
        )
        catalog_rule.add_target(events_targets.LambdaFunction(crawler_fn))

        # Tiered refresh scheduling — hourly dispatcher picks up the next
        # batch of tier-due metadata / review crawls. Work is smeared
        # deterministically across each tier's refresh window via
        # hashtext(appid) so load is smooth instead of spiking at boundaries.
        # Prod-only: no cron in staging (ad-hoc refresh via sp.py).
        refresh_meta_rule = events.Rule(
            self,
            "RefreshMetaRule",
            schedule=events.Schedule.rate(cdk.Duration.hours(1)),
            description="Hourly tiered metadata refresh dispatcher",
            enabled=config.is_production,
        )
        refresh_meta_rule.add_target(
            events_targets.LambdaFunction(
                crawler_fn,
                event=events.RuleTargetInput.from_object(
                    {
                        "action": "refresh_meta",
                        "limit": config.REFRESH_META_BATCH_LIMIT,
                    }
                ),
            )
        )

        refresh_reviews_rule = events.Rule(
            self,
            "RefreshReviewsRule",
            schedule=events.Schedule.rate(cdk.Duration.hours(1)),
            description="Hourly tiered review refresh dispatcher",
            enabled=config.is_production,
        )
        refresh_reviews_rule.add_target(
            events_targets.LambdaFunction(
                crawler_fn,
                event=events.RuleTargetInput.from_object(
                    {
                        "action": "refresh_reviews",
                        "limit": config.REFRESH_REVIEWS_BATCH_LIMIT,
                    }
                ),
            )
        )

        # Override logical ID to match the pipeline-era stack.
        # Staging only — production was never deployed via CDK Pipelines.
        if not config.is_production:
            catalog_rule.node.find_child(
                "AllowEventRuleSteamPulseStagingComputeCrawlerFnD591DFAD"
            ).override_logical_id(
                "CatalogRefreshRuleAllowEventRuleSteamPulsePipelineSteamPulseStagingComputeCrawlerFnCBFED1AD54DE85D7"
            )

        # ── SSM outputs — read by MonitoringStack via {{resolve:ssm:...}} ─────
        # Using SSM avoids Fn::ImportValue so MonitoringStack has no hard
        # CloudFormation dependency on this stack.
        ssm.StringParameter(
            self,
            "ApiFnArnParam",
            parameter_name=f"/steampulse/{env}/compute/api-fn-arn",
            string_value=api_fn.function_arn,
        )
        ssm.StringParameter(
            self,
            "CrawlerFnArnParam",
            parameter_name=f"/steampulse/{env}/compute/crawler-fn-arn",
            string_value=crawler_fn.function_arn,
        )
        ssm.StringParameter(
            self,
            "AnalysisFnArnParam",
            parameter_name=f"/steampulse/{env}/compute/analysis-fn-arn",
            string_value=analysis_fn.function_arn,
        )
        ssm.StringParameter(
            self,
            "SpokeIngestFnArnParam",
            parameter_name=f"/steampulse/{env}/compute/spoke-ingest-fn-arn",
            string_value=ingest_fn.function_arn,
        )
        ssm.StringParameter(
            self,
            "SfnArnParam",
            parameter_name=f"/steampulse/{env}/compute/sfn-arn",
            string_value=state_machine.state_machine_arn,
        )
        ssm.StringParameter(
            self,
            "ApiFnUrlParam",
            parameter_name=f"/steampulse/{env}/compute/api-fn-url",
            string_value=self.api_fn_url.url,
        )
        ssm.StringParameter(
            self,
            "AdminFnNameParam",
            parameter_name=f"/steampulse/{env}/compute/admin-fn-name",
            string_value=admin_fn.function_name,
        )
        ssm.StringParameter(
            self,
            "MigrationFnArnParam",
            parameter_name=f"/steampulse/{env}/compute/migration-fn-arn",
            string_value=migration_fn.function_arn,
        )
        ssm.StringParameter(
            self,
            "FrontendFnArnParam",
            parameter_name=f"/steampulse/{env}/compute/frontend-fn-arn",
            string_value=frontend_fn.function_arn,
        )
        ssm.StringParameter(
            self,
            "EmailFnArnParam",
            parameter_name=f"/steampulse/{env}/compute/email-fn-arn",
            string_value=email_fn.function_arn,
        )
        ssm.StringParameter(
            self,
            "AdminFnArnParam",
            parameter_name=f"/steampulse/{env}/compute/admin-fn-arn",
            string_value=admin_fn.function_arn,
        )
