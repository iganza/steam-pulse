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
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env = config.ENVIRONMENT
        private_subnets = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)

        assets_bucket = s3.Bucket.from_bucket_name(
            self, "AssetsBucket", f"steampulse-{env}-assets",
        )

        # ── Shared Lambda Layer ───────────────────────────────────────────────
        library_layer = PythonLayerVersion(
            self,
            "LibraryLayer",
            entry="src/library-layer",
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            layer_version_name=f"{config.ENVIRONMENT}-steampulse-lambda-library-layer",
            description="Shared deps (httpx, psycopg2, boto3, anthropic) + steampulse framework",
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
        analysis_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
                resources=[db_secret.secret_arn],
            )
        )
        analysis_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=["*"],
            )
        )
        analysis_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[f"arn:aws:ssm:{self.region}:{self.account}:parameter/steampulse/{env}/*"],
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
            log_group=logs.LogGroup(
                self,
                "AnalysisLogs",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment=config.to_lambda_env(),
        )

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
        api_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
                resources=[db_secret.secret_arn],
            )
        )
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
                resources=[f"arn:aws:ssm:{self.region}:{self.account}:parameter/steampulse/{env}/*"],
            )
        )

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
            log_group=logs.LogGroup(
                self,
                "ApiLogs",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment=config.to_lambda_env(PORT="8080"),
        )

        self.api_fn_url = api_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=["*"],
                allowed_methods=[lambda_.HttpMethod.ALL],
                allowed_headers=["*"],
            ),
        )

        # ── Frontend SSR Lambda ───────────────────────────────────────────────
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
            environment={"NODE_ENV": "production"},
        )

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
        crawler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
                resources=[db_secret.secret_arn],
            )
        )
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
                resources=[f"arn:aws:ssm:{self.region}:{self.account}:parameter/steampulse/{env}/*"],
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
            memory_size=256,
            tracing=lambda_.Tracing.ACTIVE,
            log_group=logs.LogGroup(
                self,
                "CrawlerLogs",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment=config.to_lambda_env(
                POWERTOOLS_SERVICE_NAME="crawler",
                POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
            ),
        )

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

        # Cross-region invoke on spoke Lambdas (deterministic names)
        spoke_regions = config.spoke_region_list
        if spoke_regions:
            spoke_fn_arns = [
                f"arn:aws:lambda:{r}:{self.account}:function:"
                f"steampulse-{env}-spoke-crawler-{r}"
                for r in spoke_regions
            ]
            crawler_role.add_to_policy(iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=spoke_fn_arns,
            ))

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
            memory_size=256,
            tracing=lambda_.Tracing.ACTIVE,
            log_group=logs.LogGroup(
                self,
                "SpokeIngestLogs",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment=config.to_lambda_env(
                POWERTOOLS_SERVICE_NAME="spoke-ingest",
                POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
            ),
        )
        ingest_fn.add_event_source(
            event_sources.SqsEventSource(
                spoke_results_queue,
                batch_size=5,
                report_batch_item_failures=True,
            )
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
                self, "AdminRole",
                assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
                managed_policies=[
                    iam.ManagedPolicy.from_aws_managed_policy_name(
                        "service-role/AWSLambdaVPCAccessExecutionRole",
                    ),
                ],
                inline_policies={
                    "db": iam.PolicyDocument(statements=[
                        iam.PolicyStatement(
                            actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
                            resources=[db_secret.secret_arn],
                        ),
                    ]),
                },
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

        # Weekly catalog refresh — disabled until we're ready to run on a schedule.
        catalog_rule = events.Rule(
            self,
            "CatalogRefreshRule",
            schedule=events.Schedule.rate(cdk.Duration.days(7)),
            enabled=False,
        )
        catalog_rule.add_target(events_targets.LambdaFunction(crawler_fn))

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
