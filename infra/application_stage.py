"""ApplicationStage — three stacks: FoundationStack → BackendStack → FrontendStack.

Config is loaded from .env.{environment} at synth time and passed through
constructors — the CDK best-practice approach (configure with properties,
not environment variable lookups inside stacks).
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "library-layer"))

import aws_cdk as cdk
from constructs import Construct

from library_layer.config import SteamPulseConfig
from stacks.foundation_stack import FoundationStack
from stacks.backend_stack import BackendStack
from stacks.frontend_stack import FrontendStack


class ApplicationStage(cdk.Stage):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        environment: str,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        config = SteamPulseConfig.for_environment(environment)
        env_name = environment.capitalize()
        cdk_env = cdk.Environment(account=self.account, region=self.region)

        foundation = FoundationStack(
            self, "Foundation",
            stack_name=f"SteamPulse-{env_name}-Foundation",
            config=config,
            termination_protection=config.is_production,
            env=cdk_env,
        )

        backend = BackendStack(
            self, "Backend",
            stack_name=f"SteamPulse-{env_name}-Backend",
            config=config,
            vpc=foundation.vpc,
            intra_sg=foundation.intra_sg,
            db_secret=foundation.db_secret,
            termination_protection=config.is_production,
            env=cdk_env,
        )

        FrontendStack(
            self, "Frontend",
            stack_name=f"SteamPulse-{env_name}-Frontend",
            config=config,
            assets_bucket=backend.assets_bucket,
            env=cdk_env,
        )
