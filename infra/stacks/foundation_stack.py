"""FoundationStack — VPC, security groups, and RDS.

Deployed once and rarely changed. Exposes vpc, intra_sg, and db_secret as
public attributes so ApplicationStage can pass them directly to BackendStack
— no SSM lookups, no resolve: tokens, no dummy-value guards needed.
"""

import aws_cdk as cdk
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_rds as rds
import aws_cdk.aws_secretsmanager as secretsmanager
from constructs import Construct

from library_layer.config import SteamPulseConfig


class FoundationStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: SteamPulseConfig,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env = config.ENVIRONMENT
        db_name = f"{env}_steampulse"

        # ── VPC ───────────────────────────────────────────────────────────────
        # Non-production: no NAT gateway (~$32/mo saved). Lambdas use public subnets.
        # Production: NAT gateway keeps Lambdas in private subnets.
        self.vpc = ec2.Vpc(
            self, "Vpc",
            max_azs=2,
            nat_gateways=1 if config.is_production else 0,
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

        # ── Security groups ───────────────────────────────────────────────────
        # BackendStack Lambdas join intra_sg to reach the DB.
        self.intra_sg = ec2.SecurityGroup(
            self, "IntraSg",
            vpc=self.vpc,
            description="Shared intra-VPC SG for Lambda functions",
            allow_all_outbound=True,
        )

        db_sg = ec2.SecurityGroup(self, "DbSg", vpc=self.vpc, description="RDS access")
        db_sg.add_ingress_rule(
            ec2.Peer.security_group_id(self.intra_sg.security_group_id),
            ec2.Port.tcp(5432),
            "Lambda to Postgres",
        )

        # ── Database ──────────────────────────────────────────────────────────
        # Production: RDS t3.micro — ~$15/month, predictable cost.
        # Non-production: Aurora Serverless v2 (min=0) — near $0 when idle.
        isolated_subnets = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED)

        if config.is_production:
            db_instance = rds.DatabaseInstance(
                self, "Db",
                engine=rds.DatabaseInstanceEngine.postgres(
                    version=rds.PostgresEngineVersion.VER_16_3,
                ),
                instance_type=ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MICRO),
                vpc=self.vpc,
                vpc_subnets=isolated_subnets,
                security_groups=[db_sg],
                database_name=db_name,
                deletion_protection=True,
                backup_retention=cdk.Duration.days(7),
                storage_encrypted=True,
                multi_az=False,
                removal_policy=cdk.RemovalPolicy.RETAIN,
            )
            db_secret: secretsmanager.ISecret = db_instance.secret  # type: ignore[assignment]
        else:
            db_cluster = rds.DatabaseCluster(
                self, "Db",
                engine=rds.DatabaseClusterEngine.aurora_postgres(
                    version=rds.AuroraPostgresEngineVersion.VER_16_4,
                ),
                default_database_name=db_name,
                vpc=self.vpc,
                vpc_subnets=isolated_subnets,
                security_groups=[db_sg],
                deletion_protection=True,
                backup=rds.BackupProps(retention=cdk.Duration.days(1)),
                storage_encrypted=True,
                serverless_v2_min_capacity=0,
                serverless_v2_max_capacity=1,
                writer=rds.ClusterInstance.serverless_v2("Writer"),
                removal_policy=cdk.RemovalPolicy.RETAIN,
            )
            db_secret = db_cluster.secret  # type: ignore[assignment]

        self.db_secret: secretsmanager.ISecret = db_secret
