"""Frontend stack — Next.js via OpenNext on Lambda, added as CloudFront behaviour.

Phase 4 builds the Next.js app and produces frontend/.open-next/.
Until then this stack registers the CloudFront behaviour with a placeholder Lambda.

NOTE: app_distribution is kept as a direct CDK object (not SSM-imported) because
cloudfront.Distribution.from_distribution_attributes() returns IDistribution which
throws "Cannot add behaviors to an imported distribution" when add_behavior() is called.
"""

import os

import aws_cdk as cdk
import aws_cdk.aws_cloudfront as cloudfront
import aws_cdk.aws_cloudfront_origins as origins
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_logs as logs
from constructs import Construct

_PLACEHOLDER = "def handler(event, context): return {'statusCode': 200, 'body': 'Frontend not yet deployed'}"
_OPEN_NEXT_SERVER = "frontend/.open-next/server-functions/default"


class FrontendStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        app_distribution: cloudfront.Distribution,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Use OpenNext server bundle when built, inline placeholder otherwise
        if os.path.isdir(_OPEN_NEXT_SERVER):
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
        )

        fn_url = frontend_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
        )

        frontend_origin = origins.FunctionUrlOrigin(fn_url)

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

        # Add /* behaviour to existing distribution (lower priority than /api/*)
        app_distribution.add_behavior(
            "/*",
            frontend_origin,
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            cache_policy=html_cache,
            origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
        )
