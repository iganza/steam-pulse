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
        SFN_PARAM_NAME="/steampulse/test/compute/sfn-arn",
        STEP_FUNCTIONS_PARAM_NAME="/steampulse/test/compute/sfn-arn",
        APP_CRAWL_QUEUE_PARAM_NAME="/steampulse/test/messaging/app-crawl-queue-url",
        REVIEW_CRAWL_QUEUE_PARAM_NAME="/steampulse/test/messaging/review-crawl-queue-url",
        ASSETS_BUCKET_PARAM_NAME="/steampulse/test/app/assets-bucket-name",
        GAME_EVENTS_TOPIC_PARAM_NAME="/steampulse/test/messaging/game-events-topic-arn",
        CONTENT_EVENTS_TOPIC_PARAM_NAME="/steampulse/test/messaging/content-events-topic-arn",
        SYSTEM_EVENTS_TOPIC_PARAM_NAME="/steampulse/test/messaging/system-events-topic-arn",
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
    # 4 subscriptions: metadata-enrichment, review-crawl ($or CfnSubscription),
    # batch-staging, cache-invalidation (catalog-refresh-complete only).
    subs = template.find_resources("AWS::SNS::Subscription")
    assert len(subs) == 4, f"Expected 4 subscriptions, got {len(subs)}"

    # Every subscription must have a FilterPolicy
    for logical_id, resource in subs.items():
        props = resource["Properties"]
        assert "FilterPolicy" in props, f"{logical_id} missing FilterPolicy"


# ── Test 46: review-crawl-queue has 2 subscriptions with correct filters ──────


def test_messaging_stack_review_crawl_filter() -> None:
    """Review-crawl-queue has ONE $or subscription covering both filter conditions (test 46)."""
    template = _synth_messaging_stack()
    subs = template.find_resources("AWS::SNS::Subscription")

    review_crawl_subs = []
    for _logical_id, resource in subs.items():
        props = resource["Properties"]
        # CfnSubscription stores endpoint as a plain string ARN token
        endpoint = props.get("Endpoint", "")
        filter_policy = props.get("FilterPolicy", {})
        fp_str = str(filter_policy)
        if "ReviewCrawl" in fp_str or "ReviewCrawl" in str(endpoint):
            review_crawl_subs.append(filter_policy)
        # Also catch by $or key presence combined with both event types in the policy
        elif "$or" in filter_policy:
            review_crawl_subs.append(filter_policy)

    assert len(review_crawl_subs) == 1, (
        f"Expected 1 review-crawl $or subscription, got {len(review_crawl_subs)}"
    )

    fp = review_crawl_subs[0]
    fp_str = str(fp)
    assert "$or" in fp, f"Expected $or filter policy, got: {fp}"
    assert "game-metadata-ready" in fp_str, "Missing game-metadata-ready condition"
    assert "is_eligible" in fp_str, "Missing is_eligible condition"
    assert "game-released" in fp_str, "Missing game-released condition"
    assert "game-updated" in fp_str, "Missing game-updated condition"


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
