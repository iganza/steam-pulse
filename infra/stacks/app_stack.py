"""App stack — FastAPI Lambda (container) + CloudFront + Route53 + ACM + KVS."""

import aws_cdk as cdk
import aws_cdk.aws_certificatemanager as acm
import aws_cdk.aws_cloudfront as cloudfront
import aws_cdk.aws_cloudfront_origins as origins
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_route53 as route53
import aws_cdk.aws_route53_targets as route53_targets
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_secretsmanager as secretsmanager
from constructs import Construct

DOMAIN = "steampulse.io"


class AppStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.Vpc,
        db_secret: secretsmanager.ISecret,
        sfn_arn: str,
        is_production: bool = False,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, cross_region_references=True, **kwargs)

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
        db_secret.grant_read(api_role)

        # Allow API Lambda to start Step Functions executions
        if sfn_arn:
            api_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["states:StartExecution", "states:DescribeExecution"],
                    resources=[sfn_arn],
                )
            )

        # FastAPI Lambda — container image from repo root Dockerfile
        api_fn = lambda_.DockerImageFunction(
            self,
            "ApiFunction",
            code=lambda_.DockerImageCode.from_image_asset(
                ".",
                file="Dockerfile",
            ),
            role=api_role,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            memory_size=512,
            timeout=cdk.Duration.seconds(30),
            environment={
                "DB_SECRET_ARN": db_secret.secret_arn,
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

        # Lambda Function URL origin
        lambda_origin = origins.FunctionUrlOrigin(fn_url)

        # CloudFront distribution
        self.distribution = cloudfront.Distribution(
            self,
            "CloudFrontDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=lambda_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=html_cache_policy,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=lambda_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=api_cache_policy,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                ),
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

        # Expose for other stacks
        self.api_fn = api_fn
        self.fn_url = fn_url
