"""CDK entry point. Phase 2 will replace this skeleton with the full pipeline stack."""

import aws_cdk as cdk

from stacks.data_stack import DataStack
from stacks.app_stack import AppStack

app = cdk.App()

account = app.node.try_get_context("account")
region = app.node.try_get_context("region") or "us-west-2"
env = cdk.Environment(account=account, region=region)

data = DataStack(app, "SteamPulseData", env=env)
AppStack(app, "SteamPulseApp", data_stack=data, env=env)

app.synth()
