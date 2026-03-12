"""ApplicationStage — all production stacks in dependency order."""

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

        account = self.account
        region = self.region
        env = cdk.Environment(account=account, region=region)

        network = NetworkStack(self, "Network", env=env)

        data = DataStack(
            self,
            "Data",
            vpc=network.vpc,
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
            env=env,
        )

        FrontendStack(
            self,
            "Frontend",
            app_distribution=app.distribution,
            env=env,
        )

        MonitoringStack(self, "Monitoring", env=env)
