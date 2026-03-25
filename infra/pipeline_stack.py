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
        *,
        branch: str,
        deploy_stage: str,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        connection_arn: str = self.node.try_get_context("codestar-connection-arn") or ""
        github_repo: str = self.node.try_get_context("github-repo") or "iganza/steam-pulse"

        source = pipelines.CodePipelineSource.connection(
            github_repo,
            branch,
            connection_arn=connection_arn,
            trigger_on_push=True,
        )

        pipeline = pipelines.CodePipeline(
            self,
            "Pipeline",
            pipeline_name=f"steampulse-{deploy_stage.lower()}",
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
                        actions=[
                            "ec2:DescribeAvailabilityZones",
                            "ec2:DescribeImages",  # fck-nat AMI lookup at synth time
                        ],
                        resources=["*"],
                    ),
                ],
            ),
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

        environment = deploy_stage.lower()
        pipeline.add_stage(
            ApplicationStage(
                self,
                f"SteamPulse-{deploy_stage}",
                environment=environment,
                env=cdk.Environment(account=self.account, region=self.region),
            ),
            post=[
                pipelines.CodeBuildStep(
                    "ApplyMigrations",
                    commands=[
                        f"FN_ARN=$(aws ssm get-parameter --name /steampulse/{environment}/compute/migration-fn-arn --query Parameter.Value --output text)",
                        "aws lambda invoke --function-name \"$FN_ARN\" --invocation-type RequestResponse --log-type Tail /tmp/migrate-out.json",
                        "cat /tmp/migrate-out.json",
                    ],
                    role_policy_statements=[
                        iam.PolicyStatement(
                            actions=["ssm:GetParameter"],
                            resources=[f"arn:aws:ssm:{self.region}:{self.account}:parameter/steampulse/{environment}/*"],
                        ),
                        iam.PolicyStatement(
                            actions=["lambda:InvokeFunction"],
                            resources=["*"],
                        ),
                    ],
                ),
                pipelines.CodeBuildStep(
                    "InvalidateCDN",
                    commands=[
                        # Read distribution ID from SSM then invalidate HTML paths
                        f'DIST_ID=$(aws ssm get-parameter --name /steampulse/{environment}/delivery/distribution-id --query Parameter.Value --output text)',
                        'aws cloudfront create-invalidation --distribution-id $DIST_ID --paths "/*"',
                    ],
                    role_policy_statements=[
                        iam.PolicyStatement(
                            actions=["ssm:GetParameter"],
                            resources=[f"arn:aws:ssm:{self.region}:{self.account}:parameter/steampulse/{deploy_stage.lower()}/*"],
                        ),
                        iam.PolicyStatement(
                            actions=["cloudfront:CreateInvalidation"],
                            resources=["*"],
                        ),
                    ],
                ),
            ],
        )
