"""Data stack — RDS PostgreSQL (prod) or Aurora Serverless v2 (staging).

Production: RDS t3.micro — $15/month flat, predictable cost for steady traffic.
Staging: Aurora Serverless v2 with pause — scales to zero when idle, ~$0-2/month.
Always termination_protection=True.
"""

import aws_cdk as cdk
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_rds as rds
import aws_cdk.aws_secretsmanager as secretsmanager
import aws_cdk.aws_ssm as ssm
from constructs import Construct


class DataStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        stage: str,
        db_name: str = "steampulse",
        is_production: bool = False,
        **kwargs: object,
    ) -> None:
        kwargs["termination_protection"] = True
        super().__init__(scope, construct_id, **kwargs)

        db_sg = ec2.SecurityGroup(self, "DatabaseSecurityGroup", vpc=vpc, description="RDS access")
        self.db_sg = db_sg
        # Allow all traffic within the VPC to reach Postgres on 5432.
        # Using VPC CIDR avoids SSM token limitations in SourceSecurityGroupId.
        db_sg.add_ingress_rule(
            ec2.Peer.ipv4(vpc.vpc_cidr_block),
            ec2.Port.tcp(5432),
            "Allow intra-VPC traffic to reach Postgres",
        )

        subnet_selection = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED)
        engine = rds.DatabaseClusterEngine.aurora_postgres(
            version=rds.AuroraPostgresEngineVersion.VER_16_4
        )

        if is_production:
            # Fixed cost ~$15/month — cheaper than Aurora for steady traffic
            db_instance = rds.DatabaseInstance(
                self,
                "PostgresInstance",
                engine=rds.DatabaseInstanceEngine.postgres(
                    version=rds.PostgresEngineVersion.VER_16_3
                ),
                instance_type=ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MICRO),
                vpc=vpc,
                vpc_subnets=subnet_selection,
                security_groups=[db_sg],
                database_name=db_name,
                deletion_protection=True,
                backup_retention=cdk.Duration.days(7),
                storage_encrypted=True,
                multi_az=False,
            )
            self.db_secret: secretsmanager.ISecret = db_instance.secret  # type: ignore[assignment]
        else:
            # Aurora Serverless v2 — pauses when idle, near $0 for staging
            db_cluster = rds.DatabaseCluster(
                self,
                "AuroraServerlessCluster",
                engine=engine,
                default_database_name=db_name,
                vpc=vpc,
                vpc_subnets=subnet_selection,
                security_groups=[db_sg],
                deletion_protection=True,
                backup=rds.BackupProps(retention=cdk.Duration.days(1)),
                storage_encrypted=True,
                serverless_v2_min_capacity=0,   # scale to zero (pause)
                serverless_v2_max_capacity=1,   # hard cap ~$44/month max
                writer=rds.ClusterInstance.serverless_v2("Writer"),
            )
            self.db_secret = db_cluster.secret  # type: ignore[assignment]

        # db-sg-id kept for operational lookup (ops/debugging)
        ssm.StringParameter(
            self,
            "DbSgIdParam",
            parameter_name=f"/steampulse/{stage}/data/db-sg-id",
            string_value=db_sg.security_group_id,
        )
