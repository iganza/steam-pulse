"""Monitoring stack — dashboard + alarms (CloudWatch primitives, free-tier compact).

Discovers all resources via SSM parameters (no cross-stack CDK references).
SSM lookups are synthesized by CDK as CloudFormation parameters of type
AWS::SSM::Parameter::Value<String>, which CloudFormation resolves at deploy
time — no hard dependency on other stacks.

The dashboard is hand-rolled rather than driven by `MonitoringFacade` so
the metric count stays under the 50/dashboard free-tier cap.

After deploying, subscribe your email to the alarm topic:
  aws sns subscribe --topic-arn <AlarmTopicArn output> \
      --protocol email --notification-endpoint you@example.com
"""

import aws_cdk as cdk
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_sns as sns
import aws_cdk.aws_sqs as sqs
import aws_cdk.aws_ssm as ssm
from aws_cdk.aws_cloudwatch import (
    Alarm,
    ComparisonOperator,
    Dashboard,
    GraphWidget,
    Metric,
    PeriodOverride,
    Stats,
    TextWidget,
    TreatMissingData,
)
from aws_cdk.aws_cloudwatch_actions import SnsAction
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
        env_cap = env.capitalize()
        custom_dims = {"environment": env}

        # ── SNS alarm topic ───────────────────────────────────────────────────
        self.alarm_topic = sns.Topic(
            self,
            "AlarmTopic",
            display_name=f"SteamPulse {env_cap} Alarms",
        )
        cdk.CfnOutput(
            self,
            "AlarmTopicArn",
            value=self.alarm_topic.topic_arn,
            description="Subscribe to this topic to receive alarm notifications",
        )
        sns_action = SnsAction(self.alarm_topic)

        # ── SSM discovery — Lambda functions and queues ──────────────────────
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

        app_crawl_queue = _lookup_queue("app-crawl-queue-arn", "AppCrawlQueueRef")
        app_crawl_dlq = _lookup_queue("app-crawl-dlq-arn", "AppCrawlDlqRef")
        review_crawl_queue = _lookup_queue("review-crawl-queue-arn", "ReviewCrawlQueueRef")
        review_crawl_dlq = _lookup_queue("review-crawl-dlq-arn", "ReviewCrawlDlqRef")
        spoke_results_queue = _lookup_queue("spoke-results-queue-arn", "SpokeResultsQueueRef")
        spoke_results_dlq = _lookup_queue("spoke-results-dlq-arn", "SpokeResultsDlqRef")
        email_queue = _lookup_queue("email-queue-arn", "EmailQueueRef")
        email_dlq = _lookup_queue("email-dlq-arn", "EmailDlqRef")

        # ── Helpers ──────────────────────────────────────────────────────────
        def _lambda_metric(fn: lambda_.IFunction, name: str, stat: str = Stats.SUM) -> Metric:
            return Metric(
                namespace="AWS/Lambda",
                metric_name=name,
                dimensions_map={"FunctionName": fn.function_name},
                statistic=stat,
            )

        def _sqs_metric(queue: sqs.IQueue, name: str, stat: str = Stats.MAXIMUM) -> Metric:
            return Metric(
                namespace="AWS/SQS",
                metric_name=name,
                dimensions_map={"QueueName": queue.queue_name},
                statistic=stat,
            )

        def _lambda_alarms(
            fn: lambda_.IFunction,
            *,
            name_prefix: str,
            errors_construct_id: str,
            throttles_construct_id: str,
            p99_seconds: int | None = None,
            p99_construct_id: str | None = None,
        ) -> None:
            errors_alarm = Alarm(
                self,
                errors_construct_id,
                alarm_name=f"SteamPulse-{env_cap}-{name_prefix}-Errors",
                metric=_lambda_metric(fn, "Errors"),
                threshold=0,
                comparison_operator=ComparisonOperator.GREATER_THAN_THRESHOLD,
                evaluation_periods=1,
                treat_missing_data=TreatMissingData.NOT_BREACHING,
            )
            errors_alarm.add_alarm_action(sns_action)
            throttles_alarm = Alarm(
                self,
                throttles_construct_id,
                alarm_name=f"SteamPulse-{env_cap}-{name_prefix}-Throttles",
                metric=_lambda_metric(fn, "Throttles"),
                threshold=0,
                comparison_operator=ComparisonOperator.GREATER_THAN_THRESHOLD,
                evaluation_periods=1,
                treat_missing_data=TreatMissingData.NOT_BREACHING,
            )
            throttles_alarm.add_alarm_action(sns_action)
            if p99_seconds is not None and p99_construct_id is not None:
                p99_alarm = Alarm(
                    self,
                    p99_construct_id,
                    alarm_name=f"SteamPulse-{env_cap}-{name_prefix}-P99",
                    metric=_lambda_metric(fn, "Duration", Stats.percentile(99)),
                    threshold=p99_seconds * 1000,
                    comparison_operator=ComparisonOperator.GREATER_THAN_THRESHOLD,
                    evaluation_periods=3,
                    treat_missing_data=TreatMissingData.NOT_BREACHING,
                )
                p99_alarm.add_alarm_action(sns_action)

        def _sqs_alarms(
            *,
            queue: sqs.IQueue | None,
            dlq: sqs.IQueue,
            name_prefix: str,
            age_construct_id: str | None = None,
            dlq_construct_id: str,
            age_seconds: int = 3600,
        ) -> None:
            if queue is not None and age_construct_id is not None:
                age_alarm = Alarm(
                    self,
                    age_construct_id,
                    alarm_name=f"SteamPulse-{env_cap}-{name_prefix}-Age",
                    metric=_sqs_metric(queue, "ApproximateAgeOfOldestMessage"),
                    threshold=age_seconds,
                    comparison_operator=ComparisonOperator.GREATER_THAN_THRESHOLD,
                    evaluation_periods=2,
                    treat_missing_data=TreatMissingData.NOT_BREACHING,
                )
                age_alarm.add_alarm_action(sns_action)
            dlq_alarm = Alarm(
                self,
                dlq_construct_id,
                alarm_name=f"SteamPulse-{env_cap}-{name_prefix}-Dlq",
                metric=_sqs_metric(dlq, "ApproximateNumberOfMessagesVisible"),
                threshold=0,
                comparison_operator=ComparisonOperator.GREATER_THAN_THRESHOLD,
                evaluation_periods=1,
                treat_missing_data=TreatMissingData.NOT_BREACHING,
            )
            dlq_alarm.add_alarm_action(sns_action)

        # ── Alarms (do not count toward dashboard metric cap) ────────────────
        _lambda_alarms(
            crawler_fn,
            name_prefix="Crawler",
            errors_construct_id="CrawlerErrorsAlarm",
            throttles_construct_id="CrawlerThrottlesAlarm",
            p99_seconds=300,
            p99_construct_id="CrawlerP99Alarm",
        )
        _lambda_alarms(
            ingest_fn,
            name_prefix="SpokeIngest",
            errors_construct_id="IngestErrorsAlarm",
            throttles_construct_id="IngestThrottlesAlarm",
        )
        _lambda_alarms(
            api_fn,
            name_prefix="Api",
            errors_construct_id="ApiErrorsAlarm",
            throttles_construct_id="ApiThrottlesAlarm",
            p99_seconds=10,
            p99_construct_id="ApiP99Alarm",
        )
        _lambda_alarms(
            frontend_fn,
            name_prefix="Frontend",
            errors_construct_id="FrontendErrorsAlarm",
            throttles_construct_id="FrontendThrottlesAlarm",
        )

        _sqs_alarms(
            queue=app_crawl_queue,
            dlq=app_crawl_dlq,
            name_prefix="AppCrawl",
            age_construct_id="AppCrawlAgeAlarm",
            dlq_construct_id="AppCrawlDlqAlarm",
        )
        _sqs_alarms(
            queue=review_crawl_queue,
            dlq=review_crawl_dlq,
            name_prefix="ReviewCrawl",
            age_construct_id="ReviewCrawlAgeAlarm",
            dlq_construct_id="ReviewCrawlDlqAlarm",
        )
        _sqs_alarms(
            queue=spoke_results_queue,
            dlq=spoke_results_dlq,
            name_prefix="SpokeResults",
            age_construct_id="SpokeResultsAgeAlarm",
            dlq_construct_id="SpokeResultsDlqAlarm",
        )
        _sqs_alarms(
            queue=None,
            dlq=email_dlq,
            name_prefix="Email",
            dlq_construct_id="EmailDlqAlarm",
        )

        # Heartbeat alarm — TreatMissingData=BREACHING is essential because
        # a crashed scheduled run emits no metric at all; without this we'd
        # silently lose all new-game discovery.
        catalog_heartbeat_alarm = Alarm(
            self,
            "CatalogRefreshHeartbeat",
            alarm_name=f"SteamPulse-{env_cap}-Crawler-Catalog-Refresh-Heartbeat",
            alarm_description=(
                "Catalog refresh has not completed successfully in the last 2 hours. "
                f"New games are not being enqueued. Check /steampulse/{env}/crawler "
                "logs for timeouts or errors."
            ),
            metric=Metric(
                namespace="SteamPulse",
                metric_name="CatalogRefreshRun",
                dimensions_map=custom_dims,
                statistic=Stats.SUM,
                period=cdk.Duration.hours(1),
            ),
            threshold=1,
            comparison_operator=ComparisonOperator.LESS_THAN_THRESHOLD,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            treat_missing_data=TreatMissingData.BREACHING,
        )
        catalog_heartbeat_alarm.add_alarm_action(sns_action)

        # ── Dashboard (compact: one row of widgets per concern) ──────────────
        # Total widgets: 4 lambda traffic + 2 lambda latency + 4 SQS depth +
        # 1 catalog heartbeat = 11 metric widgets. Total metric expressions:
        # 4·3 (lambda errors/throttles/invocations) + 2·1 (p99 latency) +
        # 4·2 (queue + DLQ depth) + 1 (heartbeat) = 23. Well under the 50
        # free-tier cap.
        def _lambda_traffic(fn: lambda_.IFunction, title: str) -> GraphWidget:
            return GraphWidget(
                title=f"{title} — Invocations / Errors / Throttles",
                width=12,
                height=6,
                left=[
                    _lambda_metric(fn, "Invocations"),
                    _lambda_metric(fn, "Errors"),
                    _lambda_metric(fn, "Throttles"),
                ],
            )

        def _lambda_p99(fn: lambda_.IFunction, title: str) -> GraphWidget:
            return GraphWidget(
                title=f"{title} — Duration p99 (ms)",
                width=12,
                height=6,
                left=[_lambda_metric(fn, "Duration", Stats.percentile(99))],
            )

        def _queue_depth(queue: sqs.IQueue, dlq: sqs.IQueue, title: str) -> GraphWidget:
            return GraphWidget(
                title=f"{title} — Queue / DLQ depth",
                width=12,
                height=6,
                left=[
                    _sqs_metric(queue, "ApproximateNumberOfMessagesVisible"),
                    _sqs_metric(dlq, "ApproximateNumberOfMessagesVisible"),
                ],
            )

        catalog_heartbeat_widget = GraphWidget(
            title="Catalog Refresh Heartbeat (must be ≥ 1 / hr)",
            width=12,
            height=6,
            left=[
                Metric(
                    namespace="SteamPulse",
                    metric_name="CatalogRefreshRun",
                    dimensions_map=custom_dims,
                    statistic=Stats.SUM,
                    period=cdk.Duration.hours(1),
                )
            ],
        )

        dashboard = Dashboard(
            self,
            "Dashboard",
            dashboard_name=f"SteamPulse-{env_cap}",
            period_override=PeriodOverride.AUTO,
        )
        dashboard.add_widgets(
            TextWidget(markdown="# Crawler Pipeline", width=24, height=1),
            _lambda_traffic(crawler_fn, "Crawler"),
            _lambda_p99(crawler_fn, "Crawler"),
            _lambda_traffic(ingest_fn, "Spoke Ingest"),
            _queue_depth(app_crawl_queue, app_crawl_dlq, "App Crawl"),
            _queue_depth(review_crawl_queue, review_crawl_dlq, "Review Crawl"),
            _queue_depth(spoke_results_queue, spoke_results_dlq, "Spoke Results"),
            catalog_heartbeat_widget,
            TextWidget(markdown="# API & Frontend", width=24, height=1),
            _lambda_traffic(api_fn, "API"),
            _lambda_p99(api_fn, "API"),
            _lambda_traffic(frontend_fn, "Frontend SSR"),
            TextWidget(markdown="# Supporting Services", width=24, height=1),
            _queue_depth(email_queue, email_dlq, "Email"),
        )
