# CDK Python Best Practices for Full-Stack Infrastructure

## Recommended Project Structure

```
my-app/
├── app.py
├── cdk.json
├── requirements.txt
├── stacks/
│   ├── __init__.py
│   ├── frontend_stack.py
│   ├── backend_stack.py
│   ├── database_stack.py
│   └── network_stack.py
└── constructs/
    ├── __init__.py
    ├── api_construct.py
    └── database_construct.py
```

---

## `app.py` - Entry Point

```python
import aws_cdk as cdk
from stacks.network_stack import NetworkStack
from stacks.database_stack import DatabaseStack
from stacks.backend_stack import BackendStack
from stacks.frontend_stack import FrontendStack

app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account"),
    region=app.node.try_get_context("region"),
)

# Order matters - dependencies flow downward
network_stack = NetworkStack(app, "NetworkStack", env=env)

database_stack = DatabaseStack(
    app, "DatabaseStack",
    vpc=network_stack.vpc,
    env=env
)

backend_stack = BackendStack(
    app, "BackendStack",
    vpc=network_stack.vpc,
    database=database_stack.database,
    env=env
)

frontend_stack = FrontendStack(
    app, "FrontendStack",
    api_url=backend_stack.function_url,  # or API GW url
    env=env
)

# Explicit dependency declaration
backend_stack.add_dependency(database_stack)
frontend_stack.add_dependency(backend_stack)

app.synth()
```

---

## `stacks/network_stack.py`

```python
from aws_cdk import Stack
import aws_cdk.aws_ec2 as ec2
from constructs import Construct

class NetworkStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        self.vpc = ec2.Vpc(
            self, "AppVpc",
            max_azs=2,
            nat_gateways=1,  # Cost-conscious default; use 2+ for prod
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    name="Isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24
                ),
            ]
        )
```

---

## `stacks/database_stack.py`

```python
from aws_cdk import Stack, RemovalPolicy, Duration
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_rds as rds
from constructs import Construct

class DatabaseStack(Stack):
    def __init__(self, scope: Construct, id: str, vpc: ec2.Vpc, **kwargs):
        super().__init__(scope, id, **kwargs)

        # Security group - only allow inbound from VPC
        self.db_security_group = ec2.SecurityGroup(
            self, "DbSecurityGroup",
            vpc=vpc,
            description="RDS Security Group",
            allow_all_outbound=False
        )

        # Aurora Serverless v2 is current best practice for Lambda workloads
        self.database = rds.DatabaseCluster(
            self, "Database",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_15_3
            ),
            serverless_v2_min_capacity=0.5,
            serverless_v2_max_capacity=4,
            writer=rds.ClusterInstance.serverless_v2("writer"),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            security_groups=[self.db_security_group],
            removal_policy=RemovalPolicy.SNAPSHOT,  # DESTROY for dev
        )
```

---

## `stacks/backend_stack.py`

```python
from aws_cdk import Stack, Duration
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_apigatewayv2 as apigwv2
import aws_cdk.aws_rds as rds
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration
from constructs import Construct

class BackendStack(Stack):
    def __init__(
        self,
        scope: Construct,
        id: str,
        vpc: ec2.Vpc,
        database: rds.DatabaseCluster,
        **kwargs
    ):
        super().__init__(scope, id, **kwargs)

        # Lambda security group
        lambda_sg = ec2.SecurityGroup(
            self, "LambdaSG",
            vpc=vpc,
            description="Lambda Security Group"
        )

        # Allow Lambda -> RDS
        database.connections.allow_from(
            lambda_sg,
            ec2.Port.tcp(5432),
            "Allow Lambda to connect to RDS"
        )

        # Lambda function (inside VPC)
        self.backend_lambda = lambda_.Function(
            self, "BackendFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=lambda_.Code.from_asset("lambda/backend"),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[lambda_sg],
            timeout=Duration.seconds(30),
            # Use config.to_lambda_env() — no inline ARNs/URLs.
            # Infrastructure values are SSM param names resolved at runtime.
            environment=config.to_lambda_env(
                POWERTOOLS_SERVICE_NAME="backend",
            ),
        )

        # Grant Lambda access to DB secret
        database.secret.grant_read(self.backend_lambda)

        # HTTP API Gateway (v2) - cheaper and simpler than REST API
        self.api = apigwv2.HttpApi(
            self, "HttpApi",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=["*"],  # Lock down in prod
                allow_methods=[apigwv2.CorsHttpMethod.ANY],
                allow_headers=["*"],
            )
        )

        self.api.add_routes(
            path="/{proxy+}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=HttpLambdaIntegration(
                "BackendIntegration", self.backend_lambda
            )
        )

        # Expose API URL for frontend
        self.api_url = self.api.url
```

---

## `stacks/frontend_stack.py`

```python
from aws_cdk import Stack, RemovalPolicy, CfnOutput
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_cloudfront as cloudfront
import aws_cdk.aws_cloudfront_origins as origins
import aws_cdk.aws_lambda as lambda_
from constructs import Construct

class FrontendStack(Stack):
    def __init__(
        self,
        scope: Construct,
        id: str,
        api_url: str,
        **kwargs
    ):
        super().__init__(scope, id, **kwargs)

        # S3 bucket for static assets (no public access - CloudFront only)
        bucket = s3.Bucket(
            self, "FrontendBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
        )

        # Lambda@Edge or CloudFront Function for request manipulation
        cf_function = cloudfront.Function(
            self, "RewriteFunction",
            code=cloudfront.FunctionCode.from_inline("""
                function handler(event) {
                    var request = event.request;
                    if (!request.uri.includes('.')) {
                        request.uri = '/index.html';
                    }
                    return request;
                }
            """)
        )

        # OAC is current best practice (replaces OAI)
        oac = cloudfront.S3OriginAccessControl(self, "OAC")

        # Strip the trailing slash and https:// from api_url for origin
        api_domain = api_url.replace("https://", "").rstrip("/")

        distribution = cloudfront.Distribution(
            self, "Distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(
                    bucket,
                    origin_access_control=oac
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=cf_function,
                        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST
                    )
                ]
            ),
            additional_behaviors={
                # Route /api/* to Lambda via API Gateway
                "/api/*": cloudfront.BehaviorOptions(
                    origin=origins.HttpOrigin(
                        api_domain,
                        protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
                    ),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                )
            },
            default_root_object="index.html",
        )

        CfnOutput(self, "DistributionUrl",
            value=f"https://{distribution.distribution_domain_name}"
        )
```

---

## Key Best Practices Summary

| Concern | Best Practice |
|---|---|
| **Stack separation** | Split by lifecycle/team ownership, not just service |
| **Database** | Aurora Serverless v2 for Lambda workloads |
| **S3 access** | OAC (Origin Access Control) over legacy OAI |
| **API** | HTTP API v2 (cheaper) unless you need REST API features |
| **Secrets** | RDS auto-generates secret; grant via IAM, not hardcoding |
| **Lambda in VPC** | Use `PRIVATE_WITH_EGRESS` subnets (needs NAT) |
| **DB subnet** | Use `PRIVATE_ISOLATED` (no internet access needed) |
| **Removal policy** | `SNAPSHOT` for prod databases, `DESTROY` for dev |
| **CF routing** | Use path behaviors to split static vs API traffic |
