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
from stacks.crawler_stack import CrawlerStack
from stacks.data_stack import DataStack
from stacks.frontend_stack import FrontendStack
from stacks.monitoring_stack import MonitoringStack
from stacks.network_stack import NetworkStack


class ApplicationStage(cdk.Stage):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env = cdk.Environment(account=self.account, region=self.region)
        is_production = construct_id == "Production"
        # DB name only — CDK handles all other resource naming automatically
        db_name = f"{construct_id.lower()}_steampulse"

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
            env=env,
        )

        crawler = CrawlerStack(
            self,
            "Crawler",
            vpc=network.vpc,
            db_secret=data.db_secret,
            sfn_arn=analysis.state_machine_arn,
            env=env,
        )

        app = AppStack(
            self,
            "App",
            vpc=network.vpc,
            db_secret=data.db_secret,
            sfn_arn=analysis.state_machine_arn,
            is_production=(construct_id == "Production"),
            env=env,
        )

        FrontendStack(
            self,
            "Frontend",
            app_distribution=app.distribution,
            env=env,
        )

        MonitoringStack(
            self,
            "Monitoring",
            api_fn=app.api_fn,
            app_crawler_fn=crawler.app_crawler_fn,
            review_crawler_fn=crawler.review_crawler_fn,
            app_queue=crawler.app_queue,
            review_queue=crawler.review_queue,
            app_dlq=crawler.app_dlq,
            review_dlq=crawler.review_dlq,
            state_machine=analysis.state_machine,
            env=env,
        )
