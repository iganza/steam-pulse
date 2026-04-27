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
        DB_SECRET_NAME="steampulse/test/db-credentials",
        STEAM_API_KEY_SECRET_NAME="steampulse/test/steam-api-key",
        STEAM_API_KEY_PARAM_NAME="/steampulse/test/api-keys/steam",
        ANTHROPIC_API_KEY_PARAM_NAME="/steampulse/test/api-keys/anthropic",
        RESEND_API_KEY_PARAM_NAME="/steampulse/test/api-keys/resend",
        DB_PASSWORD_PARAM_NAME="/steampulse/test/db-password",
        SFN_PARAM_NAME="/steampulse/test/compute/sfn-arn",
        STEP_FUNCTIONS_PARAM_NAME="/steampulse/test/compute/sfn-arn",
        APP_CRAWL_QUEUE_PARAM_NAME="/steampulse/test/messaging/app-crawl-queue-url",
        REVIEW_CRAWL_QUEUE_PARAM_NAME="/steampulse/test/messaging/review-crawl-queue-url",
        ASSETS_BUCKET_PARAM_NAME="/steampulse/test/app/assets-bucket-name",
        GAME_EVENTS_TOPIC_PARAM_NAME="/steampulse/test/messaging/game-events-topic-arn",
        CONTENT_EVENTS_TOPIC_PARAM_NAME="/steampulse/test/messaging/content-events-topic-arn",
        SYSTEM_EVENTS_TOPIC_PARAM_NAME="/steampulse/test/messaging/system-events-topic-arn",
        REFRESH_REVIEWS_ENABLED=False,
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
    # 3 subscriptions: metadata-enrichment, batch-staging, frontend-revalidation (report-ready).
    # review-crawl SNS bridge removed — review_crawl_queue is fed by inline Python dispatch.
    # cache-invalidation removed — matview refresh runs from local cron.
    subs = template.find_resources("AWS::SNS::Subscription")
    assert len(subs) == 3, f"Expected 3 subscriptions, got {len(subs)}"

    # Every subscription must have a FilterPolicy
    for logical_id, resource in subs.items():
        props = resource["Properties"]
        assert "FilterPolicy" in props, f"{logical_id} missing FilterPolicy"


# ── Test 46: review-crawl-queue has no SNS subscription (inline dispatch only) ──


def test_messaging_stack_no_review_crawl_subscription() -> None:
    """review_crawl_queue is fed by inline Python dispatch from CrawlService — no SNS bridge."""
    template = _synth_messaging_stack()
    subs = template.find_resources("AWS::SNS::Subscription")

    for _logical_id, resource in subs.items():
        props = resource["Properties"]
        filter_policy = props.get("FilterPolicy", {})
        assert "$or" not in filter_policy, (
            f"Found $or filter policy (legacy review-crawl bridge): {filter_policy}"
        )
        assert "game-released" not in str(filter_policy), (
            f"Found game-released routing (should be inline only): {filter_policy}"
        )


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
