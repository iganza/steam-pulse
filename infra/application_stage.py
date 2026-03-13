"""ApplicationStage — all stacks in dependency order.

The CDK stage name ("Staging", "Production") is automatically prepended to all
CloudFormation stack names and CDK-generated resource names. The only place we
derive a custom prefix is the PostgreSQL database name (e.g. staging_steampulse,
production_steampulse), since that's a DB identifier not a CDK resource name.

Cross-stack coupling is eliminated via SSM Parameter Store:
  - Producer stacks write to /steampulse/{stage}/{resource}
  - Consumer stacks read via value_for_string_parameter() (deploy-time CF token)
    except vpc-id which uses value_from_lookup() (synth-time, needed for Vpc.from_lookup())
  - add_dependency() calls enforce CloudFormation deployment order since CDK can no
    longer infer it from direct object references.

Exception: FrontendStack still receives app.distribution directly because
cloudfront.Distribution.from_distribution_attributes() returns IDistribution which
throws "Cannot add behaviors to an imported distribution".
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

        # NetworkStack: writes /steampulse/{stage}/network/vpc-id and vpc-sg-id
        network = NetworkStack(
            self, "Network",
            stage=stage,
            is_production=is_production,
            env=env,
        )

        # DataStack: vpc passed directly (synth-time object); reads vpc-sg-id from SSM (deploy-time)
        # Writes /steampulse/{stage}/data/db-secret-arn and db-sg-id
        data = DataStack(
            self, "Data",
            vpc=network.vpc,
            stage=stage,
            db_name=db_name,
            is_production=is_production,
            env=env,
        )
        data.add_dependency(network)

        # CommonStack: writes /steampulse/{stage}/common/library-layer-arn
        common_stack = CommonStack(self, "Common", stage=stage, env=env)

        # SqsStack: writes /steampulse/{stage}/sqs/{queue}-arn and review-crawl-queue-url
        sqs_stack = SqsStack(self, "Sqs", stage=stage, env=env)

        # AnalysisStack: vpc passed directly; reads db-secret-arn and vpc-sg-id from SSM
        # Writes /steampulse/{stage}/analysis/state-machine-arn
        analysis = AnalysisStack(self, "Analysis", vpc=network.vpc, stage=stage, env=env)
        analysis.add_dependency(network)
        analysis.add_dependency(data)

        # LambdaStack: vpc passed directly; reads all other resources from SSM
        lambda_stack = LambdaStack(
            self, "Lambda",
            vpc=network.vpc,
            is_production=is_production,
            stage=stage,
            env=env,
        )
        lambda_stack.add_dependency(network)
        lambda_stack.add_dependency(common_stack)
        lambda_stack.add_dependency(sqs_stack)
        lambda_stack.add_dependency(analysis)
        lambda_stack.add_dependency(data)

        # AppStack: vpc passed directly; reads library_layer, db_secret, sfn_arn from SSM
        # Writes /steampulse/{stage}/app/distribution-id and function-url
        app = AppStack(
            self, "App",
            vpc=network.vpc,
            is_production=is_production,
            stage=stage,
            env=env,
        )
        app.add_dependency(network)
        app.add_dependency(common_stack)
        app.add_dependency(data)
        app.add_dependency(analysis)

        # FrontendStack: receives app.distribution directly (CDK add_behavior() limitation).
        # The FunctionUrl cross-stack reference enforces App→Frontend deploy order.
        frontend = FrontendStack(
            self, "Frontend",
            stage=stage,
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
