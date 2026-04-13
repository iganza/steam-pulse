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
        # Kept as an inert construct (Lambda env vars reference the ARN at
        # module level). S3 policy removed — even if invoked, Bedrock cannot
        # read or write the batch bucket.
        batch_role = iam.Role(
            self,
            "BedrockBatchRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
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
        anthropic_secret = secretsmanager.Secret.from_secret_name_v2(
            self,
            "BatchAnthropicApiKey",
            f"/steampulse/{env}/anthropic-api-key",
        )
        db_secret.grant_read(batch_lambda_role)
        anthropic_secret.grant_read(batch_lambda_role)
        # Bedrock batch permissions REMOVED — Anthropic direct API is the
        # sole batch backend. The Bedrock service role + S3 bucket are kept
        # as inert infrastructure (Lambda env vars still reference them at
        # module level) but the Lambda cannot invoke Bedrock batch or pass
        # the role. To re-enable, restore bedrock:*, s3:*, and iam:PassRole
        # grants here.
        batch_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/steampulse/{env}/*"
                ],
            )
        )
        # SFN start permission added upfront (not via grant_start_execution)
        # to avoid a circular dependency: role ← orchestrator ← state machine
        # ← Lambdas ← role.
        batch_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["states:StartExecution"],
                resources=[
                    f"arn:aws:states:{self.region}:{self.account}:stateMachine:steampulse-batch-*-{env}",
                    f"arn:aws:states:{self.region}:{self.account}:execution:steampulse-batch-*-{env}:*"
                ],
            )
        )
        content_events_topic.grant_publish(batch_lambda_role)
        system_events_topic.grant_publish(batch_lambda_role)

        # ── Shared Lambda environment ─────────────────────────────────────────
        shared_env = config.to_lambda_env(
            BATCH_BUCKET_NAME=batch_bucket.bucket_name,
            BEDROCK_BATCH_ROLE_ARN=batch_role.role_arn,
            # Hard-pin to Anthropic — Bedrock batch IAM permissions have been
            # removed. Overrides whatever .env sets so a missing/stale config
            # can't route to a permission-denied Bedrock path.
            LLM_BACKEND="anthropic",
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
                collect_payload["chunk_count"] = sfn.JsonPath.number_at("$.synthesis.chunk_count")
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

        def _merge_level_chain(
            suffix: str, merge_level: int, next_step: sfn.IChainable
        ) -> sfn.IChainable:
            """Build one merge level: prepare → skip? → wait → check → done? → collect → next.

            Both merge levels share ``$.merge`` as their state key (via
            ``result_path``). Collect writes directly to ``$.merge``
            (overwriting prepare output) so that ``merged_summary_id``
            always lives at ``$.merge.merged_summary_id`` regardless of
            whether the phase was skipped or collected.
            """
            name = f"Merge{suffix}"
            prepare_payload: dict[str, object] = {
                "appid": sfn.JsonPath.number_at("$.appid"),
                "phase": "merge",
                "execution_id": sfn.JsonPath.string_at("$$.Execution.Name"),
                "merge_level": merge_level,
            }
            if merge_level == 2:
                # L2 reads intermediate IDs produced by L1.
                prepare_payload["merged_ids"] = sfn.JsonPath.list_at("$.merge.merged_ids")
            prepare = tasks.LambdaInvoke(
                self,
                f"Prepare{name}",
                lambda_function=prepare_fn,
                payload=sfn.TaskInput.from_object(prepare_payload),
                payload_response_only=True,
                result_path="$.merge",
            )
            skip_check = sfn.Choice(self, f"{name}Skipped?")
            wait = sfn.Wait(
                self,
                f"Wait{name}",
                time=sfn.WaitTime.duration(cdk.Duration.seconds(300)),
            )
            check = tasks.LambdaInvoke(
                self,
                f"Check{name}Status",
                lambda_function=check_status_fn,
                payload=sfn.TaskInput.from_object(
                    {"job_id": sfn.JsonPath.string_at("$.merge.job_id")}
                ),
                payload_response_only=True,
                result_path="$.merge.status_result",
            )
            done_choice = sfn.Choice(self, f"{name}Complete?")
            collect_payload: dict[str, object] = {
                "appid": sfn.JsonPath.number_at("$.appid"),
                "phase": "merge",
                "execution_id": sfn.JsonPath.string_at("$$.Execution.Name"),
                "job_id": sfn.JsonPath.string_at("$.merge.job_id"),
                "merge_level": merge_level,
                "group_meta": sfn.JsonPath.list_at("$.merge.group_meta"),
                "cached_group_meta": sfn.JsonPath.list_at("$.merge.cached_group_meta"),
            }
            # Collect writes to $.merge (not $.merge.collected) so
            # merged_summary_id / merged_ids are at $.merge.* for the
            # next level and synthesis to consume.
            collect = tasks.LambdaInvoke(
                self,
                f"Collect{name}",
                lambda_function=collect_fn,
                payload=sfn.TaskInput.from_object(collect_payload),
                payload_response_only=True,
                result_path="$.merge",
            )

            prepare.next(skip_check)
            skip_check.when(
                sfn.Condition.boolean_equals("$.merge.skip", True), next_step
            ).otherwise(wait)
            wait.next(check).next(done_choice)
            done_choice.when(
                sfn.Condition.string_equals("$.merge.status_result.status", "Completed"),
                collect,
            ).when(
                sfn.Condition.string_equals("$.merge.status_result.status", "Failed"),
                fail_state,
            ).otherwise(wait)
            collect.next(next_step)
            return prepare

        done = sfn.Succeed(self, "AnalysisComplete")
        synthesis_chain = _phase_chain("synthesis", done)

        # Safety gate: after L2 completes, verify merged_summary_id is
        # set. If L2 somehow produced multiple intermediates (requires
        # >1600 chunks — guarded in prepare, but defense-in-depth),
        # fail with a clear message rather than crashing synthesis on
        # a null JSONPath reference.
        merge_l2_converged = sfn.Choice(self, "MergeL2Converged?")
        merge_l2_converged.when(
            sfn.Condition.is_not_null("$.merge.merged_summary_id"),
            synthesis_chain,
        ).otherwise(
            sfn.Fail(
                self,
                "MergeNotConverged",
                error="MergeNotConverged",
                cause="Merge did not converge to a single merged_summary_id after L2",
            )
        )

        merge_l2_chain = _merge_level_chain("L2", 2, merge_l2_converged)

        # After L1 (skip or collect), check if L2 is needed: when
        # merged_summary_id is set (single result), jump straight to
        # synthesis. Only route to L2 when multiple intermediates remain.
        merge_needs_l2 = sfn.Choice(self, "MergeNeedsL2?")
        merge_needs_l2.when(
            sfn.Condition.is_not_null("$.merge.merged_summary_id"),
            synthesis_chain,
        ).otherwise(merge_l2_chain)

        merge_l1_chain = _merge_level_chain("", 1, merge_needs_l2)
        chunk_chain = _phase_chain("chunk", merge_l1_chain)

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

        # ── Dispatch Lambda — reads matview, starts orchestrator, publishes
        #    batch-analysis-complete event after fan-out completes ──────────
        dispatch_fn = PythonFunction(
            self,
            "DispatchBatchFn",
            entry="src/lambda-functions",
            index="lambda_functions/batch_analysis/dispatch_batch.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[library_layer],
            role=batch_lambda_role,
            vpc=vpc,
            vpc_subnets=private_subnets,
            security_groups=[intra_sg],
            timeout=cdk.Duration.seconds(30),
            memory_size=256,
            tracing=lambda_.Tracing.ACTIVE,
            log_group=logs.LogGroup(
                self,
                "DispatchBatchLogs",
                log_group_name=f"/steampulse/{env}/batch-dispatch",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment={
                **shared_env,
                "POWERTOOLS_SERVICE_NAME": "batch-dispatch",
                "POWERTOOLS_METRICS_NAMESPACE": "SteamPulse",
            },
        )
        # NOTE: orchestrator.grant_start_execution(dispatch_fn) is NOT used
        # here — the permission lives on batch_lambda_role (upfront) to avoid
        # a circular dependency through the shared role.

        # ── Orchestrator: fan-out over appid list via DistributedMap ─────
        #
        # Accepts {"appids": [440, 730, ...], "max_concurrency": 20} and
        # starts one per-game child execution per appid. MaxConcurrency is
        # read from the input payload at runtime (max_concurrency_path) so
        # the CLI can throttle without redeploying.

        # Compute appids_count before the map — the count is threaded to
        # the post-batch Lambda so the event carries meaningful totals.
        count_appids = sfn.Pass(
            self,
            "CountAppids",
            parameters={
                "appids": sfn.JsonPath.list_at("$.appids"),
                "max_concurrency": sfn.JsonPath.number_at("$.max_concurrency"),
                "appids_count": sfn.JsonPath.array_length(
                    sfn.JsonPath.list_at("$.appids")
                ),
            },
        )

        fan_out = sfn.DistributedMap(
            self,
            "FanOut",
            items_path="$.appids",
            max_concurrency_path="$.max_concurrency",
            tolerated_failure_percentage=10,
            # Discard per-item results to stay under the 256KB state limit.
            # The post-batch Lambda only needs the execution ID and total
            # appids count (preserved via result_path).
            result_path=sfn.JsonPath.DISCARD,
        )
        fan_out.item_processor(
            tasks.StepFunctionsStartExecution(
                self,
                "RunPerGame",
                state_machine=state_machine,
                integration_pattern=sfn.IntegrationPattern.RUN_JOB,
                input=sfn.TaskInput.from_object({"appid": sfn.JsonPath.number_at("$")}),
            )
        )

        # After all games complete, publish batch-analysis-complete event
        # so matview refresh fires immediately (bypassing debounce).
        # Retry on transient failures; catch and continue to Succeed so a
        # notification failure doesn't fail the orchestrator after all games
        # completed. The 6h EventBridge fallback covers missed refreshes.
        publish_batch_complete = tasks.LambdaInvoke(
            self,
            "PublishBatchAnalysisComplete",
            lambda_function=dispatch_fn,
            payload=sfn.TaskInput.from_object({
                "action": "post_batch",
                "execution_id": sfn.JsonPath.string_at("$$.Execution.Name"),
                "appids_count": sfn.JsonPath.number_at("$.appids_count"),
            }),
            payload_response_only=True,
            retry_on_service_exceptions=True,
        )
        publish_batch_complete.add_retry(
            errors=["States.ALL"],
            interval=cdk.Duration.seconds(5),
            max_attempts=2,
            backoff_rate=2,
        )
        batch_complete = sfn.Succeed(self, "BatchOrchestrationComplete")
        publish_batch_complete.add_catch(batch_complete, result_path="$.publish_error")
        count_appids.next(fan_out).next(publish_batch_complete).next(batch_complete)

        orchestrator = sfn.StateMachine(
            self,
            "BatchOrchestrator",
            state_machine_name=f"steampulse-batch-orchestrator-{env}",
            definition_body=sfn.DefinitionBody.from_chainable(count_appids),
            state_machine_type=sfn.StateMachineType.STANDARD,
            logs=sfn.LogOptions(
                destination=logs.LogGroup(
                    self,
                    "OrchestratorLogs",
                    log_group_name=f"/steampulse/{env}/batch-orchestrator",
                    retention=logs.RetentionDays.ONE_WEEK,
                    removal_policy=cdk.RemovalPolicy.DESTROY,
                ),
                level=sfn.LogLevel.ERROR,
            ),
        )

        # Grant orchestrator permission to drive the per-game machine
        state_machine.grant_start_execution(orchestrator)
        state_machine.grant(orchestrator, "states:DescribeExecution")
        state_machine.grant(orchestrator, "states:StopExecution")

        # Publish orchestrator ARN to SSM
        ssm.StringParameter(
            self,
            "OrchestratorSfnArnParam",
            parameter_name=f"/steampulse/{env}/batch/orchestrator-sfn-arn",
            string_value=orchestrator.state_machine_arn,
        )

        # Publish dispatch Lambda name to SSM for CLI invocation
        ssm.StringParameter(
            self,
            "DispatchBatchFnNameParam",
            parameter_name=f"/steampulse/{env}/batch/dispatch-fn-name",
            string_value=dispatch_fn.function_name,
        )
