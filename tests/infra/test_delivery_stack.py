"""CDK assertion tests for DeliveryStack — www → apex CloudFront Function.

Asserts the redirect Function exists in production synth and is absent in
staging, plus that it's wired to the default behavior and every additional
behavior on the distribution.
"""

import os
import sys

import aws_cdk as cdk
import aws_cdk.assertions as assertions
import aws_cdk.aws_certificatemanager as acm
import aws_cdk.aws_lambda as lambda_
import pytest

# Expose library_layer for config import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "library-layer"))
# Expose infra stacks
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra"))

from library_layer.config import SteamPulseConfig
from stacks.delivery_stack import DeliveryStack


def _make_template(*, env: str) -> assertions.Template:
    app = cdk.App(
        context={
            "aws:cdk:bundling-stacks": [],
            "hosted-zone-id": "Z000000000000000000000",
            "domain-live": False,
        }
    )
    deps = cdk.Stack(
        app,
        "DepsStack",
        env=cdk.Environment(account="123456789012", region="us-west-2"),
    )

    api_fn = lambda_.Function(
        deps,
        "ApiFn",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="index.handler",
        code=lambda_.Code.from_inline("def handler(e, c): return {}"),
    )
    api_fn_url = api_fn.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)
    frontend_fn = lambda_.Function(
        deps,
        "FrontendFn",
        runtime=lambda_.Runtime.NODEJS_20_X,
        handler="index.handler",
        code=lambda_.Code.from_inline("exports.handler = async () => ({})"),
    )
    frontend_fn_url = frontend_fn.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)

    config = SteamPulseConfig(
        ENVIRONMENT=env,
        DB_SECRET_NAME="steampulse/test/db-credentials",
        STEAM_API_KEY_SECRET_NAME="steampulse/test/steam-api-key",
        RESEND_API_KEY_SECRET_NAME="steampulse/test/resend-api-key",
        STEAM_API_KEY_PARAM_NAME="/steampulse/test/api-keys/steam",
        ANTHROPIC_API_KEY_PARAM_NAME="/steampulse/test/api-keys/anthropic",
        RESEND_API_KEY_PARAM_NAME="/steampulse/test/api-keys/resend",
        DB_PASSWORD_PARAM_NAME="/steampulse/test/db-password",
        SFN_PARAM_NAME="/steampulse/test/compute/sfn-arn",
        STEP_FUNCTIONS_PARAM_NAME="/steampulse/test/compute/sfn-arn",
        APP_CRAWL_QUEUE_PARAM_NAME="/steampulse/test/messaging/app-crawl-queue-url",
        REVIEW_CRAWL_QUEUE_PARAM_NAME="/steampulse/test/messaging/review-crawl-queue-url",
        ASSETS_BUCKET_PARAM_NAME="/steampulse/test/data/assets-bucket-name",
        GAME_EVENTS_TOPIC_PARAM_NAME="/steampulse/test/messaging/game-events-topic-arn",
        CONTENT_EVENTS_TOPIC_PARAM_NAME="/steampulse/test/messaging/content-events-topic-arn",
        SYSTEM_EVENTS_TOPIC_PARAM_NAME="/steampulse/test/messaging/system-events-topic-arn",
        EMAIL_QUEUE_PARAM_NAME="/steampulse/test/messaging/email-queue-url",
        SPOKE_CRAWL_QUEUE_URLS="https://sqs.us-east-1.amazonaws.com/123456789012/steampulse-spoke-crawl-us-east-1",
        REFRESH_REVIEWS_ENABLED=True,
    )

    cert: acm.ICertificate | None = None
    if config.is_production:
        cert = acm.Certificate.from_certificate_arn(
            deps,
            "Cert",
            "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000",
        )

    delivery = DeliveryStack(
        app,
        f"TestDelivery{env}",
        config=config,
        api_fn_url=api_fn_url,
        frontend_fn_url=frontend_fn_url,
        certificate=cert,
        env=cdk.Environment(account="123456789012", region="us-west-2"),
    )
    return assertions.Template.from_stack(delivery)


@pytest.fixture
def production_template() -> assertions.Template:
    return _make_template(env="production")


@pytest.fixture
def staging_template() -> assertions.Template:
    return _make_template(env="staging")


def test_production_creates_www_to_apex_function(
    production_template: assertions.Template,
) -> None:
    """Production synth includes exactly one CloudFront Function."""
    production_template.resource_count_is("AWS::CloudFront::Function", 1)


def test_production_function_runs_on_viewer_request_with_js_2(
    production_template: assertions.Template,
) -> None:
    """Function uses cloudfront-js-2.0 runtime (matches our usage of for...in + regex)."""
    production_template.has_resource_properties(
        "AWS::CloudFront::Function",
        {"FunctionConfig": assertions.Match.object_like({"Runtime": "cloudfront-js-2.0"})},
    )


def test_production_attaches_function_to_default_and_all_additional_behaviors(
    production_template: assertions.Template,
) -> None:
    """Function attached to default + every additional behavior so no www path bypasses redirect."""
    distributions = production_template.find_resources("AWS::CloudFront::Distribution")
    assert len(distributions) == 1, "Expected exactly one CloudFront distribution"
    (dist,) = distributions.values()
    dist_config = dist["Properties"]["DistributionConfig"]

    default_assoc = dist_config["DefaultCacheBehavior"].get("FunctionAssociations") or []
    assert default_assoc, "Default behavior missing FunctionAssociations"

    additional = dist_config.get("CacheBehaviors", [])
    assert additional, "Expected additional cache behaviors on the distribution"
    missing = [
        cb.get("PathPattern", "<unknown>")
        for cb in additional
        if not cb.get("FunctionAssociations")
    ]
    assert not missing, (
        f"Behaviors missing FunctionAssociations: {missing} — "
        f"any www request to these paths would bypass the apex redirect"
    )


def test_staging_does_not_create_www_to_apex_function(
    staging_template: assertions.Template,
) -> None:
    """Staging serves only the CloudFront default domain — no www, no Function needed."""
    staging_template.resource_count_is("AWS::CloudFront::Function", 0)
