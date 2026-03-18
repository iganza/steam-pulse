"""CDK assertion tests for ComputeStack — IAM grants for SNS publish."""

import os
import sys

import aws_cdk as cdk
import aws_cdk.assertions as assertions
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_secretsmanager as secretsmanager
import aws_cdk.aws_sns as sns
import aws_cdk.aws_sqs as sqs

# Expose library_layer for config import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "library-layer"))
# Expose infra stacks
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra"))

from library_layer.config import SteamPulseConfig
from stacks.compute_stack import ComputeStack


def _synth_compute_stack() -> assertions.Template:
    app = cdk.App()
    stack = cdk.Stack(app, "DepsStack")

    vpc = ec2.Vpc(stack, "Vpc")
    intra_sg = ec2.SecurityGroup(stack, "IntraSg", vpc=vpc)
    db_secret = secretsmanager.Secret(stack, "DbSecret")
    app_crawl_queue = sqs.Queue(stack, "AppCrawlQueue")
    review_crawl_queue = sqs.Queue(stack, "ReviewCrawlQueue")
    game_events_topic = sns.Topic(stack, "GameEvents")
    content_events_topic = sns.Topic(stack, "ContentEvents")
    system_events_topic = sns.Topic(stack, "SystemEvents")

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
    )
    return assertions.Template.from_stack(compute)


# ── Test 47: Lambda IAM policies include sns:Publish ─────────────────────────


def test_compute_stack_grants_sns_publish() -> None:
    """Lambda roles have sns:Publish permission on SNS topics (test 47)."""
    template = _synth_compute_stack()

    # Find IAM policies that grant sns:Publish
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
