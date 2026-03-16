"""Analysis stack — Step Functions Express Workflow for LLM analysis pipeline.

Single-Lambda design: analysis/handler.py reads reviews from DB, runs two-pass
Haiku→Sonnet analysis via analyzer.py, and writes the report back to DB.
Step Functions provides retry logic and execution history.
"""

import aws_cdk as cdk
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_logs as logs
import aws_cdk.aws_secretsmanager as secretsmanager
import aws_cdk.aws_ssm as ssm
import aws_cdk.aws_stepfunctions as sfn
import aws_cdk.aws_stepfunctions_tasks as tasks
from constructs import Construct


class AnalysisStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        intra_sg: ec2.ISecurityGroup,
        db_secret: secretsmanager.ISecret,
        library_layer: lambda_.ILayerVersion,
        stage: str = "staging",
        is_production: bool = False,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

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
        role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
            resources=[db_secret.secret_arn],
        ))
        # Bedrock access for LLM calls
        role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=["*"],
        ))

        # Model names are runtime config, not CDK objects — keep SSM reads
        haiku_model = ssm.StringParameter.value_for_string_parameter(
            self, f"/steampulse/{stage}/llm/haiku-model"
        )
        sonnet_model = ssm.StringParameter.value_for_string_parameter(
            self, f"/steampulse/{stage}/llm/sonnet-model"
        )

        log_group = logs.LogGroup(
            self,
            "AnalysisLambdaLogs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # Single Lambda — runs the full two-pass analysis for one game
        analysis_fn = lambda_.Function(
            self,
            "AnalysisFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_functions.analysis.handler.handler",
            code=lambda_.Code.from_asset("src/lambda-functions"),
            layers=[library_layer],
            role=role,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS if is_production else ec2.SubnetType.PUBLIC
            ),
            allow_public_subnet=True,
            security_groups=[intra_sg],
            timeout=cdk.Duration.minutes(10),
            memory_size=1024,
            environment={
                "DB_SECRET_ARN": db_secret.secret_arn,
                "HAIKU_MODEL": haiku_model,
                "SONNET_MODEL": sonnet_model,
            },
            log_group=log_group,
        )

        # Step Functions — single task with built-in retry
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

        sfn_log_group = logs.LogGroup(self, "StateMachineLogs",
                                      retention=logs.RetentionDays.ONE_WEEK)

        machine = sfn.StateMachine(
            self,
            "AnalysisMachine",
            state_machine_name=f"{stage}-steampulse-analysis",
            definition_body=sfn.DefinitionBody.from_chainable(analyze_task),
            state_machine_type=sfn.StateMachineType.EXPRESS,
            timeout=cdk.Duration.minutes(15),
            logs=sfn.LogOptions(
                destination=sfn_log_group,
                level=sfn.LogLevel.ERROR,
            ),
        )

        self.state_machine = machine
        self.state_machine_arn = machine.state_machine_arn
