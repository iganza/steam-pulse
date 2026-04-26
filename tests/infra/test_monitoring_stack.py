"""CDK assertions for MonitoringStack."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "library-layer"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra"))

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template
from library_layer.config import SteamPulseConfig
from stacks.monitoring_stack import MonitoringStack

_TEST_CONFIG = SteamPulseConfig(
    ENVIRONMENT="staging",
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
    SPOKE_REGIONS="us-west-2,us-east-1",
)


@pytest.fixture
def template() -> Template:
    app = cdk.App(context={"aws:cdk:bundling-stacks": []})
    stack = MonitoringStack(app, "TestMonitoring", config=_TEST_CONFIG)
    return Template.from_stack(stack)


def test_alarm_topic_created(template: Template) -> None:
    """One SNS topic for alarm routing."""
    template.resource_count_is("AWS::SNS::Topic", 1)


def test_dashboard_created(template: Template) -> None:
    """One CloudWatch dashboard."""
    template.resource_count_is("AWS::CloudWatch::Dashboard", 1)


def test_cfn_output_alarm_topic_arn(template: Template) -> None:
    """CfnOutput for the alarm topic ARN."""
    template.has_output("AlarmTopicArn", {})


def test_ssm_discovery_no_cross_stack_refs(template: Template) -> None:
    """Resources are discovered via SSM parameter references, never Fn::ImportValue."""
    import json

    body = template.to_json()
    raw = json.dumps(body)
    # CDK resolves value_for_string_parameter() as CloudFormation template parameters
    # with Default pointing to the SSM path — check those exist.
    params = body.get("Parameters", {})
    ssm_params = [
        k
        for k, v in params.items()
        if v.get("Type") == "AWS::SSM::Parameter::Value<String>"
        and v.get("Default", "").startswith("/steampulse/")
    ]
    assert len(ssm_params) > 0, "Expected SSM parameter references in template"
    assert "Fn::ImportValue" not in raw, "Cross-stack Fn::ImportValue must not be used"
