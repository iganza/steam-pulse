"""CDK entry point — self-mutating pipeline stack."""

import aws_cdk as cdk

from pipeline_stack import PipelineStack

app = cdk.App()

PipelineStack(
    app,
    "SteamPulsePipeline",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "us-west-2",
    ),
)

app.synth()
