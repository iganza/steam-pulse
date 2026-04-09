"""BatchAnalysisStack — Bedrock Batch Inference pipeline for bulk game analysis.

Per-game Step Functions execution. A parent Map state fans out across an
`appids` list; each child execution runs the three phases against ONE game
through parametrised PreparePhase / CollectPhase Lambdas plus a shared
CheckBatchStatus poller.

Resources:
  - S3 bucket for batch I/O (7-day lifecycle, auto-deleted)
  - IAM role assumed by Bedrock to read/write S3
  - 3 Lambdas: PreparePhase, CollectPhase, CheckBatchStatus
  - STANDARD Step Functions state machine (wait/choice loops per phase)
  - EventBridge rule (disabled by default — for future scheduled re-analysis)
"""

import aws_cdk as cdk
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_logs as logs
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_secretsmanager as secretsmanager
import aws_cdk.aws_sns as sns
import aws_cdk.aws_ssm as ssm
import aws_cdk.aws_stepfunctions as sfn
import aws_cdk.aws_stepfunctions_tasks as tasks
from aws_cdk.aws_lambda_python_alpha import PythonFunction
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
        content_events_topic: sns.ITopic,
        system_events_topic: sns.ITopic,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env = config.ENVIRONMENT
        private_subnets = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)

        # ── Library layer (looked up from SSM — published by ComputeStack) ────
        library_layer = lambda_.LayerVersion.from_layer_version_arn(
            self,
            "LibraryLayer",
            ssm.StringParameter.value_for_string_parameter(self, config.library_layer_ssm_path),
        )

        # ── S3 batch bucket ───────────────────────────────────────────────────
        batch_bucket = s3.Bucket(
            self,
            "BatchBucket",
            bucket_name=f"steampulse-batch-{env}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            lifecycle_rules=[s3.LifecycleRule(expiration=cdk.Duration.days(7))],
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

        def _make_batch_fn(
            construct_id: str, index: str, powertools_service: str
        ) -> PythonFunction:
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

        prepare_fn = _make_batch_fn(
            "PreparePhaseFn",
            "lambda_functions/batch_analysis/prepare_phase.py",
            "prepare-phase",
        )
        collect_fn = _make_batch_fn(
            "CollectPhaseFn",
            "lambda_functions/batch_analysis/collect_phase.py",
            "collect-phase",
        )
        check_status_fn = _make_batch_fn(
            "CheckBatchStatusFn",
            "lambda_functions/batch_analysis/check_batch_status.py",
            "check-status",
        )

        # ── Step Functions: STANDARD workflow — one execution per appid ──────
        # The outer Map state (in the parent trigger, not here) iterates over
        # `appids` and invokes this state machine once per game. Each execution
        # runs the three phases against a single appid.

        fail_state = sfn.Fail(
            self,
            "PhaseFailed",
            error="BedrockBatchJobFailed",
            cause="Bedrock batch inference job failed",
        )

        def _phase_chain(phase: str, next_step: sfn.IChainable) -> sfn.IChainable:
            prepare_payload: dict[str, object] = {
                "appid": sfn.JsonPath.number_at("$.appid"),
                "phase": phase,
                "execution_id": sfn.JsonPath.string_at("$$.Execution.Name"),
            }
            if phase == "synthesis":
                # Thread the exact merge artifact this execution produced
                # forward into PrepareSynthesis so it does NOT re-discover
                # the merge row via a non-deterministic "(appid, latest)"
                # lookup — which races under concurrent re-analysis for
                # the same appid. PrepareMerge runs inline and returns
                # `merged_summary_id` in its phase output (stored under
                # `$.merge` via its `result_path`).
                prepare_payload["merged_summary_id"] = sfn.JsonPath.number_at(
                    "$.merge.merged_summary_id"
                )
            prepare = tasks.LambdaInvoke(
                self,
                f"Prepare{phase.capitalize()}",
                lambda_function=prepare_fn,
                payload=sfn.TaskInput.from_object(prepare_payload),
                payload_response_only=True,
                result_path=f"$.{phase}",
            )
            skip_check = sfn.Choice(self, f"{phase.capitalize()}Skipped?")
            wait = sfn.Wait(
                self,
                f"Wait{phase.capitalize()}",
                time=sfn.WaitTime.duration(cdk.Duration.seconds(300)),
            )
            check = tasks.LambdaInvoke(
                self,
                f"Check{phase.capitalize()}Status",
                lambda_function=check_status_fn,
                payload=sfn.TaskInput.from_object(
                    {"job_id": sfn.JsonPath.string_at(f"$.{phase}.job_id")}
                ),
                payload_response_only=True,
                result_path=f"$.{phase}.status_result",
            )
            done_choice = sfn.Choice(self, f"{phase.capitalize()}Complete?")
            # Synthesis's prepare payload returns `merged_summary_id` and
            # `chunk_count` — both are threaded through to collect so the
            # final report.upsert records the exact merged row we
            # synthesised against and the exact chunk count that fed it,
            # instead of racing on find_latest_by_appid / find_by_appid.
            collect_payload: dict[str, object] = {
                "appid": sfn.JsonPath.number_at("$.appid"),
                "phase": phase,
                "execution_id": sfn.JsonPath.string_at("$$.Execution.Name"),
                "job_id": sfn.JsonPath.string_at(f"$.{phase}.job_id"),
            }
            if phase == "synthesis":
                collect_payload["merged_summary_id"] = sfn.JsonPath.number_at(
                    "$.synthesis.merged_summary_id"
                )
                collect_payload["chunk_count"] = sfn.JsonPath.number_at(
                    "$.synthesis.chunk_count"
                )
            collect = tasks.LambdaInvoke(
                self,
                f"Collect{phase.capitalize()}",
                lambda_function=collect_fn,
                payload=sfn.TaskInput.from_object(collect_payload),
                payload_response_only=True,
                result_path=f"$.{phase}.collected",
            )

            # Wire: prepare → skip? → (wait → check → done? → collect → next)
            prepare.next(skip_check)
            skip_check.when(
                sfn.Condition.boolean_equals(f"$.{phase}.skip", True), next_step
            ).otherwise(wait)
            wait.next(check).next(done_choice)
            done_choice.when(
                sfn.Condition.string_equals(f"$.{phase}.status_result.status", "Completed"),
                collect,
            ).when(
                sfn.Condition.string_equals(f"$.{phase}.status_result.status", "Failed"),
                fail_state,
            ).otherwise(wait)
            collect.next(next_step)
            return prepare

        done = sfn.Succeed(self, "AnalysisComplete")
        synthesis_chain = _phase_chain("synthesis", done)
        merge_chain = _phase_chain("merge", synthesis_chain)
        chunk_chain = _phase_chain("chunk", merge_chain)

        state_machine = sfn.StateMachine(
            self,
            "BatchAnalysisMachine",
            state_machine_name=f"steampulse-batch-analysis-{env}",
            definition_body=sfn.DefinitionBody.from_chainable(chunk_chain),
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

        # ── Scheduled trigger is NOT wired here on purpose.
        #
        # This state machine runs one execution per appid. The only
        # required external input is `{"appid": <int>}`; `phase` is
        # selected by the workflow itself and `execution_id` is derived
        # from the Step Functions execution context (`$$.Execution.Name`).
        # A scheduled trigger must therefore fan out over a list of appids
        # before it invokes the machine — a Map state driven by a parent
        # trigger, or a small dispatcher Lambda that queries eligible
        # appids and issues `StartExecution` per row.
        #
        # We previously carried a disabled EventBridge rule with a
        # placeholder `{"appid": 0}` input as a reminder to wire this up.
        # That turned out to be a foot-gun: if someone enabled the rule
        # without noticing the placeholder, every execution would fail
        # with a validation error (or worse, hit appid 0 as real data).
        # Remove the reminder rule entirely; the fan-out dispatcher is the
        # right place to add the schedule when Bedrock Batch Inference is
        # unblocked and we're ready to run bulk re-analysis.
