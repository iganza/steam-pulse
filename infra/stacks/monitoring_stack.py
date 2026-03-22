"""Monitoring stack — dashboard + alarms via cdk-monitoring-constructs.

Resources are referenced via SSM parameter ARNs (no Fn::ImportValue) so this
stack can be updated or deleted independently of ComputeStack and MessagingStack.

After deploying, subscribe your email to the alarm topic:
  aws sns subscribe --topic-arn <AlarmTopicArn output> \
      --protocol email --notification-endpoint you@example.com
"""

import aws_cdk as cdk
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_sns as sns
import aws_cdk.aws_sqs as sqs
import aws_cdk.aws_ssm as ssm
import aws_cdk.aws_stepfunctions as sfn
from cdk_monitoring_constructs import (
    AlarmFactoryDefaults,
    ErrorCountThreshold,
    MaxMessageCountThreshold,
    MonitoringFacade,
    SnsAlarmActionStrategy,
)
from constructs import Construct

from library_layer.config import SteamPulseConfig


class MonitoringStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: SteamPulseConfig,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env = config.ENVIRONMENT

        def _ssm(name: str) -> str:
            return ssm.StringParameter.value_for_string_parameter(self, name)

        # ── Resource references via SSM (CloudFormation {{resolve:ssm:...}}) ──
        api_fn = lambda_.Function.from_function_arn(
            self, "ApiFunction",
            _ssm(f"/steampulse/{env}/compute/api-fn-arn"),
        )
        crawler_fn = lambda_.Function.from_function_arn(
            self, "CrawlerFunction",
            _ssm(f"/steampulse/{env}/compute/crawler-fn-arn"),
        )
        analysis_fn = lambda_.Function.from_function_arn(
            self, "AnalysisFunction",
            _ssm(f"/steampulse/{env}/compute/analysis-fn-arn"),
        )
        state_machine = sfn.StateMachine.from_state_machine_arn(
            self, "AnalysisMachine",
            _ssm(f"/steampulse/{env}/compute/sfn-arn"),
        )
        app_queue = sqs.Queue.from_queue_arn(
            self, "AppCrawlQueue",
            _ssm(f"/steampulse/{env}/messaging/app-crawl-queue-arn"),
        )
        review_queue = sqs.Queue.from_queue_arn(
            self, "ReviewCrawlQueue",
            _ssm(f"/steampulse/{env}/messaging/review-crawl-queue-arn"),
        )
        app_dlq = sqs.Queue.from_queue_arn(
            self, "AppCrawlDlq",
            _ssm(f"/steampulse/{env}/messaging/app-crawl-dlq-arn"),
        )
        review_dlq = sqs.Queue.from_queue_arn(
            self, "ReviewCrawlDlq",
            _ssm(f"/steampulse/{env}/messaging/review-crawl-dlq-arn"),
        )

        # ── SNS alarm topic ───────────────────────────────────────────────────
        self.alarm_topic = sns.Topic(
            self, "AlarmTopic",
            display_name="SteamPulse Alarms",
        )

        cdk.CfnOutput(
            self, "AlarmTopicArn",
            value=self.alarm_topic.topic_arn,
            description="Subscribe to this topic to receive alarm notifications",
        )

        # ── Monitoring facade ─────────────────────────────────────────────────
        monitoring = MonitoringFacade(
            self, "Facade",
            alarm_factory_defaults=AlarmFactoryDefaults(
                actions_enabled=True,
                alarm_name_prefix="SteamPulse",
                action=SnsAlarmActionStrategy(on_alarm_topic=self.alarm_topic),
            ),
        )

        monitoring.monitor_lambda_function(
            lambda_function=api_fn,
            human_readable_name="API (FastAPI)",
            add_fault_count_alarm={"Critical": ErrorCountThreshold(max_error_count=5)},
            add_throttles_count_alarm={"Warning": ErrorCountThreshold(max_error_count=10)},
        )

        monitoring.monitor_lambda_function(
            lambda_function=crawler_fn,
            human_readable_name="Crawler",
            add_fault_count_alarm={"Warning": ErrorCountThreshold(max_error_count=10)},
        )

        monitoring.monitor_lambda_function(
            lambda_function=analysis_fn,
            human_readable_name="Analysis",
            add_fault_count_alarm={"Warning": ErrorCountThreshold(max_error_count=5)},
        )

        monitoring.monitor_sqs_queue(
            queue=app_dlq,
            human_readable_name="App Crawl DLQ",
            add_queue_max_size_alarm={"Critical": MaxMessageCountThreshold(max_message_count=1)},
        )

        monitoring.monitor_sqs_queue(
            queue=review_dlq,
            human_readable_name="Review Crawl DLQ",
            add_queue_max_size_alarm={"Critical": MaxMessageCountThreshold(max_message_count=1)},
        )

        monitoring.monitor_sqs_queue(
            queue=app_queue,
            human_readable_name="App Crawl Queue",
        )

        monitoring.monitor_sqs_queue(
            queue=review_queue,
            human_readable_name="Review Crawl Queue",
        )

        monitoring.monitor_step_function(
            state_machine=state_machine,
            human_readable_name="Analysis Pipeline",
            add_failed_execution_count_alarm={
                "Critical": ErrorCountThreshold(max_error_count=3),
            },
            add_timed_out_execution_count_alarm={
                "Warning": ErrorCountThreshold(max_error_count=1),
            },
        )
