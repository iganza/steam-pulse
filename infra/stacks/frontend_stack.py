"""FrontendStack — uploads Next.js static assets to S3.

Kept as a separate stack so that frontend-only deploys don't re-synthesise
ComputeStack. Looks up the assets bucket by deterministic name.
"""

import os

import aws_cdk as cdk
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_s3_deployment as s3deploy
from constructs import Construct
from library_layer.config import SteamPulseConfig

_OPEN_NEXT_ASSETS = "frontend/.open-next/assets"


class FrontendStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: SteamPulseConfig,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env = config.ENVIRONMENT
        assets_bucket = s3.Bucket.from_bucket_name(
            self,
            "AssetsBucket",
            f"steampulse-assets-{env}",
        )

        if os.path.isdir(_OPEN_NEXT_ASSETS):
            s3deploy.BucketDeployment(
                self,
                "AssetsDeployment",
                sources=[s3deploy.Source.asset(_OPEN_NEXT_ASSETS)],
                destination_bucket=assets_bucket,
                prune=True,
            )
