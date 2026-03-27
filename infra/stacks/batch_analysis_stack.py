"""BatchAnalysisStack — Bedrock Batch Inference pipeline for bulk game analysis.

Resources:
  - S3 bucket for batch I/O (7-day lifecycle, auto-deleted)
  - IAM role assumed by Bedrock to read/write S3
  - 5 Lambda functions (PreparePass1, SubmitBatchJob, CheckBatchStatus, PreparePass2, ProcessResults)
  - STANDARD Step Functions state machine with Wait/Choice polling loops
  - EventBridge rule (disabled by default — for future scheduled re-analysis)
"""


import aws_cdk as cdk
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_events as events
import aws_cdk.aws_events_targets as events_targets
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_logs as logs
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_secretsmanager as secretsmanager
import aws_cdk.aws_sns as sns
import aws_cdk.aws_ssm as ssm
import aws_cdk.aws_stepfunctions as sfn
import aws_cdk.aws_stepfunctions_tasks as tasks
from aws_cdk.aws_lambda_python_alpha import PythonFunction, PythonLayerVersion
from constructs import Construct
from library_layer.config import SteamPulseConfig


class BatchAnalysisStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: SteamPulseConfig,
        vpc: ec2.IVpc,
        intra_sg: ec2.ISecurityGroup,
        db_secret: secretsmanager.ISecret,
        library_layer: PythonLayerVersion,
        content_events_topic: sns.ITopic,
        system_events_topic: sns.ITopic,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env = config.ENVIRONMENT
        private_subnets = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)

        # ── S3 batch bucket ───────────────────────────────────────────────────
        batch_bucket = s3.Bucket(
            self,
            "BatchBucket",
            bucket_name=f"steampulse-batch-{env}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            lifecycle_rules=[
                s3.LifecycleRule(expiration=cdk.Duration.days(7))
            ],
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # ── IAM role assumed by Bedrock to read/write batch bucket ────────────
        batch_role = iam.Role(
            self,
            "BedrockBatchRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            inline_policies={
                "BatchS3Access": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=["s3:GetObject", "s3:PutObject"],
                            resources=[f"{batch_bucket.bucket_arn}/*"],
                        )
                    ]
                )
            },
        )

        # ── Lambda execution role ─────────────────────────────────────────────
        batch_lambda_role = iam.Role(
            self,
            "BatchLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole",
                ),
            ],
        )
        batch_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
                resources=[db_secret.secret_arn],
            )
        )
        batch_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:CreateModelInvocationJob",
                    "bedrock:GetModelInvocationJob",
                    "bedrock:ListModelInvocationJobs",
                    "bedrock:StopModelInvocationJob",
                ],
                resources=["*"],
            )
        )
        batch_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
                resources=[batch_bucket.bucket_arn, f"{batch_bucket.bucket_arn}/*"],
            )
        )
        batch_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[batch_role.role_arn],
            )
        )
        batch_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/steampulse/{env}/*"
                ],
            )
        )
        content_events_topic.grant_publish(batch_lambda_role)
        system_events_topic.grant_publish(batch_lambda_role)

        # ── Shared Lambda environment ─────────────────────────────────────────
        shared_env = config.to_lambda_env(
            BATCH_BUCKET_NAME=batch_bucket.bucket_name,
            BEDROCK_BATCH_ROLE_ARN=batch_role.role_arn,
        )

        def _make_batch_fn(construct_id: str, index: str, powertools_service: str) -> PythonFunction:
            return PythonFunction(
                self,
                construct_id,
                entry="src/lambda-functions",
                index=index,
                handler="handler",
                runtime=lambda_.Runtime.PYTHON_3_12,
                layers=[library_layer],
                role=batch_lambda_role,
                vpc=vpc,
                vpc_subnets=private_subnets,
                security_groups=[intra_sg],
                timeout=cdk.Duration.minutes(10),
                memory_size=1024,
                tracing=lambda_.Tracing.ACTIVE,
                log_group=logs.LogGroup(
                    self,
                    f"{construct_id}Logs",
                    log_group_name=f"/steampulse/{env}/batch-{powertools_service}",
                    retention=logs.RetentionDays.ONE_WEEK,
                    removal_policy=cdk.RemovalPolicy.DESTROY,
                ),
                environment={
                    **shared_env,
                    "POWERTOOLS_SERVICE_NAME": f"batch-{powertools_service}",
                    "POWERTOOLS_METRICS_NAMESPACE": "SteamPulse",
                },
            )

        # ── Lambda functions ──────────────────────────────────────────────────
        prepare_pass1_fn = _make_batch_fn(
            "PreparePass1Fn",
            "lambda_functions/batch_analysis/prepare_pass1.py",
            "prepare-pass1",
        )
        submit_job_fn = _make_batch_fn(
            "SubmitBatchJobFn",
            "lambda_functions/batch_analysis/submit_batch_job.py",
            "submit-job",
        )
        check_status_fn = _make_batch_fn(
            "CheckBatchStatusFn",
            "lambda_functions/batch_analysis/check_batch_status.py",
            "check-status",
        )
        prepare_pass2_fn = _make_batch_fn(
            "PreparePass2Fn",
            "lambda_functions/batch_analysis/prepare_pass2.py",
            "prepare-pass2",
        )
        process_results_fn = _make_batch_fn(
            "ProcessResultsFn",
            "lambda_functions/batch_analysis/process_results.py",
            "process-results",
        )

        # ── Step Functions: STANDARD workflow ─────────────────────────────────
        # STANDARD (not EXPRESS) — batch jobs run for hours, Wait states > 5 min require STANDARD.

        fail_state = sfn.Fail(self, "JobFailed",
            error="BedrockBatchJobFailed",
            cause="Bedrock batch inference job failed",
        )

        # Pass 1 chain
        prepare_pass1_task = tasks.LambdaInvoke(
            self, "PreparePass1",
            lambda_function=prepare_pass1_fn,
            payload=sfn.TaskInput.from_object({
                "execution_id": sfn.JsonPath.string_at("$$.Execution.Name"),
                "appids": sfn.JsonPath.string_at("$.appids"),
            }),
            payload_response_only=True,
            result_path="$.pass1",
        )
        submit_pass1_task = tasks.LambdaInvoke(
            self, "SubmitPass1Job",
            lambda_function=submit_job_fn,
            payload=sfn.TaskInput.from_object({
                "execution_id": sfn.JsonPath.string_at("$$.Execution.Name"),
                "pass": "pass1",
                "model_id": config.model_for("chunking"),
                "input_s3_uri": sfn.JsonPath.string_at("$.pass1.input_s3_uri"),
                "output_s3_uri": sfn.JsonPath.string_at("$.pass1.output_s3_uri"),
            }),
            payload_response_only=True,
            result_path="$.pass1.job",
        )
        wait_pass1 = sfn.Wait(self, "WaitPass1", time=sfn.WaitTime.duration(cdk.Duration.seconds(300)))
        check_pass1_task = tasks.LambdaInvoke(
            self, "CheckPass1Status",
            lambda_function=check_status_fn,
            payload=sfn.TaskInput.from_object({
                "job_id": sfn.JsonPath.string_at("$.pass1.job.job_id"),
            }),
            payload_response_only=True,
            result_path="$.pass1.job.status_result",
        )
        pass1_complete = sfn.Choice(self, "Pass1Complete?")

        # Pass 2 chain
        prepare_pass2_task = tasks.LambdaInvoke(
            self, "PreparePass2",
            lambda_function=prepare_pass2_fn,
            payload=sfn.TaskInput.from_object({
                "execution_id": sfn.JsonPath.string_at("$$.Execution.Name"),
                "pass1_output_s3_uri": sfn.JsonPath.string_at("$.pass1.output_s3_uri"),
            }),
            payload_response_only=True,
            result_path="$.pass2",
        )
        submit_pass2_task = tasks.LambdaInvoke(
            self, "SubmitPass2Job",
            lambda_function=submit_job_fn,
            payload=sfn.TaskInput.from_object({
                "execution_id": sfn.JsonPath.string_at("$$.Execution.Name"),
                "pass": "pass2",
                "model_id": config.model_for("summarizer"),
                "input_s3_uri": sfn.JsonPath.string_at("$.pass2.input_s3_uri"),
                "output_s3_uri": sfn.JsonPath.string_at("$.pass2.output_s3_uri"),
            }),
            payload_response_only=True,
            result_path="$.pass2.job",
        )
        wait_pass2 = sfn.Wait(self, "WaitPass2", time=sfn.WaitTime.duration(cdk.Duration.seconds(300)))
        check_pass2_task = tasks.LambdaInvoke(
            self, "CheckPass2Status",
            lambda_function=check_status_fn,
            payload=sfn.TaskInput.from_object({
                "job_id": sfn.JsonPath.string_at("$.pass2.job.job_id"),
            }),
            payload_response_only=True,
            result_path="$.pass2.job.status_result",
        )
        pass2_complete = sfn.Choice(self, "Pass2Complete?")

        process_results_task = tasks.LambdaInvoke(
            self, "ProcessResults",
            lambda_function=process_results_fn,
            payload=sfn.TaskInput.from_object({
                "pass2_output_s3_uri": sfn.JsonPath.string_at("$.pass2.output_s3_uri"),
                "execution_id": sfn.JsonPath.string_at("$$.Execution.Name"),
            }),
            payload_response_only=True,
        )

        # Wire Pass 1 polling loop
        wait_pass1.next(check_pass1_task)
        pass1_complete.when(
            sfn.Condition.string_equals("$.pass1.job.status_result.status", "Completed"),
            prepare_pass2_task,
        ).when(
            sfn.Condition.string_equals("$.pass1.job.status_result.status", "Failed"),
            fail_state,
        ).otherwise(wait_pass1)

        # Wire Pass 2 polling loop
        wait_pass2.next(check_pass2_task)
        pass2_complete.when(
            sfn.Condition.string_equals("$.pass2.job.status_result.status", "Completed"),
            process_results_task,
        ).when(
            sfn.Condition.string_equals("$.pass2.job.status_result.status", "Failed"),
            fail_state,
        ).otherwise(wait_pass2)

        # Full chain
        definition = (
            prepare_pass1_task
            .next(submit_pass1_task)
            .next(wait_pass1)
            .next(check_pass1_task)
            .next(pass1_complete)
        )
        prepare_pass2_task.next(submit_pass2_task).next(wait_pass2).next(check_pass2_task).next(pass2_complete)

        state_machine = sfn.StateMachine(
            self,
            "BatchAnalysisMachine",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            state_machine_type=sfn.StateMachineType.STANDARD,
            logs=sfn.LogOptions(
                destination=logs.LogGroup(
                    self,
                    "BatchSfnLogs",
                    log_group_name=f"/steampulse/{env}/batch-sfn",
                    retention=logs.RetentionDays.ONE_WEEK,
                    removal_policy=cdk.RemovalPolicy.DESTROY,
                ),
                level=sfn.LogLevel.ERROR,
            ),
        )

        # Publish SSM param for the state machine ARN
        ssm.StringParameter(
            self,
            "BatchSfnArnParam",
            parameter_name=f"/steampulse/{env}/batch/sfn-arn",
            string_value=state_machine.state_machine_arn,
        )

        # ── EventBridge rule (disabled — enable when ready for scheduled re-analysis)
        events.Rule(
            self,
            "WeeklyBatchRule",
            schedule=events.Schedule.cron(hour="3", minute="0", week_day="SUN"),
            enabled=False,
            targets=[
                events_targets.SfnStateMachine(
                    state_machine,
                    input=events.RuleTargetInput.from_object({"appids": "ALL_ELIGIBLE"}),
                )
            ],
        )
