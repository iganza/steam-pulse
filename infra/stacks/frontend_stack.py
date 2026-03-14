"""Frontend stack — Next.js via OpenNext on Lambda, with static assets in S3.

Architecture (open-next v3):
  - S3 bucket (owned by AppStack) serves /_next/static/* via CloudFront
  - BucketDeployment uploads .open-next/assets/ to that S3 bucket
  - Lambda handles SSR from .open-next/server-functions/default/
  - FrontendStack adds /* CloudFront behaviour → Lambda

NOTE: app_distribution is passed directly (not SSM-imported) because
cloudfront.Distribution.from_distribution_attributes() returns IDistribution which
throws "Cannot add behaviors to an imported distribution" when add_behavior() is called.

NOTE: assets_bucket is owned by AppStack (same stack as CloudFront) to avoid a
cross-stack cyclic reference (App↔Frontend) that would occur if the S3 origin and the
CloudFront behaviours lived in different stacks.
"""

import os

import aws_cdk as cdk
import aws_cdk.aws_cloudfront as cloudfront
import aws_cdk.aws_cloudfront_origins as origins
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_logs as logs
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_s3_deployment as s3deploy
from constructs import Construct

_PLACEHOLDER = "def handler(event, context): return {'statusCode': 200, 'body': 'Frontend not yet deployed'}"
_OPEN_NEXT_SERVER = "frontend/.open-next/server-functions/default"
_OPEN_NEXT_ASSETS = "frontend/.open-next/assets"


class FrontendStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        app_distribution: cloudfront.Distribution,
        assets_bucket: s3.Bucket,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        frontend_built = os.path.isdir(_OPEN_NEXT_SERVER)

        # Upload built Next.js static assets to S3 (served via CloudFront /_next/static/*)
        if frontend_built and os.path.isdir(_OPEN_NEXT_ASSETS):
            s3deploy.BucketDeployment(
                self,
                "AssetsDeployment",
                sources=[s3deploy.Source.asset(_OPEN_NEXT_ASSETS)],
                destination_bucket=assets_bucket,
                prune=True,
            )

        # SSR Lambda — use open-next bundle when built, inline placeholder otherwise
        if frontend_built:
            code = lambda_.Code.from_asset(_OPEN_NEXT_SERVER)
            handler = "index.handler"
            runtime = lambda_.Runtime.NODEJS_22_X
        else:
            code = lambda_.Code.from_inline(_PLACEHOLDER)
            handler = "index.handler"
            runtime = lambda_.Runtime.PYTHON_3_12

        frontend_log_group = logs.LogGroup(
            self,
            "FrontendFnLogs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        frontend_fn = lambda_.Function(
            self,
            "FrontendFn",
            runtime=runtime,
            handler=handler,
            code=code,
            memory_size=512,
            timeout=cdk.Duration.seconds(30),
            log_group=frontend_log_group,
            environment={"NODE_ENV": "production"},
        )

        fn_url = frontend_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
        )
        lambda_origin = origins.FunctionUrlOrigin(fn_url)

        html_cache = cloudfront.CachePolicy(
            self,
            "FrontendHtmlCache",
            default_ttl=cdk.Duration.seconds(86400),
            max_ttl=cdk.Duration.seconds(86400 * 2),
            min_ttl=cdk.Duration.seconds(0),
            enable_accept_encoding_gzip=True,
            header_behavior=cloudfront.CacheHeaderBehavior.none(),
            cookie_behavior=cloudfront.CacheCookieBehavior.none(),
            query_string_behavior=cloudfront.CacheQueryStringBehavior.none(),
        )

        # SSR catch-all — lower priority than /_next/static/* (defined in AppStack)
        app_distribution.add_behavior(
            "/*",
            lambda_origin,
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            cache_policy=html_cache,
            origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
        )
