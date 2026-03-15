"""FrontendStack — uploads Next.js static assets to S3.

Kept as a separate stack so that frontend-only deploys don't re-synthesise
BackendStack. Receives assets_bucket as a direct CDK object reference, which is
the CDK best-practice approach for two stacks in the same app. The resulting
Fn::ImportValue is safe here because the bucket has RETAIN removal policy — its
ARN never changes, so the export value is stable and can never deadlock.
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
        assets_bucket: s3.IBucket,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if os.path.isdir(_OPEN_NEXT_ASSETS):
            s3deploy.BucketDeployment(
                self,
                "AssetsDeployment",
                sources=[s3deploy.Source.asset(_OPEN_NEXT_ASSETS)],
                destination_bucket=assets_bucket,
                prune=True,
            )
