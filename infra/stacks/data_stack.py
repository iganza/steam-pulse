"""DataStack — RDS + S3 assets bucket.

Receives vpc and intra_sg from NetworkStack as CDK objects.
termination_protection=True in production — never deleted by CDK.

Assets bucket has a deterministic name so other stacks can look it up
via from_bucket_name — no cross-stack CDK construct references needed.
"""

import aws_cdk as cdk
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_iam as iam
import aws_cdk.aws_rds as rds
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_secretsmanager as secretsmanager
import aws_cdk.aws_ssm as ssm
from constructs import Construct
from library_layer.config import SteamPulseConfig


class DataStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: SteamPulseConfig,
        vpc: ec2.IVpc,
        intra_sg: ec2.ISecurityGroup,
        nat_sg: ec2.ISecurityGroup,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        db_name = f"{config.ENVIRONMENT}_steampulse"
        isolated_subnets = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED)

        db_sg = ec2.SecurityGroup(self, "DbSg", vpc=vpc, description="RDS access")
        db_sg.add_ingress_rule(
            ec2.Peer.security_group_id(intra_sg.security_group_id),
            ec2.Port.tcp(5432),
            "Lambda to Postgres",
        )
        # Allow the NAT instance (SSM bastion) to reach RDS — enables db-tunnel.sh
        # for ops access in both envs. SSM session manager controls access; no ports
        # are opened to the internet.
        db_sg.add_ingress_rule(
            ec2.Peer.security_group_id(nat_sg.security_group_id),
            ec2.Port.tcp(5432),
            "NAT instance (SSM bastion) to Postgres",
        )

        env = config.ENVIRONMENT
        secret_name = f"steampulse/{env}/db-credentials"

        if config.is_production:
            # Production: secret is pre-created manually before deploy — CDK imports it.
            # Shape to pre-create: {"username": "postgres", "password": "..."}
            # RDS writes host/port/dbname/engine back into the secret after cluster creation.
            db_secret: secretsmanager.ISecret = secretsmanager.Secret.from_secret_name_v2(
                self,
                "DbSecret",
                secret_name,
            )
            # db.t4g.micro (Graviton2): ~$12/mo single-AZ, no cold-start latency.
            # 50 GB gp3 (~$5.75/mo) — sized for full catalog at 10k reviews/game cap (~26 GB used).
            # max_allocated_storage=500 enables RDS autoscaling if ever needed.
            # To increase manually: update allocated_storage and redeploy (in-place, no downtime).
            db_instance = rds.DatabaseInstance(
                self,
                "Db",
                engine=rds.DatabaseInstanceEngine.postgres(
                    version=rds.PostgresEngineVersion.VER_16_12,
                ),
                instance_type=ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.MICRO),
                credentials=rds.Credentials.from_secret(db_secret),
                vpc=vpc,
                vpc_subnets=isolated_subnets,
                security_groups=[db_sg],
                database_name=db_name,
                storage_type=rds.StorageType.GP3,
                allocated_storage=50,
                max_allocated_storage=100,
                deletion_protection=True,
                backup_retention=cdk.Duration.days(7),
                storage_encrypted=True,
                multi_az=False,
                removal_policy=cdk.RemovalPolicy.RETAIN,
            )
            db_endpoint: str = db_instance.db_instance_endpoint_address
            db_identifier = db_instance.instance_identifier
            cdk.Tags.of(db_instance).add("steampulse:service", "database")
            cdk.Tags.of(db_instance).add("steampulse:tier", "critical")
        else:
            # Staging: CDK owns and manages the secret (from_generated_secret).
            # The override_logical_id keeps it stable across pipeline vs direct deploys.
            # Aurora Serverless v2 (min=0 ACU): near-$0 when idle, scales on demand.
            db_cluster = rds.DatabaseCluster(
                self,
                "Db",
                engine=rds.DatabaseClusterEngine.aurora_postgres(
                    version=rds.AuroraPostgresEngineVersion.VER_16_4,
                ),
                credentials=rds.Credentials.from_generated_secret(
                    "postgres",
                    secret_name=secret_name,
                ),
                default_database_name=db_name,
                vpc=vpc,
                vpc_subnets=isolated_subnets,
                security_groups=[db_sg],
                deletion_protection=True,
                backup=rds.BackupProps(retention=cdk.Duration.days(1)),
                storage_encrypted=True,
                serverless_v2_min_capacity=0,
                serverless_v2_max_capacity=1,
                writer=rds.ClusterInstance.serverless_v2("Writer"),
                enable_data_api=True,
                removal_policy=cdk.RemovalPolicy.RETAIN,
            )
            db_secret = db_cluster.secret  # type: ignore[assignment]
            db_endpoint = db_cluster.cluster_endpoint.hostname
            db_identifier = db_cluster.cluster_identifier
            cdk.Tags.of(db_cluster).add("steampulse:service", "database")
            cdk.Tags.of(db_cluster).add("steampulse:tier", "critical")

            # Stable logical ID — matches the pipeline-created resource so CloudFormation
            # treats it as the same resource (not remove+add) on direct deploys.
            cfn_secret = db_cluster.node.find_child("Secret").node.default_child
            cfn_secret.override_logical_id(  # type: ignore[union-attr]
                "SteamPulsePipelineSteamPulseStagingDataDbSecret2839FCE63fdaad7efa858a3daf9490cf0a702aeb"
            )
            cfn_secret.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN  # type: ignore[union-attr]

        self.db_secret: secretsmanager.ISecret = db_secret

        # Exported so db-tunnel.sh can resolve the endpoint without extra AWS API calls.
        cdk.CfnOutput(self, "DbWriterEndpoint", value=db_endpoint)

        # ── S3 Assets Bucket ──────────────────────────────────────────────────
        # RETAIN — never deleted by CDK. Used by crawlers (archive) and frontend (static assets).
        # Deterministic name — spokes in other regions reference by name because
        # CDK tokens can't resolve cross-region.
        self.assets_bucket = s3.Bucket(
            self,
            "AssetsBucket",
            bucket_name=f"steampulse-assets-{env}",
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # Allow CloudFront OAC to read objects. Scoped to this account so
        # only distributions we own can access the bucket.  The policy lives
        # here (not DeliveryStack) because CDK can only manage policies on
        # the real bucket construct, not an imported reference.
        self.assets_bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AllowCloudFrontOac",
                actions=["s3:GetObject"],
                resources=[self.assets_bucket.arn_for_objects("*")],
                principals=[iam.ServicePrincipal("cloudfront.amazonaws.com")],
                conditions={
                    "StringEquals": {
                        "AWS:SourceAccount": cdk.Stack.of(self).account,
                    },
                },
            )
        )

        cdk.Tags.of(self.assets_bucket).add("steampulse:service", "database")
        cdk.Tags.of(self.assets_bucket).add("steampulse:tier", "critical")

        ssm.StringParameter(
            self,
            "AssetsBucketNameParam",
            parameter_name=f"/steampulse/{env}/data/assets-bucket-name",
            string_value=self.assets_bucket.bucket_name,
        )
        ssm.StringParameter(
            self,
            "DbIdentifierParam",
            parameter_name=f"/steampulse/{env}/data/db-instance-identifier",
            string_value=db_identifier,
        )
