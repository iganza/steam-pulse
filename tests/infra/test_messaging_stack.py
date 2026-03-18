"""CDK assertion tests for MessagingStack — SNS topics, subscriptions, SSM params."""

import os
import sys

import aws_cdk as cdk
import aws_cdk.assertions as assertions

# Expose library_layer for config import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "library-layer"))
# Expose infra stacks
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra"))

from library_layer.config import SteamPulseConfig
from stacks.messaging_stack import MessagingStack


def _synth_messaging_stack() -> assertions.Template:
    app = cdk.App()
    config = SteamPulseConfig(
        ENVIRONMENT="staging",
        DB_SECRET_ARN="arn:aws:secretsmanager:us-east-1:123456789012:secret:db",
        SFN_ARN="arn:aws:states:us-east-1:123456789012:stateMachine:crawl",
        APP_CRAWL_QUEUE_URL="https://sqs.us-east-1.amazonaws.com/123456789012/app-crawl",
        REVIEW_CRAWL_QUEUE_URL="https://sqs.us-east-1.amazonaws.com/123456789012/review-crawl",
        STEAM_API_KEY_SECRET_ARN="arn:aws:secretsmanager:us-east-1:123456789012:secret:steam-key",
        ASSETS_BUCKET_NAME="steampulse-assets-test",
        STEP_FUNCTIONS_ARN="arn:aws:states:us-east-1:123456789012:stateMachine:crawl",
        GAME_EVENTS_TOPIC_ARN="arn:aws:sns:us-east-1:123456789012:game-events",
        CONTENT_EVENTS_TOPIC_ARN="arn:aws:sns:us-east-1:123456789012:content-events",
        SYSTEM_EVENTS_TOPIC_ARN="arn:aws:sns:us-east-1:123456789012:system-events",
    )
    stack = MessagingStack(app, "TestMessaging", config=config)
    return assertions.Template.from_stack(stack)


# ── Test 44: 3 SNS topics created ────────────────────────────────────────────


def test_messaging_stack_creates_3_topics() -> None:
    """MessagingStack creates exactly 3 SNS topics (test 44)."""
    template = _synth_messaging_stack()
    template.resource_count_is("AWS::SNS::Topic", 3)


# ── Test 45: subscriptions have event_type filter policies ────────────────────


def test_messaging_stack_creates_subscriptions_with_filters() -> None:
    """SNS subscriptions use event_type filter policies (test 45)."""
    template = _synth_messaging_stack()
    # At least 5 subscriptions: metadata-enrichment, review-crawl x2,
    # batch-staging, cache-invalidation
    subs = template.find_resources("AWS::SNS::Subscription")
    assert len(subs) >= 5, f"Expected >= 5 subscriptions, got {len(subs)}"

    # Every subscription must have a FilterPolicy with event_type
    for logical_id, resource in subs.items():
        props = resource["Properties"]
        assert "FilterPolicy" in props, f"{logical_id} missing FilterPolicy"
        fp = props["FilterPolicy"]
        assert "event_type" in fp, f"{logical_id} FilterPolicy missing event_type"


# ── Test 46: review-crawl-queue has 2 subscriptions with correct filters ──────


def test_messaging_stack_review_crawl_filter() -> None:
    """Review-crawl-queue has TWO subscriptions with correct filters (test 46)."""
    template = _synth_messaging_stack()
    subs = template.find_resources("AWS::SNS::Subscription")

    review_crawl_subs = []
    for _logical_id, resource in subs.items():
        props = resource["Properties"]
        # Check if endpoint references the review crawl queue
        endpoint = props.get("Endpoint", {})
        # CDK uses Fn::GetAtt on the queue ARN
        if isinstance(endpoint, dict) and "Fn::GetAtt" in endpoint:
            ref = endpoint["Fn::GetAtt"][0]
            if "ReviewCrawl" in ref:
                review_crawl_subs.append(props["FilterPolicy"])

    assert len(review_crawl_subs) == 2, (
        f"Expected 2 review-crawl subscriptions, got {len(review_crawl_subs)}"
    )

    # One should filter for game-metadata-ready + is_eligible
    filters_flat = [str(fp) for fp in review_crawl_subs]
    has_metadata_ready = any(
        "game-metadata-ready" in f and "is_eligible" in f for f in filters_flat
    )
    has_released_updated = any("game-released" in f for f in filters_flat)

    assert has_metadata_ready, "Missing game-metadata-ready + is_eligible subscription"
    assert has_released_updated, "Missing game-released/game-updated subscription"


# ── Test 50: SSM param for eligibility threshold ──────────────────────────────


def test_ssm_param_created_for_threshold() -> None:
    """CDK creates SSM param for review eligibility threshold (test 50)."""
    template = _synth_messaging_stack()
    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": "/steampulse/staging/config/review-eligibility-threshold",
            "Value": "500",
        },
    )
