"""CDK entry point — self-mutating pipeline stacks.

Two pipelines:
  SteamPulsePipeline           — watches 'staging' branch → deploys Staging
  SteamPulseProductionPipeline — watches 'main' branch    → deploys Production (disabled)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "library-layer"))

import aws_cdk as cdk

from pipeline_stack import PipelineStack
from stacks.monitoring_stack import MonitoringStack
from library_layer.config import SteamPulseConfig

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

# ── Monitoring stacks (standalone — not in the pipeline) ─────────────────────
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
