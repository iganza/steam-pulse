"""CDK entry point — self-mutating pipeline stacks.

Two pipelines:
  SteamPulsePipeline           — watches 'staging' branch → deploys Staging
  SteamPulseProductionPipeline — watches 'main' branch    → deploys Production (disabled)
"""

import aws_cdk as cdk

from pipeline_stack import PipelineStack

app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account"),
    region=app.node.try_get_context("region") or "us-west-2",
)

# Staging pipeline — watches 'staging' branch
PipelineStack(
    app,
    "SteamPulsePipeline",
    branch="staging",
    deploy_stage="Staging",
    env=env,
)

# Production pipeline — uncomment when ready to go live
# PipelineStack(
#     app,
#     "SteamPulseProductionPipeline",
#     branch="main",
#     deploy_stage="Production",
#     env=env,
# )

app.synth()
