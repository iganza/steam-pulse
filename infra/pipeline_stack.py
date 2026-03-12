"""Self-mutating CDK Pipeline via CodeStar Connection to GitHub."""

import aws_cdk as cdk
import aws_cdk.aws_codepipeline as codepipeline
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
        )

        pipeline = pipelines.CodePipeline(
            self,
            "Pipeline",
            code_pipeline=codepipeline.Pipeline(
                self,
                "PipelineV2",
                pipeline_name="steampulse",  # human-readable name in Console
                pipeline_type=codepipeline.PipelineType.V2,
            ),
            synth=pipelines.ShellStep(
                "Synth",
                input=source,
                commands=[
                    "npm install -g aws-cdk",
                    "pip install poetry",
                    "poetry install --with infra",
                    "poetry run cdk synth",
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
