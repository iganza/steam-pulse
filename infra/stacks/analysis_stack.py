"""Analysis stack — Step Functions Express Workflow for LLM analysis pipeline."""

import aws_cdk as cdk
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_logs as logs
import aws_cdk.aws_secretsmanager as secretsmanager
import aws_cdk.aws_stepfunctions as sfn
import aws_cdk.aws_stepfunctions_tasks as tasks
from constructs import Construct

# Inline placeholder — replaced when Phase 3 crawler code ships
_PLACEHOLDER = "def handler(event, context): return event"


class AnalysisStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.Vpc,
        db_secret: secretsmanager.ISecret,
        stage: str = "staging",
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Shared Lambda execution role
        role = iam.Role(
            self,
            "AnalysisRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole"
                ),
            ],
        )
        db_secret.grant_read(role)

        # SSM param for Anthropic key ARN — secret stored in Secrets Manager,
        # ARN passed via context so no hardcoded values here.
        anthropic_secret_arn: str = self.node.try_get_context("anthropic_secret_arn") or ""
        if anthropic_secret_arn:
            anthropic_secret = secretsmanager.Secret.from_secret_complete_arn(
                self, "AnthropicSecret", anthropic_secret_arn
            )
            anthropic_secret.grant_read(role)

        def _lambda(name: str, handler: str, timeout_seconds: int = 60) -> lambda_.Function:
            log_group = logs.LogGroup(
                self,
                f"{name}Logs",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            )
            return lambda_.Function(
                self,
                name,
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler=handler,
                code=lambda_.Code.from_inline(_PLACEHOLDER),
                role=role,
                vpc=vpc,
                vpc_subnets=ec2.SubnetSelection(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                ),
                timeout=cdk.Duration.seconds(timeout_seconds),
                environment={
                    "DB_SECRET_ARN": db_secret.secret_arn,
                    **({"ANTHROPIC_SECRET_ARN": anthropic_secret_arn} if anthropic_secret_arn else {}),
                },
                log_group=log_group,
            )

        fetch_fn = _lambda("FetchReviews", "handler.handler", timeout_seconds=120)
        chunks_fn = _lambda("PrepareChunks", "handler.handler")
        analyze_fn = _lambda("AnalyzeChunk", "handler.handler", timeout_seconds=120)
        synthesize_fn = _lambda("SynthesizeReport", "handler.handler", timeout_seconds=300)
        store_fn = _lambda("StoreReport", "handler.handler")
        invalidate_fn = _lambda("InvalidateCache", "handler.handler")

        # Step Functions tasks
        fetch_task = tasks.LambdaInvoke(self, "FetchReviewsTask", lambda_function=fetch_fn,
                                        result_path="$.reviews")
        chunks_task = tasks.LambdaInvoke(self, "PrepareChunksTask", lambda_function=chunks_fn,
                                         result_path="$.chunks")
        analyze_task = tasks.LambdaInvoke(self, "AnalyzeChunkTask", lambda_function=analyze_fn,
                                          result_path="$.chunk_result")
        synthesize_task = tasks.LambdaInvoke(self, "SynthesizeReportTask",
                                             lambda_function=synthesize_fn,
                                             result_path="$.report")
        store_task = tasks.LambdaInvoke(self, "StoreReportTask", lambda_function=store_fn,
                                        result_path="$.stored")
        invalidate_task = tasks.LambdaInvoke(self, "InvalidateCacheTask",
                                             lambda_function=invalidate_fn,
                                             result_path="$.invalidated")

        # Map state: process chunks in parallel (max 5 concurrent)
        chunk_map = sfn.Map(
            self,
            "ChunkMap",
            items_path="$.chunks.Payload",
            max_concurrency=5,
            result_path="$.chunk_summaries",
        ).item_processor(analyze_task)

        # State machine definition
        definition = (
            fetch_task
            .next(chunks_task)
            .next(chunk_map)
            .next(synthesize_task)
            .next(store_task)
            .next(invalidate_task)
        )

        log_group = logs.LogGroup(self, "StateMachineLogs",
                                  retention=logs.RetentionDays.ONE_WEEK)

        machine = sfn.StateMachine(
            self,
            "AnalysisMachine",
            state_machine_name=f"{stage}-steampulse-analysis",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            state_machine_type=sfn.StateMachineType.EXPRESS,
            timeout=cdk.Duration.minutes(15),
            logs=sfn.LogOptions(
                destination=log_group,
                level=sfn.LogLevel.ERROR,
            ),
        )

        self.state_machine = machine
        self.state_machine_arn = machine.state_machine_arn
