"""ApplicationStage — all stacks in dependency order.

The CDK stage name ("Staging", "Production") is automatically prepended to all
CloudFormation stack names and CDK-generated resource names. The only place we
derive a custom prefix is the PostgreSQL database name (e.g. staging_steampulse,
production_steampulse), since that's a DB identifier not a CDK resource name.
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

        network = NetworkStack(self, "Network", env=env)

        data = DataStack(
            self,
            "Data",
            vpc=network.vpc,
            db_name=db_name,
            is_production=is_production,
            env=env,
        )

        analysis = AnalysisStack(
            self,
            "Analysis",
            vpc=network.vpc,
            db_secret=data.db_secret,
            stage=stage,
            env=env,
        )

        common_stack = CommonStack(self, "Common", env=env)

        sqs_stack = SqsStack(self, "Sqs", stage=stage, env=env)

        lambda_stack = LambdaStack(
            self,
            "Lambda",
            library_layer=common_stack.library_layer,
            app_queue=sqs_stack.app_crawl_queue,
            review_queue=sqs_stack.review_crawl_queue,
            vpc=network.vpc,
            db_secret=data.db_secret,
            sfn_arn=analysis.state_machine_arn,
            is_production=is_production,
            stage=stage,
            env=env,
        )
        lambda_stack.add_dependency(common_stack)
        lambda_stack.add_dependency(sqs_stack)

        app = AppStack(
            self,
            "App",
            vpc=network.vpc,
            db_secret=data.db_secret,
            sfn_arn=analysis.state_machine_arn,
            library_layer=common_stack.library_layer,
            is_production=is_production,
            stage=stage,
            env=env,
        )
        app.add_dependency(common_stack)

        FrontendStack(
            self,
            "Frontend",
            app_distribution=app.distribution,
            env=env,
        )

        # MonitoringStack disabled until all Lambdas are stable and deployed
        # MonitoringStack(
        #     self,
        #     "Monitoring",
        #     stage=stage,
        #     env=env,
        # )
