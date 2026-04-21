"""CDK assertion tests for ComputeStack — IAM grants for SNS publish."""

import os
import sys

import aws_cdk as cdk
import aws_cdk.assertions as assertions
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_secretsmanager as secretsmanager
import aws_cdk.aws_sns as sns
import aws_cdk.aws_sqs as sqs
import pytest

# Expose library_layer for config import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "library-layer"))
# Expose infra stacks
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra"))

from library_layer.config import SteamPulseConfig
from stacks.compute_stack import ComputeStack


@pytest.fixture
def template() -> assertions.Template:
    # Skip Docker bundling (PythonFunction pip install) — resource properties
    # are still fully synthesized, only the asset Code is a placeholder.
    app = cdk.App(context={"aws:cdk:bundling-stacks": []})
    stack = cdk.Stack(app, "DepsStack")

    vpc = ec2.Vpc(stack, "Vpc")
    intra_sg = ec2.SecurityGroup(stack, "IntraSg", vpc=vpc)
    db_secret = secretsmanager.Secret(stack, "DbSecret")
    app_crawl_queue = sqs.Queue(stack, "AppCrawlQueue")
    review_crawl_queue = sqs.Queue(stack, "ReviewCrawlQueue")
    game_events_topic = sns.Topic(stack, "GameEvents")
    content_events_topic = sns.Topic(stack, "ContentEvents")
    system_events_topic = sns.Topic(stack, "SystemEvents")
    spoke_results_queue = sqs.Queue(stack, "SpokeResultsQueue")
    email_queue = sqs.Queue(stack, "EmailQueue")
    cache_invalidation_queue = sqs.Queue(stack, "CacheInvalidationQueue")
    genre_synthesis_queue = sqs.Queue(stack, "GenreSynthesisQueue")

    config = SteamPulseConfig(
        ENVIRONMENT="production",
        DB_SECRET_NAME="steampulse/test/db-credentials",
        STEAM_API_KEY_SECRET_NAME="steampulse/test/steam-api-key",
        RESEND_API_KEY_SECRET_NAME="steampulse/test/resend-api-key",
        SFN_PARAM_NAME="/steampulse/test/compute/sfn-arn",
        STEP_FUNCTIONS_PARAM_NAME="/steampulse/test/compute/sfn-arn",
        APP_CRAWL_QUEUE_PARAM_NAME="/steampulse/test/messaging/app-crawl-queue-url",
        REVIEW_CRAWL_QUEUE_PARAM_NAME="/steampulse/test/messaging/review-crawl-queue-url",
        ASSETS_BUCKET_PARAM_NAME="/steampulse/test/data/assets-bucket-name",
        GAME_EVENTS_TOPIC_PARAM_NAME="/steampulse/test/messaging/game-events-topic-arn",
        CONTENT_EVENTS_TOPIC_PARAM_NAME="/steampulse/test/messaging/content-events-topic-arn",
        SYSTEM_EVENTS_TOPIC_PARAM_NAME="/steampulse/test/messaging/system-events-topic-arn",
        EMAIL_QUEUE_PARAM_NAME="/steampulse/test/messaging/email-queue-url",
        SPOKE_CRAWL_QUEUE_URLS="https://sqs.us-east-1.amazonaws.com/123456789012/steampulse-spoke-crawl-us-east-1-production",
    )
    compute = ComputeStack(
        app,
        "TestCompute",
        config=config,
        vpc=vpc,
        intra_sg=intra_sg,
        db_secret=db_secret,
        app_crawl_queue=app_crawl_queue,
        review_crawl_queue=review_crawl_queue,
        game_events_topic=game_events_topic,
        content_events_topic=content_events_topic,
        system_events_topic=system_events_topic,
        spoke_results_queue=spoke_results_queue,
        email_queue=email_queue,
        cache_invalidation_queue=cache_invalidation_queue,
        genre_synthesis_queue=genre_synthesis_queue,
        spoke_crawl_queue_urls="https://sqs.us-east-1.amazonaws.com/123456789012/steampulse-spoke-crawl-us-east-1-production",
    )
    return assertions.Template.from_stack(compute)


def test_compute_stack_grants_sns_publish(template: assertions.Template) -> None:
    """Lambda roles have sns:Publish permission on SNS topics."""
    policies = template.find_resources("AWS::IAM::Policy")
    sns_publish_found = False

    for _logical_id, resource in policies.items():
        statements = resource.get("Properties", {}).get("PolicyDocument", {}).get("Statement", [])
        for stmt in statements:
            actions = stmt.get("Action", [])
            if isinstance(actions, str):
                actions = [actions]
            if "sns:Publish" in actions:
                sns_publish_found = True
                break
        if sns_publish_found:
            break

    assert sns_publish_found, "No IAM policy grants sns:Publish"


def test_compute_stack_batches_spoke_ingest_sqs_events(template: assertions.Template) -> None:
    """Spoke ingest uses larger SQS batches with a short batching window."""
    template.has_resource_properties(
        "AWS::Lambda::EventSourceMapping",
        {
            "BatchSize": 100,
            "MaximumBatchingWindowInSeconds": 5,
            "ScalingConfig": {"MaximumConcurrency": 6},
            "FunctionResponseTypes": ["ReportBatchItemFailures"],
        },
    )
