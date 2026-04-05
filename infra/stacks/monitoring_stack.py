"""Monitoring stack — dashboard + alarms via cdk-monitoring-constructs.

Intentionally dependency-free: no SSM lookups, no cross-stack resource imports.
Custom metrics in the SteamPulse namespace are queried by name only — no ARNs needed.

Deploy independently (never through the pipeline):
  poetry run cdk deploy SteamPulse-Staging-Monitoring

After deploying, subscribe your email to the alarm topic:
  aws sns subscribe --topic-arn <AlarmTopicArn output> \\
      --protocol email --notification-endpoint you@example.com
"""

import aws_cdk as cdk
import aws_cdk.aws_sns as sns
from aws_cdk.aws_cloudwatch import Metric, Stats
from cdk_monitoring_constructs import (
    AlarmFactoryDefaults,
    CustomMetricGroup,
    DefaultDashboardFactory,
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

        # ── SNS alarm topic ───────────────────────────────────────────────────
        self.alarm_topic = sns.Topic(
            self,
            "AlarmTopic",
            display_name=f"SteamPulse {env.capitalize()} Alarms",
        )

        cdk.CfnOutput(
            self,
            "AlarmTopicArn",
            value=self.alarm_topic.topic_arn,
            description="Subscribe to this topic to receive alarm notifications",
        )

        # ── Monitoring facade ─────────────────────────────────────────────────
        monitoring = MonitoringFacade(
            self,
            "Facade",
            dashboard_factory=DefaultDashboardFactory(
                self,
                "DashboardFactory",
                dashboard_name_prefix=f"SteamPulse-{env.capitalize()}",
            ),
            alarm_factory_defaults=AlarmFactoryDefaults(
                actions_enabled=True,
                alarm_name_prefix=f"SteamPulse-{env.capitalize()}",
                action=SnsAlarmActionStrategy(on_alarm_topic=self.alarm_topic),
            ),
        )

        # ── Steam API custom metrics ──────────────────────────────────────────
        dims = {"environment": env}

        monitoring.monitor_custom(
            human_readable_name="Steam API",
            alarm_friendly_name="SteamAPI",
            metric_groups=[
                CustomMetricGroup(
                    title="Requests & Throttles",
                    metrics=[
                        Metric(
                            namespace="SteamPulse",
                            metric_name="SteamApiRequests",
                            dimensions_map=dims,
                            statistic=Stats.SUM,
                        ),
                        Metric(
                            namespace="SteamPulse",
                            metric_name="SteamApiRetries",
                            dimensions_map=dims,
                            statistic=Stats.SUM,
                        ),
                        Metric(
                            namespace="SteamPulse",
                            metric_name="SteamApiErrors",
                            dimensions_map=dims,
                            statistic=Stats.SUM,
                        ),
                    ],
                ),
                CustomMetricGroup(
                    title="Latency (p99)",
                    metrics=[
                        Metric(
                            namespace="SteamPulse",
                            metric_name="SteamApiLatency",
                            dimensions_map=dims,
                            statistic=Stats.percentile(99),
                        ),
                    ],
                ),
            ],
        )
