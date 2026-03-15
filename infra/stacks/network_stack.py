"""VPC with public and private subnets for RDS and Lambda."""

import aws_cdk as cdk
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_ssm as ssm
from constructs import Construct


class NetworkStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
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

        # Shared intra-VPC security group — assigned to all Lambda functions so
        # DataStack can grant a single known SG access to RDS instead of individual SGs.
        intra_sg = ec2.SecurityGroup(
            self,
            "IntraVpcSg",
            vpc=self.vpc,
            description="Shared intra-VPC SG for all Lambda functions",
            allow_all_outbound=True,
        )

        # Publish VPC attributes for consumer stacks via SSM
        ssm.StringParameter(
            self,
            "VpcIdParam",
            parameter_name=f"/steampulse/{stage}/network/vpc-id",
            string_value=self.vpc.vpc_id,
        )
        ssm.StringParameter(
            self,
            "VpcSgIdParam",
            parameter_name=f"/steampulse/{stage}/network/vpc-sg-id",
            string_value=intra_sg.security_group_id,
        )

        # TEMP: preserve private subnet exports so CloudFormation can update this stack
        # while the currently-deployed App/Analysis stacks still import them.
        # TODO: remove after next successful deploy (App/Analysis will use public subnets).
        if not is_production:
            cdk.CfnOutput(
                self,
                "ExportsOutputRefAppVpcPrivateSubnet1Subnet191FA232E8633931",
                value=self.vpc.private_subnets[0].subnet_id,
            )
            cdk.CfnOutput(
                self,
                "ExportsOutputRefAppVpcPrivateSubnet2Subnet9EA093CC75507AC6",
                value=self.vpc.private_subnets[1].subnet_id,
            )
