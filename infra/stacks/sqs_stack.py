"""SqsStack — SQS queues, DLQs, and EventBridge schedules for the crawler pipeline."""
import aws_cdk as cdk
import aws_cdk.aws_events as events
import aws_cdk.aws_events_targets as targets
import aws_cdk.aws_sqs as sqs
from constructs import Construct


class SqsStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, stage: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Dead-letter queues
        app_crawl_dlq = sqs.Queue(
            self,
            "AppCrawlDlq",
            queue_name=f"{stage}-steampulse-app-crawl-dlq",
            retention_period=cdk.Duration.days(14),
        )
        review_crawl_dlq = sqs.Queue(
            self,
            "ReviewCrawlDlq",
            queue_name=f"{stage}-steampulse-review-crawl-dlq",
            retention_period=cdk.Duration.days(14),
        )

        # App crawl queue — batch 10, 5 min visibility
        self.app_crawl_queue = sqs.Queue(
            self,
            "AppCrawlQueue",
            queue_name=f"{stage}-steampulse-app-crawl",
            visibility_timeout=cdk.Duration.minutes(5),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=app_crawl_dlq,
            ),
        )

        # Review crawl queue — batch 1, 10 min visibility
        self.review_crawl_queue = sqs.Queue(
            self,
            "ReviewCrawlQueue",
            queue_name=f"{stage}-steampulse-review-crawl",
            visibility_timeout=cdk.Duration.minutes(10),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=review_crawl_dlq,
            ),
        )

        # EventBridge: nightly re-crawl of top 500 — disabled until we're ready to run on a schedule
        nightly_rule = events.Rule(
            self,
            "NightlyRecrawl",
            schedule=events.Schedule.cron(hour="2", minute="0"),
            description="Nightly re-crawl of top 500 games",
            enabled=False,
        )
        nightly_rule.add_target(targets.SqsQueue(self.app_crawl_queue))
