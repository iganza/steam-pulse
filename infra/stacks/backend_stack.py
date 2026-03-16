"""BackendStack — Lambdas, SQS, Step Functions, CloudFront.

Receives VPC, security group, and DB secret directly from FoundationStack
as constructor arguments — clean CDK cross-stack wiring with no SSM lookups
or resolve: tokens.
"""

import os

import aws_cdk as cdk
import aws_cdk.aws_certificatemanager as acm
import aws_cdk.aws_cloudfront as cloudfront
import aws_cdk.aws_cloudfront_origins as origins
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_events as events
import aws_cdk.aws_events_targets as events_targets
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_lambda_event_sources as event_sources
import aws_cdk.aws_logs as logs
import aws_cdk.aws_route53 as route53
import aws_cdk.aws_route53_targets as route53_targets
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_secretsmanager as secretsmanager
import aws_cdk.aws_sqs as sqs
import aws_cdk.aws_ssm as ssm
import aws_cdk.aws_stepfunctions as sfn
import aws_cdk.aws_stepfunctions_tasks as tasks
from aws_cdk.aws_lambda_python_alpha import PythonLayerVersion
from constructs import Construct
from library_layer.config import SteamPulseConfig

DOMAIN = "steampulse.io"

_PLACEHOLDER_HANDLER = (
    "def handler(event, context): "
    "return {'statusCode': 200, "
    "'headers': {'content-type': 'text/html'}, "
    "'body': '<h1>Frontend not yet deployed</h1>'}"
)
_OPEN_NEXT_SERVER = "frontend/.open-next/server-functions/default"


class BackendStack(cdk.Stack):
    """Lambdas, SQS, Step Functions, CloudFront. VPC/DB live in FoundationStack."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: SteamPulseConfig,
        vpc: ec2.IVpc,
        intra_sg: ec2.ISecurityGroup,
        db_secret: secretsmanager.ISecret,
        **kwargs: object,
    ) -> None:
        # cross_region_references only needed in production where ACM cert
        # must be in us-east-1 for CloudFront while the stack lives in us-west-2.
        super().__init__(
            scope, construct_id,
            cross_region_references=config.is_production,
            **kwargs,
        )

        env = config.ENVIRONMENT

        lambda_subnets = ec2.SubnetSelection(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS if config.is_production
            else ec2.SubnetType.PUBLIC,
        )

        # ── Shared Lambda Layer ───────────────────────────────────────────────
        library_layer = PythonLayerVersion(
            self, "LibraryLayer",
            entry="src/library-layer",
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="Shared deps (httpx, psycopg2, boto3, anthropic) + steampulse framework",
        )

        # ── SQS Queues ────────────────────────────────────────────────────────
        app_crawl_dlq = sqs.Queue(
            self, "AppCrawlDlq",
            retention_period=cdk.Duration.days(14),
        )
        review_crawl_dlq = sqs.Queue(
            self, "ReviewCrawlDlq",
            retention_period=cdk.Duration.days(14),
        )
        app_crawl_queue = sqs.Queue(
            self, "AppCrawlQueue",
            visibility_timeout=cdk.Duration.minutes(5),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=app_crawl_dlq),
        )
        review_crawl_queue = sqs.Queue(
            self, "ReviewCrawlQueue",
            visibility_timeout=cdk.Duration.minutes(10),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=review_crawl_dlq),
        )

        # Nightly recrawl schedule — disabled until ready to run on schedule.
        nightly_rule = events.Rule(
            self, "NightlyRecrawl",
            schedule=events.Schedule.cron(hour="2", minute="0"),
            description="Nightly re-crawl of top 500 games",
            enabled=False,
        )
        nightly_rule.add_target(events_targets.SqsQueue(app_crawl_queue))

        # ── Analysis Lambda + Step Functions ──────────────────────────────────
        analysis_log_group = logs.LogGroup(
            self, "AnalysisLogs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        analysis_role = iam.Role(
            self, "AnalysisRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole",
                ),
            ],
        )
        analysis_role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
            resources=[db_secret.secret_arn],
        ))
        # resources=* covers both foundation-model and inference-profile ARN formats.
        analysis_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=["*"],
        ))

        analysis_fn = lambda_.Function(
            self, "AnalysisFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_functions.analysis.handler.handler",
            code=lambda_.Code.from_asset("src/lambda-functions"),
            layers=[library_layer],
            role=analysis_role,
            vpc=vpc,
            vpc_subnets=lambda_subnets,
            allow_public_subnet=True,
            security_groups=[intra_sg],
            timeout=cdk.Duration.minutes(10),
            memory_size=1024,
            log_group=analysis_log_group,
            environment={
                "ENVIRONMENT": env,
                "DB_SECRET_ARN": db_secret.secret_arn,
                "HAIKU_MODEL": config.HAIKU_MODEL,
                "SONNET_MODEL": config.SONNET_MODEL,
            },
        )

        analyze_task = tasks.LambdaInvoke(
            self, "AnalyzeGame",
            lambda_function=analysis_fn,
            output_path="$.Payload",
        )
        analyze_task.add_retry(
            max_attempts=2,
            interval=cdk.Duration.seconds(10),
            backoff_rate=2,
        )

        sfn_log_group = logs.LogGroup(
            self, "SfnLogs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        state_machine = sfn.StateMachine(
            self, "AnalysisMachine",
            definition_body=sfn.DefinitionBody.from_chainable(analyze_task),
            state_machine_type=sfn.StateMachineType.EXPRESS,
            timeout=cdk.Duration.minutes(15),
            logs=sfn.LogOptions(
                destination=sfn_log_group,
                level=sfn.LogLevel.ERROR,
            ),
        )

        # ── API Lambda ────────────────────────────────────────────────────────
        api_log_group = logs.LogGroup(
            self, "ApiLogs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        api_role = iam.Role(
            self, "ApiRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole",
                ),
            ],
        )
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
            resources=[db_secret.secret_arn],
        ))
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=["*"],
        ))
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["states:StartExecution", "states:DescribeExecution"],
            resources=[state_machine.state_machine_arn],
        ))

        api_fn = lambda_.Function(
            self, "ApiFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_functions.api.handler.handler",
            code=lambda_.Code.from_asset("src/lambda-functions"),
            layers=[library_layer],
            role=api_role,
            vpc=vpc,
            vpc_subnets=lambda_subnets,
            allow_public_subnet=True,
            security_groups=[intra_sg],
            memory_size=512,
            timeout=cdk.Duration.seconds(30),
            log_group=api_log_group,
            environment={
                "ENVIRONMENT": env,
                "DB_SECRET_ARN": db_secret.secret_arn,
                "SFN_ARN": state_machine.state_machine_arn,
                "STEP_FUNCTIONS_ARN": state_machine.state_machine_arn,
                "PRO_ENABLED": str(config.PRO_ENABLED).lower(),
                "PORT": "8080",
            },
        )

        fn_url = api_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=["*"],
                allowed_methods=[lambda_.HttpMethod.ALL],
                allowed_headers=["*"],
            ),
        )

        # ── Next.js SSR Lambda ────────────────────────────────────────────────
        # Falls back to a placeholder when the frontend hasn't been built yet.
        if os.path.isdir(_OPEN_NEXT_SERVER):
            frontend_code = lambda_.Code.from_asset(_OPEN_NEXT_SERVER)
            frontend_handler = "index.handler"
            frontend_runtime = lambda_.Runtime.NODEJS_22_X
        else:
            frontend_code = lambda_.Code.from_inline(_PLACEHOLDER_HANDLER)
            frontend_handler = "index.handler"
            frontend_runtime = lambda_.Runtime.PYTHON_3_12

        frontend_log_group = logs.LogGroup(
            self, "FrontendFnLogs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        frontend_fn = lambda_.Function(
            self, "FrontendFn",
            runtime=frontend_runtime,
            handler=frontend_handler,
            code=frontend_code,
            memory_size=512,
            timeout=cdk.Duration.seconds(30),
            log_group=frontend_log_group,
            environment={"NODE_ENV": "production"},
        )
        frontend_url = frontend_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
        )

        # ── S3 Static Assets Bucket ───────────────────────────────────────────
        # RETAIN removal policy — never deleted by CDK, even on stack destroy.
        # FrontendStack uploads assets here via BucketDeployment.
        assets_bucket = s3.Bucket(
            self, "AssetsBucket",
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        self.assets_bucket = assets_bucket

        # OAC for CloudFront → S3 (replaces OAI; no bucket policy needed).
        oac = cloudfront.S3OriginAccessControl(self, "AssetsOac")
        s3_origin = origins.S3BucketOrigin.with_origin_access_control(
            assets_bucket,
            origin_access_control=oac,
        )

        # ── CloudFront + Optional Route53/ACM (production only) ───────────────
        hosted_zone = None
        cert = None
        if config.is_production:
            zone_id: str = self.node.try_get_context("hosted-zone-id") or ""
            hosted_zone = route53.HostedZone.from_hosted_zone_attributes(
                self, "HostedZone",
                hosted_zone_id=zone_id,
                zone_name=DOMAIN,
            )
            cert = acm.Certificate(
                self, "Cert",
                domain_name=DOMAIN,
                subject_alternative_names=[f"*.{DOMAIN}"],
                validation=acm.CertificateValidation.from_dns(hosted_zone),
            )

        html_cache_policy = cloudfront.CachePolicy(
            self, "HtmlCachePolicy",
            default_ttl=cdk.Duration.seconds(86400),
            max_ttl=cdk.Duration.seconds(86400 * 2),
            min_ttl=cdk.Duration.seconds(0),
            enable_accept_encoding_gzip=True,
            header_behavior=cloudfront.CacheHeaderBehavior.none(),
            cookie_behavior=cloudfront.CacheCookieBehavior.none(),
            query_string_behavior=cloudfront.CacheQueryStringBehavior.none(),
        )
        static_cache_policy = cloudfront.CachePolicy(
            self, "StaticCachePolicy",
            default_ttl=cdk.Duration.seconds(31_536_000),
            max_ttl=cdk.Duration.seconds(31_536_000),
            min_ttl=cdk.Duration.seconds(31_536_000),
            enable_accept_encoding_gzip=True,
        )

        distribution = cloudfront.Distribution(
            self, "Distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.FunctionUrlOrigin(frontend_url),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=html_cache_policy,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=origins.FunctionUrlOrigin(fn_url),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                ),
                "/_next/static/*": cloudfront.BehaviorOptions(
                    origin=s3_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=static_cache_policy,
                ),
                "/static/*": cloudfront.BehaviorOptions(
                    origin=s3_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=static_cache_policy,
                ),
            },
            domain_names=[DOMAIN, f"www.{DOMAIN}"] if config.is_production else None,
            certificate=cert if config.is_production else None,
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            http_version=cloudfront.HttpVersion.HTTP2_AND_3,
        )

        if config.is_production and hosted_zone:
            route53.ARecord(
                self, "ARecord",
                zone=hosted_zone,
                target=route53.RecordTarget.from_alias(
                    route53_targets.CloudFrontTarget(distribution),
                ),
            )
            route53.ARecord(
                self, "WwwRecord",
                record_name="www",
                zone=hosted_zone,
                target=route53.RecordTarget.from_alias(
                    route53_targets.CloudFrontTarget(distribution),
                ),
            )

        # CloudFront KVS for featured spots (Phase 5)
        self.kvs = cloudfront.KeyValueStore(self, "FeaturedKvs")

        # ── Crawler Lambda ────────────────────────────────────────────────────
        # Steam API key stored in Secrets Manager with a predictable name.
        steam_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "SteamApiKey",
            f"steampulse/{env}/steam-api-key",
        )

        crawler_role = iam.Role(
            self, "CrawlerRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole",
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaSQSQueueExecutionRole",
                ),
            ],
        )
        crawler_role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
            resources=[db_secret.secret_arn, steam_secret.secret_arn],
        ))
        crawler_role.add_to_policy(iam.PolicyStatement(
            actions=["states:StartExecution"],
            resources=[state_machine.state_machine_arn],
        ))
        review_crawl_queue.grant_send_messages(crawler_role)
        app_crawl_queue.grant_send_messages(crawler_role)

        crawler_logs = logs.LogGroup(
            self, "CrawlerLogs",
            removal_policy=cdk.RemovalPolicy.DESTROY,
            retention=logs.RetentionDays.ONE_MONTH,
        )
        crawler_fn = lambda_.Function(
            self, "CrawlerFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_functions.crawler.handler.handler",
            code=lambda_.Code.from_asset("src/lambda-functions"),
            layers=[library_layer],
            role=crawler_role,
            vpc=vpc,
            vpc_subnets=lambda_subnets,
            security_groups=[intra_sg],
            allow_public_subnet=not config.is_production,
            timeout=cdk.Duration.minutes(10),
            memory_size=256,
            tracing=lambda_.Tracing.ACTIVE,
            environment={
                "ENVIRONMENT": env,
                "APP_CRAWL_QUEUE_URL": app_crawl_queue.queue_url,
                "REVIEW_CRAWL_QUEUE_URL": review_crawl_queue.queue_url,
                "DB_SECRET_ARN": db_secret.secret_arn,
                "SFN_ARN": state_machine.state_machine_arn,
                "STEAM_API_KEY_SECRET_ARN": steam_secret.secret_arn,
                "HAIKU_MODEL": config.HAIKU_MODEL,
                "SONNET_MODEL": config.SONNET_MODEL,
                "POWERTOOLS_SERVICE_NAME": "crawler",
                "POWERTOOLS_METRICS_NAMESPACE": "SteamPulse",
            },
            log_group=crawler_logs,
        )

        crawler_fn.add_event_source(
            event_sources.SqsEventSource(
                app_crawl_queue,
                batch_size=10,
                report_batch_item_failures=True,
            )
        )
        crawler_fn.add_event_source(
            event_sources.SqsEventSource(
                review_crawl_queue,
                batch_size=1,
                report_batch_item_failures=True,
            )
        )

        catalog_rule = events.Rule(
            self, "CatalogRefreshRule",
            schedule=events.Schedule.rate(cdk.Duration.days(7)),
        )
        catalog_rule.add_target(events_targets.LambdaFunction(crawler_fn))

        # ── SSM Outputs ───────────────────────────────────────────────────────
        # Written for operational use (scripts, manual lookups, CDN invalidation
        # step in the pipeline). NOT read back as CDK inputs anywhere.
        ssm.StringParameter(
            self, "DistributionIdParam",
            parameter_name=f"/steampulse/{env}/app/distribution-id",
            string_value=distribution.distribution_id,
        )
        ssm.StringParameter(
            self, "FunctionUrlParam",
            parameter_name=f"/steampulse/{env}/app/function-url",
            string_value=fn_url.url,
        )
        ssm.StringParameter(
            self, "AssetsBucketNameParam",
            parameter_name=f"/steampulse/{env}/app/assets-bucket-name",
            string_value=assets_bucket.bucket_name,
        )
