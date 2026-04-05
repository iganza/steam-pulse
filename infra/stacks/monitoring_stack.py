"""Monitoring stack — dashboard + alarms via cdk-monitoring-constructs.

Discovers all resources via SSM parameters (no cross-stack CDK references).
SSM lookups are synthesized by CDK as CloudFormation parameters of type
AWS::SSM::Parameter::Value<String>, which CloudFormation resolves at deploy
time — no hard dependency on other stacks.

After deploying, subscribe your email to the alarm topic:
  aws sns subscribe --topic-arn <AlarmTopicArn output> \
      --protocol email --notification-endpoint you@example.com
"""

import aws_cdk as cdk
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_sns as sns
import aws_cdk.aws_sqs as sqs
import aws_cdk.aws_ssm as ssm
from aws_cdk.aws_cloudwatch import Metric, Stats
from cdk_monitoring_constructs import (
    AlarmFactoryDefaults,
    CustomMetricGroup,
    DefaultDashboardFactory,
    ErrorCountThreshold,
    LatencyThreshold,
    MaxMessageAgeThreshold,
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
        dims = {"environment": env}

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

        # ── SSM discovery — Lambda functions ──────────────────────────────────
        def _lookup_fn(param_suffix: str, construct_id: str) -> lambda_.IFunction:
            arn = ssm.StringParameter.value_for_string_parameter(
                self, f"/steampulse/{env}/compute/{param_suffix}"
            )
            return lambda_.Function.from_function_arn(self, construct_id, arn)

        def _lookup_queue(param_suffix: str, construct_id: str) -> sqs.IQueue:
            arn = ssm.StringParameter.value_for_string_parameter(
                self, f"/steampulse/{env}/messaging/{param_suffix}"
            )
            return sqs.Queue.from_queue_arn(self, construct_id, arn)

        crawler_fn = _lookup_fn("crawler-fn-arn", "CrawlerFnRef")
        ingest_fn = _lookup_fn("spoke-ingest-fn-arn", "IngestFnRef")
        api_fn = _lookup_fn("api-fn-arn", "ApiFnRef")
        frontend_fn = _lookup_fn("frontend-fn-arn", "FrontendFnRef")
        email_fn = _lookup_fn("email-fn-arn", "EmailFnRef")

        app_crawl_queue = _lookup_queue("app-crawl-queue-arn", "AppCrawlQueueRef")
        app_crawl_dlq = _lookup_queue("app-crawl-dlq-arn", "AppCrawlDlqRef")
        review_crawl_queue = _lookup_queue("review-crawl-queue-arn", "ReviewCrawlQueueRef")
        review_crawl_dlq = _lookup_queue("review-crawl-dlq-arn", "ReviewCrawlDlqRef")
        spoke_results_queue = _lookup_queue("spoke-results-queue-arn", "SpokeResultsQueueRef")
        spoke_results_dlq = _lookup_queue("spoke-results-dlq-arn", "SpokeResultsDlqRef")
        email_queue = _lookup_queue("email-queue-arn", "EmailQueueRef")
        email_dlq = _lookup_queue("email-dlq-arn", "EmailDlqRef")

        # ══════════════════════════════════════════════════════════════════════
        # Section 1: Crawler Pipeline
        # ══════════════════════════════════════════════════════════════════════
        monitoring.add_large_header("Crawler Pipeline")

        monitoring.monitor_lambda_function(
            lambda_function=crawler_fn,
            human_readable_name="Crawler",
            alarm_friendly_name="Crawler",
            add_fault_count_alarm={"CrawlerErrors": ErrorCountThreshold(max_error_count=0)},
            add_throttles_count_alarm={"CrawlerThrottles": ErrorCountThreshold(max_error_count=0)},
            add_latency_p99_alarm={
                "CrawlerP99": LatencyThreshold(max_latency=cdk.Duration.seconds(300)),
            },
        )

        monitoring.monitor_lambda_function(
            lambda_function=ingest_fn,
            human_readable_name="Spoke Ingest",
            alarm_friendly_name="SpokeIngest",
            add_fault_count_alarm={"IngestErrors": ErrorCountThreshold(max_error_count=0)},
            add_throttles_count_alarm={"IngestThrottles": ErrorCountThreshold(max_error_count=0)},
        )

        monitoring.monitor_sqs_queue_with_dlq(
            queue=app_crawl_queue,
            dead_letter_queue=app_crawl_dlq,
            human_readable_name="App Crawl Queue",
            alarm_friendly_name="AppCrawlQueue",
            add_queue_max_message_age_alarm={
                "AppCrawlAge": MaxMessageAgeThreshold(max_age_in_seconds=3600),
            },
            add_dead_letter_queue_max_size_alarm={
                "AppCrawlDlq": MaxMessageCountThreshold(max_message_count=0),
            },
        )

        monitoring.monitor_sqs_queue_with_dlq(
            queue=review_crawl_queue,
            dead_letter_queue=review_crawl_dlq,
            human_readable_name="Review Crawl Queue",
            alarm_friendly_name="ReviewCrawlQueue",
            add_queue_max_message_age_alarm={
                "ReviewCrawlAge": MaxMessageAgeThreshold(max_age_in_seconds=3600),
            },
            add_dead_letter_queue_max_size_alarm={
                "ReviewCrawlDlq": MaxMessageCountThreshold(max_message_count=0),
            },
        )

        monitoring.monitor_sqs_queue_with_dlq(
            queue=spoke_results_queue,
            dead_letter_queue=spoke_results_dlq,
            human_readable_name="Spoke Results Queue",
            alarm_friendly_name="SpokeResultsQueue",
            add_queue_max_message_age_alarm={
                "SpokeResultsAge": MaxMessageAgeThreshold(max_age_in_seconds=3600),
            },
            add_dead_letter_queue_max_size_alarm={
                "SpokeResultsDlq": MaxMessageCountThreshold(max_message_count=0),
            },
        )

        monitoring.monitor_custom(
            human_readable_name="Crawler Business Metrics",
            alarm_friendly_name="CrawlerBiz",
            metric_groups=[
                CustomMetricGroup(
                    title="Pipeline Throughput",
                    metrics=[
                        Metric(
                            namespace="SteamPulse",
                            metric_name=m,
                            dimensions_map=dims,
                            statistic=Stats.SUM,
                        )
                        for m in (
                            "SpokeDispatched",
                            "GamesUpserted",
                            "ReviewsUpserted",
                            "TagsIngested",
                            "CatalogRefreshRun",
                        )
                    ],
                ),
            ],
        )

        # ══════════════════════════════════════════════════════════════════════
        # Section 2: API & Frontend
        # ══════════════════════════════════════════════════════════════════════
        monitoring.add_large_header("API & Frontend")

        monitoring.monitor_lambda_function(
            lambda_function=api_fn,
            human_readable_name="API",
            alarm_friendly_name="Api",
            add_fault_count_alarm={"ApiErrors": ErrorCountThreshold(max_error_count=0)},
            add_throttles_count_alarm={"ApiThrottles": ErrorCountThreshold(max_error_count=0)},
            add_latency_p99_alarm={
                "ApiP99": LatencyThreshold(max_latency=cdk.Duration.seconds(10)),
            },
        )

        monitoring.monitor_lambda_function(
            lambda_function=frontend_fn,
            human_readable_name="Frontend SSR",
            alarm_friendly_name="Frontend",
            add_fault_count_alarm={"FrontendErrors": ErrorCountThreshold(max_error_count=0)},
            add_throttles_count_alarm={"FrontendThrottles": ErrorCountThreshold(max_error_count=0)},
        )

        # ══════════════════════════════════════════════════════════════════════
        # Section 3: Cross-Region Spoke Health
        # ══════════════════════════════════════════════════════════════════════
        monitoring.add_large_header("Cross-Region Spoke Health")

        # Per-region custom metrics (cross-region dashboard via Metric(region=r))
        for region in config.spoke_region_list:
            monitoring.monitor_custom(
                human_readable_name=f"Spoke {region}",
                alarm_friendly_name=f"Spoke-{region}",
                metric_groups=[
                    CustomMetricGroup(
                        title=f"{region} Fetches",
                        metrics=[
                            Metric(
                                namespace="SteamPulse",
                                metric_name=m,
                                dimensions_map=dims,
                                statistic=Stats.SUM,
                                region=region,
                            )
                            for m in ("MetadataFetched", "ReviewsFetched", "TagsFetched")
                        ],
                    ),
                    CustomMetricGroup(
                        title=f"{region} Queue Depth",
                        metrics=[
                            Metric(
                                namespace="AWS/SQS",
                                metric_name="ApproximateNumberOfMessagesVisible",
                                dimensions_map={
                                    "QueueName": f"steampulse-spoke-crawl-{region}-{env}",
                                },
                                statistic=Stats.MAXIMUM,
                                region=region,
                            ),
                        ],
                    ),
                ],
            )

        # Steam API health (aggregated across all spokes)
        monitoring.monitor_custom(
            human_readable_name="Steam API",
            alarm_friendly_name="SteamAPI",
            metric_groups=[
                CustomMetricGroup(
                    title="Requests & Errors",
                    metrics=[
                        Metric(
                            namespace="SteamPulse",
                            metric_name=m,
                            dimensions_map=dims,
                            statistic=Stats.SUM,
                        )
                        for m in ("SteamApiRequests", "SteamApiRetries", "SteamApiErrors")
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

        # ══════════════════════════════════════════════════════════════════════
        # Section 4: Supporting Services
        # ══════════════════════════════════════════════════════════════════════
        monitoring.add_large_header("Supporting Services")

        monitoring.monitor_lambda_function(
            lambda_function=email_fn,
            human_readable_name="Email",
            alarm_friendly_name="Email",
            add_fault_count_alarm={"EmailErrors": ErrorCountThreshold(max_error_count=0)},
        )

        monitoring.monitor_sqs_queue_with_dlq(
            queue=email_queue,
            dead_letter_queue=email_dlq,
            human_readable_name="Email Queue",
            alarm_friendly_name="EmailQueue",
            add_dead_letter_queue_max_size_alarm={
                "EmailDlq": MaxMessageCountThreshold(max_message_count=0),
            },
        )
