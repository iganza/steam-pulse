"""MessagingStack — SQS queues and EventBridge rules that target SQS.

No VPC dependency — SQS is fully managed. Deployed independently of compute
so queue config changes (visibility timeout, DLQ thresholds) never risk a
Lambda code deploy.

EventBridge rules targeting Lambda functions directly live in ComputeStack
because they hold a CDK reference to the Lambda function.
"""

import aws_cdk as cdk
import aws_cdk.aws_events as events
import aws_cdk.aws_events_targets as events_targets
import aws_cdk.aws_iam as iam
import aws_cdk.aws_sns as sns
import aws_cdk.aws_sns_subscriptions as subs
import aws_cdk.aws_sqs as sqs
import aws_cdk.aws_ssm as ssm
from constructs import Construct
from library_layer.config import SteamPulseConfig


class MessagingStack(cdk.Stack):
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

        # ── SNS Domain Topics ────────────────────────────────────────────────
        self.game_events_topic = sns.Topic(self, "GameEventsTopic")
        self.content_events_topic = sns.Topic(self, "ContentEventsTopic")
        self.system_events_topic = sns.Topic(self, "SystemEventsTopic")

        # ── Queues ────────────────────────────────────────────────────────────
        self.metadata_enrichment_dlq = sqs.Queue(
            self,
            "MetadataEnrichmentDlq",
            retention_period=cdk.Duration.days(14),
        )
        self.review_crawl_dlq = sqs.Queue(
            self,
            "ReviewCrawlDlq",
            retention_period=cdk.Duration.days(14),
        )
        self.batch_staging_dlq = sqs.Queue(
            self,
            "BatchStagingDlq",
            retention_period=cdk.Duration.days(14),
        )
        self.cache_invalidation_dlq = sqs.Queue(
            self,
            "CacheInvalidationDlq",
            retention_period=cdk.Duration.days(14),
        )
        self.spoke_results_dlq = sqs.Queue(
            self,
            "SpokeResultsDlq",
            retention_period=cdk.Duration.days(14),
        )
        self.email_dlq = sqs.Queue(
            self,
            "EmailDlq",
            retention_period=cdk.Duration.days(14),
        )
        self.frontend_revalidation_dlq = sqs.Queue(
            self,
            "FrontendRevalidationDlq",
            retention_period=cdk.Duration.days(14),
        )
        # Deterministic names — spokes in other regions construct ARN/URL
        # strings from these names (CDK tokens can't cross regions).
        self.app_crawl_queue = sqs.Queue(
            self,
            "MetadataEnrichmentQueue",
            queue_name=f"steampulse-app-crawl-{env}",
            visibility_timeout=cdk.Duration.minutes(10),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.metadata_enrichment_dlq,
            ),
        )
        self.review_crawl_queue = sqs.Queue(
            self,
            "ReviewCrawlQueue",
            queue_name=f"steampulse-review-crawl-{env}",
            visibility_timeout=cdk.Duration.minutes(10),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.review_crawl_dlq,
            ),
        )
        self.batch_staging_queue = sqs.Queue(
            self,
            "BatchStagingQueue",
            visibility_timeout=cdk.Duration.minutes(10),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.batch_staging_dlq,
            ),
        )
        self.cache_invalidation_queue = sqs.Queue(
            self,
            "CacheInvalidationQueue",
            visibility_timeout=cdk.Duration.minutes(5),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.cache_invalidation_dlq,
            ),
        )
        self.spoke_results_queue = sqs.Queue(
            self,
            "SpokeResultsQueue",
            queue_name=f"steampulse-spoke-results-{env}",
            visibility_timeout=cdk.Duration.minutes(15),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.spoke_results_dlq,
            ),
        )

        self.email_queue = sqs.Queue(
            self,
            "EmailQueue",
            visibility_timeout=cdk.Duration.minutes(5),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.email_dlq,
            ),
        )
        # Fed by ReportReadyEvent, drained by revalidate_frontend Lambda.
        self.frontend_revalidation_queue = sqs.Queue(
            self,
            "FrontendRevalidationQueue",
            visibility_timeout=cdk.Duration.minutes(2),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.frontend_revalidation_dlq,
            ),
        )

        # ── Tags ────────────────────────────────────────────────────────────
        for q in (
            self.app_crawl_queue,
            self.metadata_enrichment_dlq,
            self.review_crawl_queue,
            self.review_crawl_dlq,
        ):
            cdk.Tags.of(q).add("steampulse:service", "crawler")

        for q in (self.spoke_results_queue, self.spoke_results_dlq):
            cdk.Tags.of(q).add("steampulse:service", "ingest")

        for q in (self.email_queue, self.email_dlq):
            cdk.Tags.of(q).add("steampulse:service", "email")

        for q in (self.batch_staging_queue, self.batch_staging_dlq):
            cdk.Tags.of(q).add("steampulse:service", "batch")

        for q in (self.cache_invalidation_queue, self.cache_invalidation_dlq):
            cdk.Tags.of(q).add("steampulse:service", "frontend")

        for q in (self.frontend_revalidation_queue, self.frontend_revalidation_dlq):
            cdk.Tags.of(q).add("steampulse:service", "frontend")

        cdk.Tags.of(self.game_events_topic).add("steampulse:service", "crawler")
        cdk.Tags.of(self.content_events_topic).add("steampulse:service", "analysis")
        cdk.Tags.of(self.system_events_topic).add("steampulse:service", "admin")

        # ── SNS → SQS Subscriptions with Filter Policies ────────────────────

        # metadata-enrichment-queue ← game-events (game-discovered only)
        self.game_events_topic.add_subscription(
            subs.SqsSubscription(
                self.app_crawl_queue,
                filter_policy={
                    "event_type": sns.SubscriptionFilter.string_filter(
                        allowlist=["game-discovered"],
                    ),
                },
            )
        )

        # review-crawl-queue ← game-events
        # Single subscription with $or filter: game-metadata-ready (only when
        # eligible) OR game-released/game-updated (always eligible).
        # SNS does not allow two subscriptions with the same {Topic, Protocol,
        # Endpoint} but different filter policies, so we use CfnSubscription
        # with a raw $or filter policy.
        review_crawl_sub = sns.CfnSubscription(
            self,
            "ReviewCrawlSub",
            protocol="sqs",
            topic_arn=self.game_events_topic.topic_arn,
            endpoint=self.review_crawl_queue.queue_arn,
            filter_policy={
                "$or": [
                    {"event_type": ["game-metadata-ready"], "is_eligible": ["true"]},
                    {"event_type": ["game-released", "game-updated"]},
                ],
            },
        )
        # CfnSubscription doesn't auto-grant — allow SNS to deliver to the queue.
        self.review_crawl_queue.grant_send_messages(iam.ServicePrincipal("sns.amazonaws.com"))

        # batch-staging-queue ← content-events (reviews-ready only)
        self.content_events_topic.add_subscription(
            subs.SqsSubscription(
                self.batch_staging_queue,
                filter_policy={
                    "event_type": sns.SubscriptionFilter.string_filter(
                        allowlist=["reviews-ready"],
                    ),
                },
            )
        )

        # cache-invalidation-queue ← system-events (catalog-refresh-complete only; daily).
        self.system_events_topic.add_subscription(
            subs.SqsSubscription(
                self.cache_invalidation_queue,
                filter_policy={
                    "event_type": sns.SubscriptionFilter.string_filter(
                        allowlist=["catalog-refresh-complete"],
                    ),
                },
            )
        )

        # frontend-revalidation-queue ← content-events (report-ready only).
        self.content_events_topic.add_subscription(
            subs.SqsSubscription(
                self.frontend_revalidation_queue,
                filter_policy={
                    "event_type": sns.SubscriptionFilter.string_filter(
                        allowlist=["report-ready"],
                    ),
                },
            )
        )

        # ── EventBridge → SQS ─────────────────────────────────────────────────
        # Disabled by default — enable manually after initial seed completes.
        nightly_rule = events.Rule(
            self,
            "NightlyRecrawl",
            schedule=events.Schedule.cron(hour="2", minute="0"),
            description="Nightly re-crawl of top 500 games",
            enabled=False,
        )
        nightly_rule.add_target(events_targets.SqsQueue(self.app_crawl_queue))

        # ── SSM — read by MonitoringStack without Fn::ImportValue ─────────────
        ssm.StringParameter(
            self,
            "AppCrawlQueueArnParam",
            parameter_name=f"/steampulse/{env}/messaging/app-crawl-queue-arn",
            string_value=self.app_crawl_queue.queue_arn,
        )
        ssm.StringParameter(
            self,
            "ReviewCrawlQueueArnParam",
            parameter_name=f"/steampulse/{env}/messaging/review-crawl-queue-arn",
            string_value=self.review_crawl_queue.queue_arn,
        )
        ssm.StringParameter(
            self,
            "AppCrawlDlqArnParam",
            parameter_name=f"/steampulse/{env}/messaging/app-crawl-dlq-arn",
            string_value=self.metadata_enrichment_dlq.queue_arn,
        )
        ssm.StringParameter(
            self,
            "ReviewCrawlDlqArnParam",
            parameter_name=f"/steampulse/{env}/messaging/review-crawl-dlq-arn",
            string_value=self.review_crawl_dlq.queue_arn,
        )

        # Queue URL SSM params — resolved by Lambda at cold start
        ssm.StringParameter(
            self,
            "AppCrawlQueueUrlParam",
            parameter_name=f"/steampulse/{env}/messaging/app-crawl-queue-url",
            string_value=self.app_crawl_queue.queue_url,
        )
        ssm.StringParameter(
            self,
            "ReviewCrawlQueueUrlParam",
            parameter_name=f"/steampulse/{env}/messaging/review-crawl-queue-url",
            string_value=self.review_crawl_queue.queue_url,
        )

        # Topic ARN SSM params
        ssm.StringParameter(
            self,
            "GameEventsTopicArnParam",
            parameter_name=f"/steampulse/{env}/messaging/game-events-topic-arn",
            string_value=self.game_events_topic.topic_arn,
        )
        ssm.StringParameter(
            self,
            "ContentEventsTopicArnParam",
            parameter_name=f"/steampulse/{env}/messaging/content-events-topic-arn",
            string_value=self.content_events_topic.topic_arn,
        )
        ssm.StringParameter(
            self,
            "SystemEventsTopicArnParam",
            parameter_name=f"/steampulse/{env}/messaging/system-events-topic-arn",
            string_value=self.system_events_topic.topic_arn,
        )

        # Spoke results queue SSM params
        ssm.StringParameter(
            self,
            "SpokeResultsQueueArnParam",
            parameter_name=f"/steampulse/{env}/messaging/spoke-results-queue-arn",
            string_value=self.spoke_results_queue.queue_arn,
        )
        ssm.StringParameter(
            self,
            "SpokeResultsQueueUrlParam",
            parameter_name=f"/steampulse/{env}/messaging/spoke-results-queue-url",
            string_value=self.spoke_results_queue.queue_url,
        )

        # Email queue SSM param — resolved by API and EmailFn at cold start
        ssm.StringParameter(
            self,
            "EmailQueueUrlParam",
            parameter_name=f"/steampulse/{env}/messaging/email-queue-url",
            string_value=self.email_queue.queue_url,
        )

        ssm.StringParameter(
            self,
            "SpokeResultsDlqArnParam",
            parameter_name=f"/steampulse/{env}/messaging/spoke-results-dlq-arn",
            string_value=self.spoke_results_dlq.queue_arn,
        )
        ssm.StringParameter(
            self,
            "EmailQueueArnParam",
            parameter_name=f"/steampulse/{env}/messaging/email-queue-arn",
            string_value=self.email_queue.queue_arn,
        )
        ssm.StringParameter(
            self,
            "EmailDlqArnParam",
            parameter_name=f"/steampulse/{env}/messaging/email-dlq-arn",
            string_value=self.email_dlq.queue_arn,
        )
        ssm.StringParameter(
            self,
            "FrontendRevalidationQueueArnParam",
            parameter_name=f"/steampulse/{env}/messaging/frontend-revalidation-queue-arn",
            string_value=self.frontend_revalidation_queue.queue_arn,
        )
        ssm.StringParameter(
            self,
            "FrontendRevalidationDlqArnParam",
            parameter_name=f"/steampulse/{env}/messaging/frontend-revalidation-dlq-arn",
            string_value=self.frontend_revalidation_dlq.queue_arn,
        )
        # Eligibility threshold SSM param
        ssm.StringParameter(
            self,
            "EligibilityThresholdParam",
            parameter_name=f"/steampulse/{env}/config/review-eligibility-threshold",
            string_value="500",
        )
