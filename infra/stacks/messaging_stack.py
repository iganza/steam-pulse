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

        # ── Queues ────────────────────────────────────────────────────────────
        self.app_crawl_dlq = sqs.Queue(
            self, "AppCrawlDlq",
            retention_period=cdk.Duration.days(14),
        )
        self.review_crawl_dlq = sqs.Queue(
            self, "ReviewCrawlDlq",
            retention_period=cdk.Duration.days(14),
        )
        self.app_crawl_queue = sqs.Queue(
            self, "AppCrawlQueue",
            visibility_timeout=cdk.Duration.minutes(10),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3, queue=self.app_crawl_dlq,
            ),
        )
        self.review_crawl_queue = sqs.Queue(
            self, "ReviewCrawlQueue",
            visibility_timeout=cdk.Duration.minutes(10),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3, queue=self.review_crawl_dlq,
            ),
        )

        # ── EventBridge → SQS ─────────────────────────────────────────────────
        # Disabled by default — enable manually after initial seed completes.
        nightly_rule = events.Rule(
            self, "NightlyRecrawl",
            schedule=events.Schedule.cron(hour="2", minute="0"),
            description="Nightly re-crawl of top 500 games",
            enabled=False,
        )
        nightly_rule.add_target(events_targets.SqsQueue(self.app_crawl_queue))

        # ── SSM — read by MonitoringStack without Fn::ImportValue ─────────────
        ssm.StringParameter(
            self, "AppCrawlQueueArnParam",
            parameter_name=f"/steampulse/{env}/messaging/app-crawl-queue-arn",
            string_value=self.app_crawl_queue.queue_arn,
        )
        ssm.StringParameter(
            self, "ReviewCrawlQueueArnParam",
            parameter_name=f"/steampulse/{env}/messaging/review-crawl-queue-arn",
            string_value=self.review_crawl_queue.queue_arn,
        )
        ssm.StringParameter(
            self, "AppCrawlDlqArnParam",
            parameter_name=f"/steampulse/{env}/messaging/app-crawl-dlq-arn",
            string_value=self.app_crawl_dlq.queue_arn,
        )
        ssm.StringParameter(
            self, "ReviewCrawlDlqArnParam",
            parameter_name=f"/steampulse/{env}/messaging/review-crawl-dlq-arn",
            string_value=self.review_crawl_dlq.queue_arn,
        )
