"""ApplicationStage — all stacks in dependency order.

The CDK stage name ("Staging", "Production") is automatically prepended to all
CloudFormation stack names and CDK-generated resource names. The only place we
derive a custom prefix is the PostgreSQL database name (e.g. staging_steampulse,
production_steampulse), since that's a DB identifier not a CDK resource name.

Cross-stack coupling uses direct CDK object references. CDK auto-generates
CfnOutput/Fn::ImportValue pairs and infers deployment order from the reference
graph — no add_dependency() calls or SSM tokens needed for stack wiring.

FrontendStack only uploads static assets (BucketDeployment → AppStack's S3 bucket).
The SSR Lambda and all CloudFront behaviors live in AppStack to avoid cross-stack
cyclic references.
"""

import aws_cdk as cdk
from constructs import Construct

from stacks.analysis_stack import AnalysisStack
from stacks.app_stack import AppStack
from stacks.common_stack import CommonStack
from stacks.data_stack import DataStack
from stacks.frontend_stack import FrontendStack
from stacks.lambda_stack import LambdaStack
# from stacks.monitoring_stack import MonitoringStack
from stacks.network_stack import NetworkStack
from stacks.sqs_stack import SqsStack


class ApplicationStage(cdk.Stage):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env = cdk.Environment(account=self.account, region=self.region)
        is_production = stage == "production"
        db_name = f"{stage}_steampulse"

        # NetworkStack: writes /steampulse/{stage}/network/vpc-id (for Vpc.from_lookup())
        network = NetworkStack(
            self, "Network",
            stage=stage,
            is_production=is_production,
            env=env,
        )

        # DataStack: vpc and intra_sg passed directly
        # Writes /steampulse/{stage}/data/db-sg-id for ops lookup
        data = DataStack(
            self, "Data",
            vpc=network.vpc,
            stage=stage,
            db_name=db_name,
            is_production=is_production,
            env=env,
        )

        # CommonStack: exposes self.library_layer directly
        common_stack = CommonStack(self, "Common", stage=stage, env=env)

        # SqsStack: exposes self.app_crawl_queue and self.review_crawl_queue directly
        sqs_stack = SqsStack(self, "Sqs", stage=stage, env=env)

        # AnalysisStack: receives intra_sg, db_secret, library_layer as direct refs
        # Exposes self.state_machine directly
        analysis = AnalysisStack(
            self, "Analysis",
            vpc=network.vpc,
            intra_sg=network.intra_sg,
            db_secret=data.db_secret,
            library_layer=common_stack.library_layer,
            stage=stage,
            is_production=is_production,
            env=env,
        )

        # AppStack: receives all deps as direct refs
        # Writes /steampulse/{stage}/app/distribution-id, function-url, assets-bucket-name
        app = AppStack(
            self, "App",
            vpc=network.vpc,
            intra_sg=network.intra_sg,
            db_secret=data.db_secret,
            library_layer=common_stack.library_layer,
            state_machine=analysis.state_machine,
            is_production=is_production,
            stage=stage,
            env=env,
        )

        # LambdaStack: receives all deps as direct refs; CDK infers full dep order
        LambdaStack(
            self, "Lambda",
            vpc=network.vpc,
            intra_sg=network.intra_sg,
            db_secret=data.db_secret,
            library_layer=common_stack.library_layer,
            app_crawl_queue=sqs_stack.app_crawl_queue,
            review_crawl_queue=sqs_stack.review_crawl_queue,
            state_machine=analysis.state_machine,
            assets_bucket=app.assets_bucket,
            is_production=is_production,
            stage=stage,
            env=env,
        )

        # FrontendStack: only uploads static assets to S3.
        # SSR Lambda + CloudFront behaviors live in AppStack to avoid cross-stack cycle.
        FrontendStack(
            self, "Frontend",
            stage=stage,
            assets_bucket=app.assets_bucket,
            env=env,
        )

        # MonitoringStack disabled until all Lambdas are stable and deployed
        # MonitoringStack(
        #     self,
        #     "Monitoring",
        #     stage=stage,
        #     env=env,
        # )
