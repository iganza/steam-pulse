"""Frontend stack — uploads Next.js static assets to S3.

The SSR Lambda and CloudFront behaviors live in AppStack to avoid cross-stack
cyclic references. This stack only handles BucketDeployment, creating a clean
one-way dependency: Frontend → App.
"""

import os

import aws_cdk as cdk
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_s3_deployment as s3deploy
from constructs import Construct

_OPEN_NEXT_ASSETS = "frontend/.open-next/assets"


class FrontendStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        assets_bucket: s3.Bucket,
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
