"""CDK assertions for CrawlSpokeStack."""

import os
import sys

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

# Expose library_layer for config import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "library-layer"))
# Expose infra stacks
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra"))

from library_layer.config import SteamPulseConfig
from stacks.spoke_stack import CrawlSpokeStack


@pytest.fixture
def template() -> Template:
    config = SteamPulseConfig(
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
    )
    app = cdk.App()
    stack = CrawlSpokeStack(
        app, "TestSpoke",
        config=config,
        primary_region="us-west-2",
        app_crawl_queue_arn="arn:aws:sqs:us-west-2:123456789012:AppCrawlQueue",
        review_crawl_queue_arn="arn:aws:sqs:us-west-2:123456789012:ReviewCrawlQueue",
        spoke_results_queue_url="https://sqs.us-west-2.amazonaws.com/123456789012/SpokeResultsQueue",
        assets_bucket_name="steampulse-assets-test",
        env=cdk.Environment(account="123456789012", region="us-east-1"),
    )
    return Template.from_stack(stack)


def test_one_lambda(template: Template) -> None:
    template.resource_count_is("AWS::Lambda::Function", 1)


def test_reserved_concurrency_three(template: Template) -> None:
    template.has_resource_properties("AWS::Lambda::Function", {
        "ReservedConcurrentExecutions": 3,
    })


def test_no_vpc(template: Template) -> None:
    template.resource_count_is("AWS::EC2::VPC", 0)


def test_two_event_source_mappings(template: Template) -> None:
    """Two SQS triggers: metadata + reviews."""
    template.resource_count_is("AWS::Lambda::EventSourceMapping", 2)


def test_ssm_status_param(template: Template) -> None:
    template.resource_count_is("AWS::SSM::Parameter", 1)
