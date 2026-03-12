"""Data stack — RDS PostgreSQL + S3. Always termination_protection=True."""

import aws_cdk as cdk
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_rds as rds
import aws_cdk.aws_secretsmanager as secretsmanager
from constructs import Construct


class DataStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.Vpc,
        **kwargs: object,
    ) -> None:
        # termination_protection is always True for this stack
        kwargs["termination_protection"] = True
        super().__init__(scope, construct_id, **kwargs)

        # RDS security group
        db_sg = ec2.SecurityGroup(self, "DbSg", vpc=vpc, description="RDS access")

        # RDS PostgreSQL — t3.micro, Secret auto-generated
        db = rds.DatabaseInstance(
            self,
            "Postgres",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_16_3
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T3, ec2.InstanceSize.MICRO
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            security_groups=[db_sg],
            database_name="steampulse",
            deletion_protection=True,
            backup_retention=cdk.Duration.days(7),
            storage_encrypted=True,
            multi_az=False,
        )

        # Expose secret and security group for other stacks
        self.db_secret: secretsmanager.ISecret = db.secret  # type: ignore[assignment]
        self.db_sg = db_sg
