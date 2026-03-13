"""VPC with public and private subnets for RDS and Lambda."""

import aws_cdk as cdk
import aws_cdk.aws_ec2 as ec2
from constructs import Construct


class NetworkStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        is_production: bool = False,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Staging: no NAT gateway (saves ~$32/mo). Lambdas use public subnets
        # for internet access (Steam API calls). RDS stays in isolated subnets.
        # Production: NAT gateway keeps Lambdas in private subnets.
        self.is_production = is_production

        self.vpc = ec2.Vpc(
            self,
            "AppVpc",
            max_azs=2,
            nat_gateways=1 if is_production else 0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
            ],
        )
