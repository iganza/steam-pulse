"""Monitoring stack — CloudWatch alarms and dashboard."""

import aws_cdk as cdk
import aws_cdk.aws_cloudwatch as cloudwatch
from constructs import Construct


class MonitoringStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Dashboard — widgets added by other stacks via add_widgets()
        self.dashboard = cloudwatch.Dashboard(
            self,
            "Dashboard",
            dashboard_name=None,  # CDK-generated name
        )

        # Placeholder alarm — 5XX errors from Lambda (will be wired to real metric in Phase 4)
        error_alarm = cloudwatch.Alarm(
            self,
            "HighErrorRate",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Errors",
                statistic="Sum",
                period=cdk.Duration.minutes(5),
            ),
            threshold=10,
            evaluation_periods=2,
            alarm_description="Lambda error rate too high",
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        self.dashboard.add_widgets(
            cloudwatch.AlarmWidget(
                title="Lambda Errors",
                alarm=error_alarm,
            )
        )
