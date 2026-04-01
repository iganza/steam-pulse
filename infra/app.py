"""CDK entry point — direct stack deployment (no pipeline).

Deploy with:
    ./scripts/deploy.sh --env staging
    ./scripts/deploy.sh --env production

Or manually:
    cd frontend && npx open-next build
    cd infra && poetry run cdk deploy 'SteamPulse-Staging-*' --require-approval never
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "library-layer"))

import aws_cdk as cdk

from application_stage import ApplicationStage
from stacks.monitoring_stack import MonitoringStack
from library_layer.config import SteamPulseConfig

app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account"),
    region=app.node.try_get_context("region") or "us-west-2",
)

# Staging stacks — deploy with: cdk deploy 'SteamPulse-Staging-*'
ApplicationStage(
    app,
    "SteamPulse-Staging",
    environment="staging",
    env=env,
)

# Production stacks — deploy with: cdk deploy 'SteamPulse-Production-*'
# Uncomment when ready to go live.
# ApplicationStage(
#     app,
#     "SteamPulse-Production",
#     environment="production",
#     env=env,
# )

# ── Monitoring stacks (standalone) ───────────────────────────────────────────
MonitoringStack(
    app,
    "SteamPulse-Staging-Monitoring",
    stack_name="SteamPulse-Staging-Monitoring",
    config=SteamPulseConfig.for_environment("staging"),
    env=env,
)

# Production — uncomment when ready
# MonitoringStack(
#     app,
#     "SteamPulse-Production-Monitoring",
#     stack_name="SteamPulse-Production-Monitoring",
#     config=SteamPulseConfig.for_environment("production"),
#     env=env,
# )

app.synth()
