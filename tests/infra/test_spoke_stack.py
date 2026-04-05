"""CDK assertions for CrawlSpokeStack."""

import os
import sys

# Expose library_layer and infra stacks
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "library-layer"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra"))

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template
from library_layer.config import SteamPulseConfig
from stacks.spoke_stack import CrawlSpokeStack

_TEST_CONFIG = SteamPulseConfig(
    ENVIRONMENT="staging",
    DB_SECRET_NAME="steampulse/test/db-credentials",
    STEAM_API_KEY_SECRET_NAME="steampulse/test/steam-api-key",
    SFN_PARAM_NAME="/steampulse/test/compute/sfn-arn",
    STEP_FUNCTIONS_PARAM_NAME="/steampulse/test/compute/sfn-arn",
    APP_CRAWL_QUEUE_PARAM_NAME="/steampulse/test/messaging/app-crawl-queue-url",
    REVIEW_CRAWL_QUEUE_PARAM_NAME="/steampulse/test/messaging/review-crawl-queue-url",
    ASSETS_BUCKET_PARAM_NAME="/steampulse/test/data/assets-bucket-name",
    GAME_EVENTS_TOPIC_PARAM_NAME="/steampulse/test/messaging/game-events-topic-arn",
    CONTENT_EVENTS_TOPIC_PARAM_NAME="/steampulse/test/messaging/content-events-topic-arn",
    SYSTEM_EVENTS_TOPIC_PARAM_NAME="/steampulse/test/messaging/system-events-topic-arn",
    SPOKE_CRAWL_QUEUE_URLS="https://sqs.us-east-1.amazonaws.com/123456789012/steampulse-spoke-crawl-us-east-1-staging",
)


@pytest.fixture
def template() -> Template:
    # Skip Docker bundling (PythonFunction pip install) — resource properties
    # are still fully synthesized, only the asset Code is a placeholder.
    app = cdk.App(context={"aws:cdk:bundling-stacks": []})
    stack = CrawlSpokeStack(
        app,
        "TestSpoke",
        config=_TEST_CONFIG,
        primary_region="us-west-2",
        environment="staging",
        spoke_results_queue_url="https://sqs.us-west-2.amazonaws.com/123456789012/SpokeResultsQueue",
        assets_bucket_name="steampulse-assets-test",
        steam_api_key_secret_name="steampulse/test/steam-api-key",
        env=cdk.Environment(account="123456789012", region="us-east-1"),
    )
    return Template.from_stack(stack)


def test_one_lambda_function(template: Template) -> None:
    """Spoke creates exactly one Lambda function — the crawler."""
    template.resource_count_is("AWS::Lambda::Function", 1)


def test_no_reserved_concurrency(template: Template) -> None:
    """Concurrency is controlled by SQS ESM max_concurrency, not reserved concurrency."""
    from aws_cdk.assertions import Match

    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "ReservedConcurrentExecutions": Match.absent(),
        },
    )


def test_deterministic_function_name(template: Template) -> None:
    """Spoke Lambda has a deterministic name for cross-region invocation."""
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "steampulse-spoke-crawler-us-east-1-staging",
        },
    )


def test_no_vpc(template: Template) -> None:
    template.resource_count_is("AWS::EC2::VPC", 0)


def test_sqs_event_source_mapping(template: Template) -> None:
    """Spoke Lambda is triggered by SQS event source mapping."""
    template.resource_count_is("AWS::Lambda::EventSourceMapping", 1)


def test_spoke_crawl_queue_exists(template: Template) -> None:
    """Per-spoke SQS crawl queue with deterministic name."""
    template.has_resource_properties(
        "AWS::SQS::Queue",
        {
            "QueueName": "steampulse-spoke-crawl-us-east-1-staging",
        },
    )


def test_ssm_params(template: Template) -> None:
    """Two SSM params: spoke status + crawl queue URL."""
    template.resource_count_is("AWS::SSM::Parameter", 2)


def test_alarm_topic(template: Template) -> None:
    """Spoke has a local SNS alarm topic."""
    template.resource_count_is("AWS::SNS::Topic", 1)


def test_alarm_topic_output(template: Template) -> None:
    """CfnOutput for the spoke alarm topic ARN."""
    template.has_output("SpokeAlarmTopicArn", {})


def test_no_cloudwatch_dashboards(template: Template) -> None:
    """Spoke monitoring is alarms-only; no CloudWatch dashboards should be created."""
    template.resource_count_is("AWS::CloudWatch::Dashboard", 0)
