"""Monitoring stack — dashboard + alarms via cdk-monitoring-constructs.

Creates an SNS topic you can subscribe to for alarm notifications.
After deploying, subscribe your email:
  aws sns subscribe --topic-arn <AlarmTopicArn output> \
      --protocol email --notification-endpoint you@example.com
"""

import aws_cdk as cdk
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_sns as sns
import aws_cdk.aws_sqs as sqs
import aws_cdk.aws_stepfunctions as sfn
from cdk_monitoring_constructs import (
    AlarmFactoryDefaults,
    ErrorCountThreshold,
    MaxMessageCountThreshold,
    MonitoringFacade,
    SnsAlarmActionStrategy,
)
from constructs import Construct


class MonitoringStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        api_fn: lambda_.IFunction,
        app_crawler_fn: lambda_.IFunction,
        review_crawler_fn: lambda_.IFunction,
        app_queue: sqs.IQueue,
        review_queue: sqs.IQueue,
        app_dlq: sqs.IQueue,
        review_dlq: sqs.IQueue,
        state_machine: sfn.IStateMachine,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # SNS topic — subscribe via console or CLI after deploy
        self.alarm_topic = sns.Topic(
            self,
            "AlarmTopic",
            display_name="SteamPulse Alarms",
        )

        cdk.CfnOutput(
            self,
            "AlarmTopicArn",
            value=self.alarm_topic.topic_arn,
            description="Subscribe to this topic to receive alarm notifications",
        )

        monitoring = MonitoringFacade(
            self,
            "Facade",
            alarm_factory_defaults=AlarmFactoryDefaults(
                actions_enabled=True,
                alarm_name_prefix="SteamPulse",
                action=SnsAlarmActionStrategy(on_alarm_topic=self.alarm_topic),
            ),
        )

        # FastAPI Lambda — fault count (errors) + throttles
        monitoring.monitor_lambda_function(
            lambda_function=api_fn,
            human_readable_name="API (FastAPI)",
            add_fault_count_alarm={
                "Critical": ErrorCountThreshold(max_error_count=5),
            },
            add_throttles_count_alarm={
                "Warning": ErrorCountThreshold(max_error_count=10),
            },
        )

        # App crawler Lambda
        monitoring.monitor_lambda_function(
            lambda_function=app_crawler_fn,
            human_readable_name="App Crawler",
            add_fault_count_alarm={
                "Warning": ErrorCountThreshold(max_error_count=10),
            },
        )

        # Review crawler Lambda
        monitoring.monitor_lambda_function(
            lambda_function=review_crawler_fn,
            human_readable_name="Review Crawler",
            add_fault_count_alarm={
                "Warning": ErrorCountThreshold(max_error_count=10),
            },
        )

        # DLQs — any message landing here is a failure worth waking up for
        monitoring.monitor_sqs_queue(
            queue=app_dlq,
            human_readable_name="App Crawl DLQ",
            add_queue_max_size_alarm={
                "Critical": MaxMessageCountThreshold(max_message_count=1),
            },
        )

        monitoring.monitor_sqs_queue(
            queue=review_dlq,
            human_readable_name="Review Crawl DLQ",
            add_queue_max_size_alarm={
                "Critical": MaxMessageCountThreshold(max_message_count=1),
            },
        )

        # Crawl queues — depth + message age visibility (no alarms, just dashboard)
        monitoring.monitor_sqs_queue(
            queue=app_queue,
            human_readable_name="App Crawl Queue",
        )

        monitoring.monitor_sqs_queue(
            queue=review_queue,
            human_readable_name="Review Crawl Queue",
        )

        # Step Functions analysis pipeline
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
