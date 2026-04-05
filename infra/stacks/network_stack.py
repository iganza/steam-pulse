"""NetworkStack — VPC, subnets, NAT (fck-nat), security groups.

Deployed once, rarely changed. Downstream stacks receive vpc and intra_sg
as direct CDK objects — no SSM lookups needed.

Non-production: single fck-nat t4g.nano instance (~$4/mo vs $32/mo managed NAT).
Production:     two fck-nat instances, one per AZ — auto-recovers in ~2 min.
                (~$8/mo vs ~$64/mo for two managed NAT Gateways).

Both environments use FckNatInstanceProvider (ASG-backed) for consistency.
nat_gateways=1 for staging means one instance in one AZ; =2 for prod places
one instance per AZ.
"""

import aws_cdk as cdk
import aws_cdk.aws_ec2 as ec2
from cdk_fck_nat import FckNatInstanceProvider
from constructs import Construct

from library_layer.config import SteamPulseConfig


class NetworkStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: SteamPulseConfig,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # FckNatInstanceProvider works for both envs — one ASG per NAT gateway.
        # Staging gets 1 instance; prod gets 2 (one per AZ) for HA.
        nat_gateways = 2 if config.is_production else 1
        nat_provider: ec2.NatProvider = FckNatInstanceProvider(
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.NANO),
        )

        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=nat_gateways,
            nat_gateway_provider=nat_provider,
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

        # fck-nat instances must accept inbound traffic from the entire VPC CIDR.
        # FckNatInstanceProvider exposes .security_group after VPC creation;
        # NatProvider base class doesn't declare it statically.
        nat_provider.security_group.add_ingress_rule(  # type: ignore[union-attr]
            ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            ec2.Port.all_traffic(),
            "Allow VPC traffic to reach NAT instance",
        )

        # Shared SG joined by all Lambda functions — grants DB access and allows
        # outbound internet egress via fck-nat.
        self.intra_sg = ec2.SecurityGroup(
            self,
            "IntraSg",
            vpc=self.vpc,
            description="Shared intra-VPC SG for Lambda functions",
            allow_all_outbound=True,
        )

        # Expose the NAT SG so DataStack can allow it into Aurora for SSM port-forwarding.
        # This lets devs tunnel to RDS via SSM without a separate bastion host.
        self.nat_sg: ec2.ISecurityGroup = nat_provider.security_group  # type: ignore[union-attr]
