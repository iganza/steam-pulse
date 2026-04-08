"""DeliveryStack — CloudFront distribution, Route53 (production).

Receives Lambda function URLs from ComputeStack. Looks up assets bucket by name.
Changes rarely — only when CloudFront routing, caching config, or domain setup changes.

Production: custom domain + ACM cert from CertificateStack (us-east-1).
            cross_region_references=True required to consume the cert.
Staging:    CloudFront default domain only — no ACM cert, no Route53.
"""

import aws_cdk as cdk
import aws_cdk.aws_certificatemanager as acm
import aws_cdk.aws_cloudfront as cloudfront
import aws_cdk.aws_cloudfront_origins as origins
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_route53 as route53
import aws_cdk.aws_route53_targets as route53_targets
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_ssm as ssm
from constructs import Construct

from library_layer.config import SteamPulseConfig

DOMAIN = "steampulse.io"


class DeliveryStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: SteamPulseConfig,
        api_fn_url: lambda_.FunctionUrl,
        frontend_fn_url: lambda_.FunctionUrl,
        certificate: acm.ICertificate | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(
            scope,
            construct_id,
            cross_region_references=config.is_production,
            **kwargs,
        )

        env = config.ENVIRONMENT

        # ── S3 Frontend Bucket ────────────────────────────────────────────────
        # Looked up by deterministic name — avoids cross-stack CDK construct
        # references that would create a Data ↔ Delivery cycle.
        # OAC bucket policy lives in DataStack (account-scoped).
        self.frontend_bucket = s3.Bucket.from_bucket_name(
            self,
            "FrontendBucket",
            f"steampulse-frontend-{env}",
        )

        oac = cloudfront.S3OriginAccessControl(self, "AssetsOac")
        s3_origin = origins.S3BucketOrigin.with_origin_access_control(
            self.frontend_bucket,
            origin_access_control=oac,
        )

        # ── Cache Policies ────────────────────────────────────────────────────
        html_cache_policy = cloudfront.CachePolicy(
            self,
            "HtmlCachePolicy",
            default_ttl=cdk.Duration.seconds(86_400),
            max_ttl=cdk.Duration.seconds(86_400 * 2),
            min_ttl=cdk.Duration.seconds(0),
            enable_accept_encoding_gzip=True,
            header_behavior=cloudfront.CacheHeaderBehavior.none(),
            cookie_behavior=cloudfront.CacheCookieBehavior.none(),
            query_string_behavior=cloudfront.CacheQueryStringBehavior.none(),
        )
        static_cache_policy = cloudfront.CachePolicy(
            self,
            "StaticCachePolicy",
            default_ttl=cdk.Duration.seconds(31_536_000),
            max_ttl=cdk.Duration.seconds(31_536_000),
            min_ttl=cdk.Duration.seconds(31_536_000),
            enable_accept_encoding_gzip=True,
        )

        # ── CloudFront ────────────────────────────────────────────────────────
        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.FunctionUrlOrigin(frontend_fn_url),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=html_cache_policy,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=origins.FunctionUrlOrigin(api_fn_url),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                ),
                "/_next/static/*": cloudfront.BehaviorOptions(
                    origin=s3_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=static_cache_policy,
                ),
                "/static/*": cloudfront.BehaviorOptions(
                    origin=s3_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=static_cache_policy,
                ),
            },
            domain_names=[DOMAIN, f"www.{DOMAIN}"] if config.is_production else None,
            certificate=certificate if config.is_production else None,
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            http_version=cloudfront.HttpVersion.HTTP2_AND_3,
        )

        # ── Route53 (production only, and only when domain-live=true) ────────
        domain_live: bool = bool(self.node.try_get_context("domain-live"))
        if config.is_production and domain_live:
            zone_id: str = self.node.try_get_context("hosted-zone-id") or ""
            hosted_zone = route53.HostedZone.from_hosted_zone_attributes(
                self,
                "HostedZone",
                hosted_zone_id=zone_id,
                zone_name=DOMAIN,
            )
            route53.ARecord(
                self,
                "ARecord",
                zone=hosted_zone,
                target=route53.RecordTarget.from_alias(
                    route53_targets.CloudFrontTarget(distribution),
                ),
            )
            route53.ARecord(
                self,
                "WwwRecord",
                record_name="www",
                zone=hosted_zone,
                target=route53.RecordTarget.from_alias(
                    route53_targets.CloudFrontTarget(distribution),
                ),
            )

        # CloudFront KVS for featured spots (Phase 5)
        self.kvs = cloudfront.KeyValueStore(self, "FeaturedKvs")

        # ── SSM outputs — ops tooling + pipeline CDN invalidation step ────────
        ssm.StringParameter(
            self,
            "DistributionIdParam",
            parameter_name=f"/steampulse/{env}/delivery/distribution-id",
            string_value=distribution.distribution_id,
        )
        ssm.StringParameter(
            self,
            "FrontendBucketNameParam",
            parameter_name=f"/steampulse/{env}/delivery/frontend-bucket-name",
            string_value=self.frontend_bucket.bucket_name,
        )
