"""App stack — FastAPI Lambda + Next.js SSR Lambda + CloudFront + Route53 + ACM + KVS."""

import os

import aws_cdk as cdk
import aws_cdk.aws_certificatemanager as acm
import aws_cdk.aws_cloudfront as cloudfront
import aws_cdk.aws_cloudfront_origins as origins
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_logs as logs
import aws_cdk.aws_route53 as route53
import aws_cdk.aws_route53_targets as route53_targets
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_ssm as ssm
from constructs import Construct

DOMAIN = "steampulse.io"

_PLACEHOLDER = "def handler(event, context): return {'statusCode': 200, 'headers': {'content-type': 'text/html'}, 'body': '<h1>Frontend not yet deployed</h1>'}"
_OPEN_NEXT_SERVER = "frontend/.open-next/server-functions/default"


class AppStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        is_production: bool = False,
        stage: str = "staging",
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, cross_region_references=True, **kwargs)

        # Deploy-time SSM references
        vpc_sg_id = ssm.StringParameter.value_for_string_parameter(
            self, f"/steampulse/{stage}/network/vpc-sg-id"
        )
        intra_sg = ec2.SecurityGroup.from_security_group_id(self, "IntraSg", vpc_sg_id)

        library_layer_arn = ssm.StringParameter.value_for_string_parameter(
            self, f"/steampulse/{stage}/common/library-layer-arn"
        )
        library_layer = lambda_.LayerVersion.from_layer_version_arn(
            self, "LibraryLayer", library_layer_arn
        )

        db_secret_arn = ssm.StringParameter.value_for_string_parameter(
            self, f"/steampulse/{stage}/data/db-secret-arn"
        )

        sfn_arn = ssm.StringParameter.value_for_string_parameter(
            self, f"/steampulse/{stage}/analysis/state-machine-arn"
        )

        # Route53 + ACM only wired up in production — staging uses CloudFront URL only
        hosted_zone = None
        cert = None
        if is_production:
            zone_id: str = self.node.try_get_context("hosted-zone-id") or ""
            hosted_zone = route53.HostedZone.from_hosted_zone_attributes(
                self,
                "HostedZone",
                hosted_zone_id=zone_id,
                zone_name=DOMAIN,
            )
            cert = acm.Certificate(
                self,
                "DomainCertificate",
                domain_name=DOMAIN,
                subject_alternative_names=[f"*.{DOMAIN}"],
                validation=acm.CertificateValidation.from_dns(hosted_zone),
            )

        # IAM role for FastAPI Lambda
        api_role = iam.Role(
            self,
            "ApiRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole"
                ),
            ],
        )
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
            resources=[db_secret_arn],
        ))

        # Allow Lambda to invoke Claude via Bedrock (no API key needed)
        api_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-3-5-haiku-20241022-v1:0",
                    f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0",
                ],
            )
        )

        # Allow API Lambda to start Step Functions executions
        api_role.add_to_policy(
            iam.PolicyStatement(
                actions=["states:StartExecution", "states:DescribeExecution"],
                resources=[sfn_arn],
            )
        )

        # FastAPI Lambda — standard Python runtime with shared library layer
        api_fn = lambda_.Function(
            self,
            "ApiFunction",
            function_name=f"{stage}-steampulse-api",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_functions.api.handler.handler",
            code=lambda_.Code.from_asset("src/lambda-functions"),
            layers=[library_layer],
            role=api_role,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS if is_production else ec2.SubnetType.PUBLIC
            ),
            allow_public_subnet=True,
            security_groups=[intra_sg],
            memory_size=512,
            timeout=cdk.Duration.seconds(30),
            environment={
                "DB_SECRET_ARN": db_secret_arn,
                "STEP_FUNCTIONS_ARN": sfn_arn,
                "PORT": "8080",
            },
        )

        # Lambda Function URL (no API Gateway)
        fn_url = api_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=["*"],
                allowed_methods=[lambda_.HttpMethod.ALL],
                allowed_headers=["*"],
            ),
        )

        # ── Next.js SSR Lambda ────────────────────────────────────────────────
        # Co-located with CloudFront in this stack to avoid cross-stack cycle.
        # FrontendStack only handles BucketDeployment (one-way dep: Frontend→App).
        if os.path.isdir(_OPEN_NEXT_SERVER):
            frontend_code = lambda_.Code.from_asset(_OPEN_NEXT_SERVER)
            frontend_handler = "index.handler"
            frontend_runtime = lambda_.Runtime.NODEJS_22_X
        else:
            frontend_code = lambda_.Code.from_inline(_PLACEHOLDER)
            frontend_handler = "index.handler"
            frontend_runtime = lambda_.Runtime.PYTHON_3_12

        frontend_log_group = logs.LogGroup(
            self,
            "FrontendFnLogs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        frontend_fn = lambda_.Function(
            self,
            "FrontendFn",
            runtime=frontend_runtime,
            handler=frontend_handler,
            code=frontend_code,
            memory_size=512,
            timeout=cdk.Duration.seconds(30),
            log_group=frontend_log_group,
            environment={"NODE_ENV": "production"},
        )
        frontend_url = frontend_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
        )
        frontend_origin = origins.FunctionUrlOrigin(frontend_url)

        # S3 bucket for static assets — created here to avoid cross-stack OAC cycle
        assets_bucket = s3.Bucket(
            self,
            "StaticAssetsBucket",
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        self.assets_bucket = assets_bucket

        # S3 Origin Access Control for static assets
        oac = cloudfront.S3OriginAccessControl(self, "AssetsOriginAccessControl")
        s3_origin = origins.S3BucketOrigin.with_origin_access_control(
            assets_bucket, origin_access_control=oac
        )

        # CloudFront KVS for featured spots (Phase 5)
        self.kvs = cloudfront.KeyValueStore(self, "FeaturedKvs")

        # Cache policies
        # API: no caching — use AWS managed policy (avoids gzip+no-cache conflict)
        api_cache_policy = cloudfront.CachePolicy.CACHING_DISABLED

        html_cache_policy = cloudfront.CachePolicy(
            self,
            "HtmlCachePolicy",
            default_ttl=cdk.Duration.seconds(86400),
            max_ttl=cdk.Duration.seconds(86400 * 2),
            min_ttl=cdk.Duration.seconds(0),
            enable_accept_encoding_gzip=True,
            header_behavior=cloudfront.CacheHeaderBehavior.none(),
            cookie_behavior=cloudfront.CacheCookieBehavior.none(),
            query_string_behavior=cloudfront.CacheQueryStringBehavior.none(),
        )

        static_cache_policy = cloudfront.CachePolicy(
            self,
            "StaticCachePolicy",
            default_ttl=cdk.Duration.seconds(31536000),
            max_ttl=cdk.Duration.seconds(31536000),
            min_ttl=cdk.Duration.seconds(31536000),
            enable_accept_encoding_gzip=True,
        )

        api_lambda_origin = origins.FunctionUrlOrigin(fn_url)

        # CloudFront distribution — all origins in this stack, no cross-stack cycle
        self.distribution = cloudfront.Distribution(
            self,
            "CloudFrontDistribution",
            # Default behaviour: Next.js SSR
            default_behavior=cloudfront.BehaviorOptions(
                origin=frontend_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=html_cache_policy,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
            ),
            additional_behaviors={
                # FastAPI backend
                "/api/*": cloudfront.BehaviorOptions(
                    origin=api_lambda_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=api_cache_policy,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                ),
                # Next.js hashed static files — served from S3, cached forever
                "/_next/static/*": cloudfront.BehaviorOptions(
                    origin=s3_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=static_cache_policy,
                ),
                # Other static assets (public folder)
                "/static/*": cloudfront.BehaviorOptions(
                    origin=s3_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=static_cache_policy,
                ),
            },
            domain_names=[DOMAIN, f"www.{DOMAIN}"] if is_production else None,
            certificate=cert if is_production else None,
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            http_version=cloudfront.HttpVersion.HTTP2_AND_3,
        )

        # Route53 A records — production only (staging uses CloudFront URL)
        if is_production and hosted_zone:
            route53.ARecord(
                self,
                "AliasRecord",
                zone=hosted_zone,
                target=route53.RecordTarget.from_alias(
                    route53_targets.CloudFrontTarget(self.distribution)
                ),
            )
            route53.ARecord(
                self,
                "WwwAliasRecord",
                record_name="www",
                zone=hosted_zone,
                target=route53.RecordTarget.from_alias(
                    route53_targets.CloudFrontTarget(self.distribution)
                ),
            )

        # Publish for monitoring and other consumers
        ssm.StringParameter(
            self,
            "DistributionIdParam",
            parameter_name=f"/steampulse/{stage}/app/distribution-id",
            string_value=self.distribution.distribution_id,
        )
        ssm.StringParameter(
            self,
            "FunctionUrlParam",
            parameter_name=f"/steampulse/{stage}/app/function-url",
            string_value=fn_url.url,
        )

        self.api_fn = api_fn
        self.fn_url = fn_url
