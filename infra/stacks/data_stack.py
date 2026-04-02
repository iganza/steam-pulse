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
        if not config.is_production:
            # Allow the NAT instance to reach RDS/Postgres in non-production only — enables SSM
            # port-forwarding for dev/ops access without opening this path in production.
            db_sg.add_ingress_rule(
                ec2.Peer.security_group_id(nat_sg.security_group_id),
                ec2.Port.tcp(5432),
                "NAT instance (SSM bastion) to Postgres",
            )

        env = config.ENVIRONMENT
        secret_name = f"steampulse/{env}/db-credentials"

        if config.is_production:
            # t3.micro: ~$15/mo, predictable cost, no cold-start latency.
            db_instance = rds.DatabaseInstance(
                self, "Db",
                engine=rds.DatabaseInstanceEngine.postgres(
                    version=rds.PostgresEngineVersion.VER_16_3,
                ),
                instance_type=ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MICRO),
                credentials=rds.Credentials.from_generated_secret(
                    "postgres",
                    secret_name=secret_name,
                ),
                vpc=vpc,
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
            db_endpoint: str = db_instance.db_instance_endpoint_address
        else:
            # Aurora Serverless v2 (min=0 ACU): near-$0 when idle, scales on demand.
            db_cluster = rds.DatabaseCluster(
                self, "Db",
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

            # The secret was originally created by the CDK Pipeline stack, giving it a
            # pipeline-prefixed logical ID. Override to match so CloudFormation treats it
            # as the same resource (not remove+add) on direct deploys.
            cfn_secret = db_cluster.node.find_child("Secret").node.default_child
            cfn_secret.override_logical_id(  # type: ignore[union-attr]
                "SteamPulsePipelineSteamPulseStagingDataDbSecret2839FCE63fdaad7efa858a3daf9490cf0a702aeb"
            )
            # Step 1 of secret migration: ensure physical secret survives if ever removed
            # from this stack (prerequisite for switching to from_secret_name_v2).
            cfn_secret.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN  # type: ignore[union-attr]

        self.db_secret: secretsmanager.ISecret = db_secret

        # Exported so db-tunnel.sh can resolve the endpoint without extra AWS API calls.
        cdk.CfnOutput(self, "DbWriterEndpoint", value=db_endpoint)

        # ── S3 Assets Bucket ──────────────────────────────────────────────────
        # RETAIN — never deleted by CDK. Used by crawlers (archive) and frontend (static assets).
        # Deterministic name — spokes in other regions reference by name because
        # CDK tokens can't resolve cross-region.
        self.assets_bucket = s3.Bucket(
            self, "AssetsBucket",
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

        ssm.StringParameter(
            self, "AssetsBucketNameParam",
            parameter_name=f"/steampulse/{env}/data/assets-bucket-name",
            string_value=self.assets_bucket.bucket_name,
        )
