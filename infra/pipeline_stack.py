"""Self-mutating CDK Pipeline via CodeStar Connection to GitHub."""

import aws_cdk as cdk
import aws_cdk.aws_codepipeline as codepipeline
import aws_cdk.aws_iam as iam
import aws_cdk.pipelines as pipelines
from constructs import Construct

from application_stage import ApplicationStage


class PipelineStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        connection_arn: str = self.node.try_get_context("codestar-connection-arn") or ""
        github_repo: str = self.node.try_get_context("github-repo") or "iganza/steam-pulse"
        github_branch: str = self.node.try_get_context("github-branch") or "main"

        source = pipelines.CodePipelineSource.connection(
            github_repo,
            github_branch,
            connection_arn=connection_arn,
            trigger_on_push=True,
        )

        pipeline = pipelines.CodePipeline(
            self,
            "Pipeline",
            pipeline_name="steampulse",
            pipeline_type=codepipeline.PipelineType.V2,
            synth=pipelines.CodeBuildStep(
                "Synth",
                input=source,
                commands=[
                    "npm install -g aws-cdk",
                    "pip install poetry",
                    "poetry install --with infra",
                    "poetry run cdk synth",
                ],
                role_policy_statements=[
                    iam.PolicyStatement(
                        actions=["ec2:DescribeAvailabilityZones"],
                        resources=["*"],
                    ),
                ],
            ),
            docker_enabled_for_synth=True,
        )

        # Staging — auto-deploys on every push to main
        pipeline.add_stage(
            ApplicationStage(
                self,
                "Staging",
                env=cdk.Environment(account=self.account, region=self.region),
            )
        )

        # Production — manual approval gate
        pipeline.add_stage(
            ApplicationStage(
                self,
                "Production",
                env=cdk.Environment(account=self.account, region=self.region),
            ),
            pre=[pipelines.ManualApprovalStep("PromoteToProduction")],
        )

        # Force pipeline materialization so we can access the underlying construct,
        # then add a V2 push trigger for the CodeStar connection.
        pipeline.build_pipeline()
        pipeline.pipeline.add_trigger(
            provider_type=codepipeline.ProviderType.CODE_STAR_SOURCE_CONNECTION,
            git_configuration=codepipeline.GitConfiguration(
                source_action=pipeline.pipeline.stages[0].actions[0],
                push_filter=[
                    codepipeline.GitPushFilter(
                        branches_includes=[github_branch],
                    )
                ],
            ),
        )
