"""CertificateStack — ACM TLS certificate in us-east-1.

CloudFront requires certificates to be in us-east-1 regardless of where
the distribution or origin resources live. This stack MUST be deployed with
env.region="us-east-1". DeliveryStack references self.certificate using
cross_region_references=True.

Production only — staging uses the CloudFront default domain (no custom cert).
"""

import aws_cdk as cdk
import aws_cdk.aws_certificatemanager as acm
import aws_cdk.aws_route53 as route53
from constructs import Construct

from library_layer.config import SteamPulseConfig

DOMAIN = "steampulse.io"


class CertificateStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: SteamPulseConfig,
        **kwargs: object,
    ) -> None:
        # cross_region_references=True required so DeliveryStack (us-west-2)
        # can consume self.certificate via SSM-backed custom resource.
        super().__init__(scope, construct_id, cross_region_references=True, **kwargs)

        zone_id: str = self.node.try_get_context("hosted-zone-id") or ""
        hosted_zone = route53.HostedZone.from_hosted_zone_attributes(
            self,
            "HostedZone",
            hosted_zone_id=zone_id,
            zone_name=DOMAIN,
        )

        self.certificate = acm.Certificate(
            self,
            "Cert",
            domain_name=DOMAIN,
            subject_alternative_names=[f"*.{DOMAIN}"],
            validation=acm.CertificateValidation.from_dns(hosted_zone),
        )
