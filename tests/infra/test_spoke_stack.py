"""CDK assertions for CrawlSpokeStack."""

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template
from stacks.spoke_stack import CrawlSpokeStack


@pytest.fixture
def template() -> Template:
    app = cdk.App()
    stack = CrawlSpokeStack(
        app, "TestSpoke",
        primary_region="us-west-2",
        environment="staging",
        app_crawl_queue_arn="arn:aws:sqs:us-west-2:123456789012:AppCrawlQueue",
        review_crawl_queue_arn="arn:aws:sqs:us-west-2:123456789012:ReviewCrawlQueue",
        spoke_results_queue_url="https://sqs.us-west-2.amazonaws.com/123456789012/SpokeResultsQueue",
        assets_bucket_name="steampulse-assets-test",
        steam_api_key_secret_name="steampulse/test/steam-api-key",
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
