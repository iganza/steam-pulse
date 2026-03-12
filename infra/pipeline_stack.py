"""Self-mutating CDK Pipeline via CodeStar Connection to GitHub."""

import aws_cdk as cdk
import aws_cdk.aws_codebuild as codebuild
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
                    "cd frontend && npm ci && npx open-next@latest build && cd ..",
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
            # Use BuildSpec runtime-versions to get Node 22 + Python 3.12
            # (cleaner than nvm shell commands — matches how production CDK projects do it)
            synth_code_build_defaults=pipelines.CodeBuildOptions(
                partial_build_spec=codebuild.BuildSpec.from_object({
                    "phases": {
                        "install": {
                            "runtime-versions": {
                                "nodejs": "22.x",
                                "python": "3.12",
                            }
                        }
                    }
                }),
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
