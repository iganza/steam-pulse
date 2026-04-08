"""Tests for batch analysis Lambda handlers and utility functions.

Uses MagicMock for bedrock (moto doesn't support Bedrock batch API) and moto
@mock_aws for S3/SNS. DB connections are patched to avoid needing a live database.
"""

import importlib
import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import boto3
import pytest
from library_layer.analyzer import CHUNK_SYSTEM_PROMPT, _build_chunk_user_message
from library_layer.models.analyzer_models import (
    AudienceProfile,
    CommunityHealth,
    ContentDepth,
    DevPriority,
    GameReport,
    MonetizationSentiment,
    RefundSignals,
)
from library_layer.models.review import Review
from moto import mock_aws

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_REGION = "us-east-1"
_BUCKET = "test-batch-bucket"
_EXECUTION_ID = "test-exec-2025-01-01"

_SSM_PARAMS = {
    "/steampulse/test/messaging/content-events-topic-arn": "arn:aws:sns:us-east-1:123456789012:content-events",
    "/steampulse/test/messaging/system-events-topic-arn": "arn:aws:sns:us-east-1:123456789012:system-events",
}

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


def _make_review(
    appid: int = 440,
    body: str = "Great game!",
    voted_up: bool = True,
    playtime_hours: int = 10,
    posted_at: datetime | None = None,
) -> Review:
    return Review(
        appid=appid,
        steam_review_id=f"rev-{abs(hash(body + str(appid)))}",
        voted_up=voted_up,
        body=body,
        playtime_hours=playtime_hours,
        posted_at=posted_at or datetime(2024, 6, 15, tzinfo=UTC),
    )


def _minimal_game_report_json(appid: int = 440) -> str:
    """Return a minimal valid GameReport as a JSON string (for use as LLM output).

    Sentiment magnitude (positive_pct / review_score_desc) lives on the Game row,
    not the report — see the data-source-clarity refactor.
    """
    return GameReport(
        game_name="Test Game",
        total_reviews_analyzed=100,
        sentiment_trend="stable",
        sentiment_trend_note="Steady over 180 days.",
        one_liner="A decent game worth trying.",
        audience_profile=AudienceProfile(
            ideal_player="Strategy fans",
            casual_friendliness="medium",
            archetypes=["Strategist", "Explorer"],
            not_for=["Speedrunners", "Casual players"],
        ),
        design_strengths=["Good mechanics", "Great art"],
        gameplay_friction=["Pacing issues"],
        player_wishlist=["More content"],
        churn_triggers=["Tutorial is too long"],
        technical_issues=[],
        refund_signals=RefundSignals(
            refund_language_frequency="none", primary_refund_drivers=[], risk_level="low"
        ),
        community_health=CommunityHealth(
            overall="not_applicable", signals=[], multiplayer_population="not_applicable"
        ),
        monetization_sentiment=MonetizationSentiment(
            overall="not_applicable", signals=[], dlc_sentiment="not_applicable"
        ),
        content_depth=ContentDepth(
            perceived_length="medium", replayability="medium", value_perception="good", signals=[]
        ),
        dev_priorities=[
            DevPriority(
                action="Fix pacing",
                why_it_matters="Drives churn",
                frequency="common",
                effort="medium",
            )
        ],
        competitive_context=[],
        genre_context="Average for the genre.",
        hidden_gem_score=0.2,
        appid=appid,
    ).model_dump_json()


def _write_pass2_output(s3_client: Any, game_report_json: str, appid: int = 440) -> str:
    """Write a simulated Bedrock batch output JSONL file to moto S3. Returns the output S3 URI."""
    record = json.dumps(
        {
            "recordId": f"{appid}-synthesis",
            "modelOutput": {"content": [{"text": game_report_json}]},
        }
    )
    key = f"jobs/{_EXECUTION_ID}/pass2/output/output.jsonl.out"
    s3_client.put_object(Bucket=_BUCKET, Key=key, Body=record.encode())
    return f"s3://{_BUCKET}/jobs/{_EXECUTION_ID}/pass2/output/"


def _write_scores_json(s3_client: Any, appid: int, scores: dict) -> None:
    key = f"jobs/{_EXECUTION_ID}/pass2/scores.json"
    s3_client.put_object(
        Bucket=_BUCKET,
        Key=key,
        Body=json.dumps({str(appid): scores}).encode(),
    )


# ---------------------------------------------------------------------------
# 1. _parse_s3_uri — pure function (no AWS)
# ---------------------------------------------------------------------------


def test_parse_s3_uri_standard() -> None:
    from lambda_functions.batch_analysis.prepare_pass2 import _parse_s3_uri

    assert _parse_s3_uri("s3://my-bucket/path/to/key") == ("my-bucket", "path/to/key")


def test_parse_s3_uri_no_key() -> None:
    from lambda_functions.batch_analysis.prepare_pass2 import _parse_s3_uri

    assert _parse_s3_uri("s3://my-bucket/") == ("my-bucket", "")


# ---------------------------------------------------------------------------
# 2. _format_chunk_record — pure function (no AWS)
# ---------------------------------------------------------------------------


def test_format_chunk_record_structure() -> None:
    from lambda_functions.batch_analysis.prepare_pass1 import _format_chunk_record

    chunk = [
        {
            "voted_up": True,
            "review_text": "Love it",
            "playtime_hours": 50,
            "votes_helpful": 10,
            "votes_funny": 0,
            "posted_at": "2024-01-01T00:00:00+00:00",
            "written_during_early_access": False,
            "received_for_free": False,
        }
    ]
    record = _format_chunk_record(
        appid=440, chunk=chunk, chunk_index=0, total_chunks=3, game_name="TF2"
    )

    assert record["recordId"] == "440-chunk-0"
    mi = record["modelInput"]
    assert mi["anthropic_version"] == "bedrock-2023-05-31"
    assert mi["max_tokens"] == 1024
    assert mi["system"] == CHUNK_SYSTEM_PROMPT
    assert len(mi["messages"]) == 1
    assert mi["messages"][0]["role"] == "user"
    assert "Love it" in mi["messages"][0]["content"]


# ---------------------------------------------------------------------------
# 3. _build_chunk_user_message — pure function (no AWS)
# ---------------------------------------------------------------------------


def test_build_chunk_user_message_contains_reviews() -> None:
    reviews = [
        {
            "voted_up": True,
            "review_text": "Amazing mechanics and replayability.",
            "playtime_hours": 120,
            "votes_helpful": 42,
            "votes_funny": 3,
            "posted_at": "2024-03-15T00:00:00+00:00",
            "written_during_early_access": False,
            "received_for_free": False,
        }
    ]
    msg = _build_chunk_user_message(reviews, chunk_index=0, total_chunks=1, game_name="Portal 2")
    assert "<reviews>" in msg
    assert "Amazing mechanics" in msg
    assert "Portal 2" in msg


def test_build_chunk_user_message_formats_all_fields() -> None:
    reviews = [
        {
            "voted_up": False,
            "review_text": "Refunded after 2 hours.",
            "playtime_hours": 2,
            "votes_helpful": 5,
            "votes_funny": 0,
            "posted_at": "2024-05-01T00:00:00+00:00",
            "written_during_early_access": True,
            "received_for_free": True,
        }
    ]
    msg = _build_chunk_user_message(reviews, chunk_index=0, total_chunks=1)
    assert "NEGATIVE" in msg
    assert "2h played" in msg
    assert "5 helpful votes" in msg
    assert "Early Access" in msg
    assert "Free Key" in msg
    assert "2024-05-01" in msg


# ---------------------------------------------------------------------------
# 4. check_batch_status handler — inject MagicMock for _bedrock
# ---------------------------------------------------------------------------

import lambda_functions.batch_analysis.check_batch_status as _check_status_module  # noqa: E402


def _make_bedrock_status(raw_status: str, message: str = "") -> MagicMock:
    mock_bedrock = MagicMock()
    mock_bedrock.get_model_invocation_job.return_value = {
        "status": raw_status,
        "message": message or raw_status,
    }
    return mock_bedrock


def test_check_status_completed(lambda_context: Any) -> None:
    _check_status_module._bedrock = _make_bedrock_status("Completed")
    result = _check_status_module.handler({"job_id": "arn:aws:bedrock:job-1"}, lambda_context)
    assert result["status"] == "Completed"


def test_check_status_in_progress_maps_to_running(lambda_context: Any) -> None:
    _check_status_module._bedrock = _make_bedrock_status("InProgress")
    result = _check_status_module.handler({"job_id": "arn:aws:bedrock:job-1"}, lambda_context)
    assert result["status"] == "Running"


def test_check_status_submitted_maps_to_running(lambda_context: Any) -> None:
    _check_status_module._bedrock = _make_bedrock_status("Submitted")
    result = _check_status_module.handler({"job_id": "arn:aws:bedrock:job-1"}, lambda_context)
    assert result["status"] == "Running"


def test_check_status_expired_maps_to_failed(lambda_context: Any) -> None:
    _check_status_module._bedrock = _make_bedrock_status("Expired")
    result = _check_status_module.handler({"job_id": "arn:aws:bedrock:job-1"}, lambda_context)
    assert result["status"] == "Failed"


def test_check_status_unknown_maps_to_failed(lambda_context: Any) -> None:
    _check_status_module._bedrock = _make_bedrock_status("SomeUnknownStatus")
    result = _check_status_module.handler({"job_id": "arn:aws:bedrock:job-1"}, lambda_context)
    assert result["status"] == "Failed"


def test_check_status_partially_completed_maps_to_completed(lambda_context: Any) -> None:
    _check_status_module._bedrock = _make_bedrock_status("PartiallyCompleted")
    result = _check_status_module.handler({"job_id": "arn:aws:bedrock:job-1"}, lambda_context)
    assert result["status"] == "Completed"


# ---------------------------------------------------------------------------
# 5. submit_batch_job handler — inject MagicMock for _bedrock
# ---------------------------------------------------------------------------

import lambda_functions.batch_analysis.submit_batch_job as _submit_module  # noqa: E402


def _submit_event(execution_id: str = _EXECUTION_ID, pass_name: str = "pass1") -> dict:
    return {
        "execution_id": execution_id,
        "pass": pass_name,
        "model_id": "us.anthropic.claude-haiku-test-v1:0",
        "input_s3_uri": f"s3://{_BUCKET}/jobs/{execution_id}/pass1/input.jsonl",
        "output_s3_uri": f"s3://{_BUCKET}/jobs/{execution_id}/pass1/output/",
    }


def test_submit_job_name_format(lambda_context: Any) -> None:
    mock_bedrock = MagicMock()
    mock_bedrock.create_model_invocation_job.return_value = {"jobArn": "arn:aws:bedrock:job-abc"}
    _submit_module._bedrock = mock_bedrock

    result = _submit_module.handler(_submit_event(), lambda_context)

    call_kwargs = mock_bedrock.create_model_invocation_job.call_args[1]
    job_name: str = call_kwargs["jobName"]
    assert job_name.startswith("sp-pass1-")
    # Total length: "sp-pass1-" (9) + 12-char hash = 21
    assert len(job_name) == 21
    assert result["job_id"] == "arn:aws:bedrock:job-abc"


def test_submit_job_name_is_deterministic(lambda_context: Any) -> None:
    mock_bedrock = MagicMock()
    mock_bedrock.create_model_invocation_job.return_value = {"jobArn": "arn:aws:bedrock:job-x"}
    _submit_module._bedrock = mock_bedrock

    event = _submit_event()
    _submit_module.handler(event, lambda_context)
    name1: str = mock_bedrock.create_model_invocation_job.call_args[1]["jobName"]
    _submit_module.handler(event, lambda_context)
    name2: str = mock_bedrock.create_model_invocation_job.call_args[1]["jobName"]

    assert name1 == name2


def test_submit_job_hash_differs_by_pass(lambda_context: Any) -> None:
    mock_bedrock = MagicMock()
    mock_bedrock.create_model_invocation_job.return_value = {"jobArn": "arn:aws:bedrock:job-x"}
    _submit_module._bedrock = mock_bedrock

    _submit_module.handler(_submit_event(pass_name="pass1"), lambda_context)
    name1: str = mock_bedrock.create_model_invocation_job.call_args[1]["jobName"]

    _submit_module.handler(_submit_event(pass_name="pass2"), lambda_context)
    name2: str = mock_bedrock.create_model_invocation_job.call_args[1]["jobName"]

    assert name1 != name2


# ---------------------------------------------------------------------------
# 6. prepare_pass1 handler — @mock_aws + patched DB + mocked repos
# ---------------------------------------------------------------------------


def _load_prepare_pass1() -> Any:
    """Reload prepare_pass1 with get_conn patched (called inside @mock_aws)."""
    with patch("library_layer.utils.db.get_conn", return_value=MagicMock()):
        mod = importlib.import_module("lambda_functions.batch_analysis.prepare_pass1")
        importlib.reload(mod)
    return mod


@mock_aws
def test_prepare_pass1_specific_appids_uploads_jsonl(lambda_context: Any) -> None:
    s3 = boto3.client("s3", region_name=_REGION)
    s3.create_bucket(Bucket=_BUCKET)

    h = _load_prepare_pass1()
    h._s3 = s3
    h._BUCKET = _BUCKET

    mock_game = MagicMock()
    mock_game.name = "Team Fortress 2"
    mock_game_repo = MagicMock()
    mock_game_repo.find_by_appid.return_value = mock_game
    mock_review_repo = MagicMock()
    mock_review_repo.find_by_appid.return_value = [_make_review(appid=440)]

    with (
        patch(
            "lambda_functions.batch_analysis.prepare_pass1.GameRepository",
            return_value=mock_game_repo,
        ),
        patch(
            "lambda_functions.batch_analysis.prepare_pass1.ReviewRepository",
            return_value=mock_review_repo,
        ),
    ):
        result = h.handler({"execution_id": _EXECUTION_ID, "appids": [440]}, lambda_context)

    assert result["total_records"] >= 1
    assert result["input_s3_uri"] == f"s3://{_BUCKET}/jobs/{_EXECUTION_ID}/pass1/input.jsonl"

    obj = s3.get_object(Bucket=_BUCKET, Key=f"jobs/{_EXECUTION_ID}/pass1/input.jsonl")
    record = json.loads(obj["Body"].read().decode().splitlines()[0])
    assert record["recordId"].startswith("440-chunk-")
    assert record["modelInput"]["anthropic_version"] == "bedrock-2023-05-31"


def test_prepare_pass1_rejects_non_list_appids(lambda_context: Any) -> None:
    h = _load_prepare_pass1()

    with pytest.raises(ValueError, match="appids must be a list of integers"):
        h.handler({"execution_id": _EXECUTION_ID, "appids": "ALL_ELIGIBLE"}, lambda_context)


@mock_aws
def test_prepare_pass1_skips_appid_with_no_reviews(lambda_context: Any) -> None:
    s3 = boto3.client("s3", region_name=_REGION)
    s3.create_bucket(Bucket=_BUCKET)

    h = _load_prepare_pass1()
    h._s3 = s3
    h._BUCKET = _BUCKET

    mock_game_repo = MagicMock()
    mock_game_repo.find_by_appid.return_value = MagicMock(name="Empty Game")
    mock_review_repo = MagicMock()
    mock_review_repo.find_by_appid.return_value = []

    with (
        patch(
            "lambda_functions.batch_analysis.prepare_pass1.GameRepository",
            return_value=mock_game_repo,
        ),
        patch(
            "lambda_functions.batch_analysis.prepare_pass1.ReviewRepository",
            return_value=mock_review_repo,
        ),
    ):
        result = h.handler({"execution_id": _EXECUTION_ID, "appids": [999]}, lambda_context)

    assert result["total_records"] == 0


@mock_aws
def test_prepare_pass1_normalizes_body_to_review_text(lambda_context: Any) -> None:
    """Review.body must appear as review_text in the JSONL prompt content."""
    s3 = boto3.client("s3", region_name=_REGION)
    s3.create_bucket(Bucket=_BUCKET)

    h = _load_prepare_pass1()
    h._s3 = s3
    h._BUCKET = _BUCKET

    review = _make_review(appid=440, body="Unique body string xyz")
    mock_game_repo = MagicMock()
    mock_game_repo.find_by_appid.return_value = MagicMock(name="TF2")
    mock_review_repo = MagicMock()
    mock_review_repo.find_by_appid.return_value = [review]

    with (
        patch(
            "lambda_functions.batch_analysis.prepare_pass1.GameRepository",
            return_value=mock_game_repo,
        ),
        patch(
            "lambda_functions.batch_analysis.prepare_pass1.ReviewRepository",
            return_value=mock_review_repo,
        ),
    ):
        h.handler({"execution_id": _EXECUTION_ID, "appids": [440]}, lambda_context)

    obj = s3.get_object(Bucket=_BUCKET, Key=f"jobs/{_EXECUTION_ID}/pass1/input.jsonl")
    record = json.loads(obj["Body"].read().decode().splitlines()[0])
    # review_text content must appear in the LLM prompt
    assert "Unique body string xyz" in record["modelInput"]["messages"][0]["content"]


@mock_aws
def test_prepare_pass1_normalizes_datetime_posted_at_to_iso_string(lambda_context: Any) -> None:
    """posted_at datetime must be converted to ISO string for the prompt."""
    s3 = boto3.client("s3", region_name=_REGION)
    s3.create_bucket(Bucket=_BUCKET)

    h = _load_prepare_pass1()
    h._s3 = s3
    h._BUCKET = _BUCKET

    review = _make_review(appid=440, posted_at=datetime(2024, 3, 15, tzinfo=UTC))
    mock_game_repo = MagicMock()
    mock_game_repo.find_by_appid.return_value = MagicMock(name="TF2")
    mock_review_repo = MagicMock()
    mock_review_repo.find_by_appid.return_value = [review]

    with (
        patch(
            "lambda_functions.batch_analysis.prepare_pass1.GameRepository",
            return_value=mock_game_repo,
        ),
        patch(
            "lambda_functions.batch_analysis.prepare_pass1.ReviewRepository",
            return_value=mock_review_repo,
        ),
    ):
        h.handler({"execution_id": _EXECUTION_ID, "appids": [440]}, lambda_context)

    obj = s3.get_object(Bucket=_BUCKET, Key=f"jobs/{_EXECUTION_ID}/pass1/input.jsonl")
    record = json.loads(obj["Body"].read().decode().splitlines()[0])
    assert "2024-03-15" in record["modelInput"]["messages"][0]["content"]


@mock_aws
def test_prepare_pass1_sorts_reviews_chronologically(lambda_context: Any) -> None:
    """Reviews are sorted oldest-first so temporal signals are preserved."""
    s3 = boto3.client("s3", region_name=_REGION)
    s3.create_bucket(Bucket=_BUCKET)

    h = _load_prepare_pass1()
    h._s3 = s3
    h._BUCKET = _BUCKET

    newer = _make_review(
        appid=440, body="Newer review", posted_at=datetime(2024, 12, 1, tzinfo=UTC)
    )
    older = _make_review(appid=440, body="Older review", posted_at=datetime(2024, 1, 1, tzinfo=UTC))
    mock_game_repo = MagicMock()
    mock_game_repo.find_by_appid.return_value = MagicMock(name="TF2")
    mock_review_repo = MagicMock()
    # Pass in reverse order — handler should sort them
    mock_review_repo.find_by_appid.return_value = [newer, older]

    with (
        patch(
            "lambda_functions.batch_analysis.prepare_pass1.GameRepository",
            return_value=mock_game_repo,
        ),
        patch(
            "lambda_functions.batch_analysis.prepare_pass1.ReviewRepository",
            return_value=mock_review_repo,
        ),
    ):
        h.handler({"execution_id": _EXECUTION_ID, "appids": [440]}, lambda_context)

    obj = s3.get_object(Bucket=_BUCKET, Key=f"jobs/{_EXECUTION_ID}/pass1/input.jsonl")
    record = json.loads(obj["Body"].read().decode().splitlines()[0])
    content: str = record["modelInput"]["messages"][0]["content"]
    assert content.index("Older review") < content.index("Newer review")


# ---------------------------------------------------------------------------
# 7. process_results handler — @mock_aws + patched DB + mock SNS/repo
# ---------------------------------------------------------------------------

# Cache the imported module — module-level get_conn/get_parameter run only once.
_process_results_cached: Any = None


def _load_process_results() -> Any:
    """Import process_results once with get_conn and get_parameter patched."""
    global _process_results_cached
    if _process_results_cached is None:
        with (
            patch("library_layer.utils.db.get_conn", return_value=MagicMock()),
            patch(
                "aws_lambda_powertools.utilities.parameters.get_parameter",
                side_effect=lambda p: _SSM_PARAMS.get(p, p),
            ),
        ):
            mod = importlib.import_module("lambda_functions.batch_analysis.process_results")
            importlib.reload(mod)
            _process_results_cached = mod
    return _process_results_cached


def _configure_process_results(h: Any, s3_client: Any, mock_sns: Any) -> None:
    """Inject per-test AWS clients and static config into the handler module."""
    h._s3 = s3_client
    h._sns = mock_sns
    h._content_events_topic_arn = "arn:aws:sns:us-east-1:123:content-events"
    h._system_events_topic_arn = "arn:aws:sns:us-east-1:123:system-events"
    h._BUCKET = _BUCKET
    h._conn = MagicMock()


def _handler_event() -> dict:
    return {
        "pass2_output_s3_uri": f"s3://{_BUCKET}/jobs/{_EXECUTION_ID}/pass2/output/",
        "execution_id": _EXECUTION_ID,
    }


@mock_aws
def test_process_results_applies_precomputed_scores(lambda_context: Any) -> None:
    s3 = boto3.client("s3", region_name=_REGION)
    s3.create_bucket(Bucket=_BUCKET)
    mock_sns = MagicMock()

    # LLM output has hidden_gem_score=0.2 — precomputed overrides with 0.3 + trend
    _write_pass2_output(s3, _minimal_game_report_json(appid=440), appid=440)
    _write_scores_json(
        s3,
        440,
        {
            "hidden_gem_score": 0.3,
            "sentiment_trend": "improving",
            "sentiment_trend_note": "Sentiment rose.",
            "sentiment_trend_reliable": True,
            "sentiment_trend_sample_size": 200,
        },
    )

    h = _load_process_results()
    _configure_process_results(h, s3, mock_sns)

    mock_repo = MagicMock()
    mock_game_repo_pr = MagicMock()
    mock_game_repo_pr.find_for_revenue_estimate.return_value = None  # skip revenue estimate
    mock_tag_repo_pr = MagicMock()
    with (
        patch(
            "lambda_functions.batch_analysis.process_results.ReportRepository",
            return_value=mock_repo,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.GameRepository",
            return_value=mock_game_repo_pr,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.TagRepository",
            return_value=mock_tag_repo_pr,
        ),
    ):
        result = h.handler(_handler_event(), lambda_context)

    assert result["processed"] == 1
    assert result["failed"] == 0

    upserted: dict = mock_repo.upsert.call_args[0][0]
    assert upserted["hidden_gem_score"] == 0.3
    assert upserted["sentiment_trend"] == "improving"
    assert upserted["sentiment_trend_reliable"] is True
    assert "sentiment_score" not in upserted
    assert "overall_sentiment" not in upserted


@mock_aws
def test_process_results_uses_llm_values_when_no_scores(lambda_context: Any) -> None:
    """When scores.json is absent, LLM-provided values are kept as-is."""
    s3 = boto3.client("s3", region_name=_REGION)
    s3.create_bucket(Bucket=_BUCKET)
    mock_sns = MagicMock()

    _write_pass2_output(s3, _minimal_game_report_json(appid=440), appid=440)
    # No scores.json — _read_scores_from_s3 will catch the error and return {}

    h = _load_process_results()
    _configure_process_results(h, s3, mock_sns)

    mock_repo = MagicMock()
    mock_game_repo_pr = MagicMock()
    mock_game_repo_pr.find_for_revenue_estimate.return_value = None  # skip revenue estimate
    mock_tag_repo_pr = MagicMock()
    with (
        patch(
            "lambda_functions.batch_analysis.process_results.ReportRepository",
            return_value=mock_repo,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.GameRepository",
            return_value=mock_game_repo_pr,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.TagRepository",
            return_value=mock_tag_repo_pr,
        ),
    ):
        result = h.handler(_handler_event(), lambda_context)

    assert result["processed"] == 1
    upserted: dict = mock_repo.upsert.call_args[0][0]
    assert upserted["hidden_gem_score"] == 0.2  # LLM value kept (no override)


@mock_aws
def test_process_results_skips_unrecognised_record_ids(lambda_context: Any) -> None:
    """Records with non-matching recordId format are skipped (not counted as failed)."""
    s3 = boto3.client("s3", region_name=_REGION)
    s3.create_bucket(Bucket=_BUCKET)
    mock_sns = MagicMock()

    bad_record = json.dumps(
        {"recordId": "bad-format", "modelOutput": {"content": [{"text": "{}"}]}}
    )
    s3.put_object(
        Bucket=_BUCKET,
        Key=f"jobs/{_EXECUTION_ID}/pass2/output/output.jsonl.out",
        Body=bad_record.encode(),
    )

    h = _load_process_results()
    _configure_process_results(h, s3, mock_sns)

    mock_repo = MagicMock()
    mock_game_repo_pr = MagicMock()
    mock_game_repo_pr.find_for_revenue_estimate.return_value = None  # skip revenue estimate
    mock_tag_repo_pr = MagicMock()
    with (
        patch(
            "lambda_functions.batch_analysis.process_results.ReportRepository",
            return_value=mock_repo,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.GameRepository",
            return_value=mock_game_repo_pr,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.TagRepository",
            return_value=mock_tag_repo_pr,
        ),
    ):
        result = h.handler(_handler_event(), lambda_context)

    assert result["processed"] == 0
    assert result["failed"] == 0  # skipped, not failed
    mock_repo.upsert.assert_not_called()


@mock_aws
def test_process_results_handles_failed_records(lambda_context: Any) -> None:
    """Invalid model output increments the failed counter and collects the appid."""
    s3 = boto3.client("s3", region_name=_REGION)
    s3.create_bucket(Bucket=_BUCKET)
    mock_sns = MagicMock()

    broken_record = json.dumps(
        {
            "recordId": "440-synthesis",
            "modelOutput": {"content": [{"text": "NOT_VALID_JSON{{{"}]},
        }
    )
    s3.put_object(
        Bucket=_BUCKET,
        Key=f"jobs/{_EXECUTION_ID}/pass2/output/output.jsonl.out",
        Body=broken_record.encode(),
    )

    h = _load_process_results()
    _configure_process_results(h, s3, mock_sns)

    mock_repo = MagicMock()
    mock_game_repo_pr = MagicMock()
    mock_game_repo_pr.find_for_revenue_estimate.return_value = None  # skip revenue estimate
    mock_tag_repo_pr = MagicMock()
    with (
        patch(
            "lambda_functions.batch_analysis.process_results.ReportRepository",
            return_value=mock_repo,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.GameRepository",
            return_value=mock_game_repo_pr,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.TagRepository",
            return_value=mock_tag_repo_pr,
        ),
    ):
        result = h.handler(_handler_event(), lambda_context)

    assert result["processed"] == 0
    assert result["failed"] == 1
    assert 440 in result["failed_appids"]


@mock_aws
def test_process_results_publishes_report_ready_per_game(lambda_context: Any) -> None:
    s3 = boto3.client("s3", region_name=_REGION)
    s3.create_bucket(Bucket=_BUCKET)
    mock_sns = MagicMock()

    _write_pass2_output(s3, _minimal_game_report_json(appid=440), appid=440)

    h = _load_process_results()
    _configure_process_results(h, s3, mock_sns)

    mock_repo = MagicMock()
    mock_game_repo_pr = MagicMock()
    mock_game_repo_pr.find_for_revenue_estimate.return_value = None  # skip revenue estimate
    mock_tag_repo_pr = MagicMock()
    with (
        patch(
            "lambda_functions.batch_analysis.process_results.ReportRepository",
            return_value=mock_repo,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.GameRepository",
            return_value=mock_game_repo_pr,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.TagRepository",
            return_value=mock_tag_repo_pr,
        ),
    ):
        h.handler(_handler_event(), lambda_context)

    all_publishes = mock_sns.publish.call_args_list
    report_ready_calls = [
        c for c in all_publishes if json.loads(c.kwargs["Message"]).get("event") == "report-ready"
    ]
    assert len(report_ready_calls) == 1
    assert json.loads(report_ready_calls[0].kwargs["Message"])["appid"] == 440


@mock_aws
def test_process_results_publishes_batch_complete_summary(lambda_context: Any) -> None:
    s3 = boto3.client("s3", region_name=_REGION)
    s3.create_bucket(Bucket=_BUCKET)
    mock_sns = MagicMock()

    _write_pass2_output(s3, _minimal_game_report_json(appid=440), appid=440)

    h = _load_process_results()
    _configure_process_results(h, s3, mock_sns)

    mock_repo = MagicMock()
    mock_game_repo_pr = MagicMock()
    mock_game_repo_pr.find_for_revenue_estimate.return_value = None  # skip revenue estimate
    mock_tag_repo_pr = MagicMock()
    with (
        patch(
            "lambda_functions.batch_analysis.process_results.ReportRepository",
            return_value=mock_repo,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.GameRepository",
            return_value=mock_game_repo_pr,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.TagRepository",
            return_value=mock_tag_repo_pr,
        ),
    ):
        result = h.handler(_handler_event(), lambda_context)

    batch_complete_calls = [
        c
        for c in mock_sns.publish.call_args_list
        if json.loads(c.kwargs["Message"]).get("event") == "batch-complete"
    ]
    assert len(batch_complete_calls) == 1
    payload = json.loads(batch_complete_calls[0].kwargs["Message"])
    assert payload["processed"] == result["processed"]
    assert payload["execution_id"] == _EXECUTION_ID


@mock_aws
def test_process_results_returns_processed_and_failed_counts(lambda_context: Any) -> None:
    s3 = boto3.client("s3", region_name=_REGION)
    s3.create_bucket(Bucket=_BUCKET)
    mock_sns = MagicMock()

    _write_pass2_output(s3, _minimal_game_report_json(appid=440), appid=440)

    h = _load_process_results()
    _configure_process_results(h, s3, mock_sns)

    mock_repo = MagicMock()
    mock_game_repo_pr = MagicMock()
    mock_game_repo_pr.find_for_revenue_estimate.return_value = None  # skip revenue estimate
    mock_tag_repo_pr = MagicMock()
    with (
        patch(
            "lambda_functions.batch_analysis.process_results.ReportRepository",
            return_value=mock_repo,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.GameRepository",
            return_value=mock_game_repo_pr,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.TagRepository",
            return_value=mock_tag_repo_pr,
        ),
    ):
        result = h.handler(_handler_event(), lambda_context)

    assert "processed" in result
    assert "failed" in result
    assert "failed_appids" in result
    assert isinstance(result["failed_appids"], list)


@mock_aws
def test_process_results_persists_revenue_estimate(lambda_context: Any) -> None:
    """When a game + tags/genres are available, process_results should compute
    a Boxleiter estimate and call update_revenue_estimate with the values."""
    from decimal import Decimal

    from library_layer.models.game import Game

    s3 = boto3.client("s3", region_name=_REGION)
    s3.create_bucket(Bucket=_BUCKET)
    mock_sns = MagicMock()

    _write_pass2_output(s3, _minimal_game_report_json(appid=440), appid=440)

    h = _load_process_results()
    _configure_process_results(h, s3, mock_sns)

    mock_repo = MagicMock()
    mock_game_repo_pr = MagicMock()
    # Minimal Game that clears all the estimator guards so compute_estimate
    # produces non-None values. Indie default bucket, 1000 reviews * 30.
    mock_game_repo_pr.find_for_revenue_estimate.return_value = Game.model_validate(
        {
            "appid": 440,
            "name": "TF2",
            "slug": "tf2",
            "type": "game",
            "price_usd": Decimal("10.00"),
            "is_free": False,
            "review_count": 1000,
            "release_date": "2024-01-01",
        }
    )
    mock_tag_repo_pr = MagicMock()
    mock_tag_repo_pr.find_genres_for_appids.return_value = {440: []}
    mock_tag_repo_pr.find_tags_for_appids.return_value = {440: []}

    with (
        patch(
            "lambda_functions.batch_analysis.process_results.ReportRepository",
            return_value=mock_repo,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.GameRepository",
            return_value=mock_game_repo_pr,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.TagRepository",
            return_value=mock_tag_repo_pr,
        ),
    ):
        h.handler(_handler_event(), lambda_context)

    # Bulk helpers called once with the full appid list, not per record.
    mock_tag_repo_pr.find_genres_for_appids.assert_called_once_with([440])
    mock_tag_repo_pr.find_tags_for_appids.assert_called_once_with([440])

    # Single bulk UPDATE + commit per batch (not per row).
    mock_game_repo_pr.bulk_update_revenue_estimates.assert_called_once()
    (rows,) = mock_game_repo_pr.bulk_update_revenue_estimates.call_args.args
    assert len(rows) == 1
    appid, owners, revenue_usd, method, reason = rows[0]
    assert appid == 440
    assert owners == 30_000  # indie (30) * 1000 reviews
    assert revenue_usd == Decimal("300000.00")
    assert method == "boxleiter_v1"
    assert reason is None


@mock_aws
def test_process_results_revenue_estimate_null_for_free_game(lambda_context: Any) -> None:
    """Free-to-play games land with owners=None and revenue_usd=None so the
    repo writes a NULL method downstream."""
    from library_layer.models.game import Game

    s3 = boto3.client("s3", region_name=_REGION)
    s3.create_bucket(Bucket=_BUCKET)
    mock_sns = MagicMock()

    _write_pass2_output(s3, _minimal_game_report_json(appid=440), appid=440)

    h = _load_process_results()
    _configure_process_results(h, s3, mock_sns)

    mock_repo = MagicMock()
    mock_game_repo_pr = MagicMock()
    mock_game_repo_pr.find_for_revenue_estimate.return_value = Game.model_validate(
        {
            "appid": 440,
            "name": "TF2",
            "slug": "tf2",
            "type": "game",
            "price_usd": None,
            "is_free": True,
            "review_count": 1000,
            "release_date": "2024-01-01",
        }
    )
    mock_tag_repo_pr = MagicMock()
    mock_tag_repo_pr.find_genres_for_appids.return_value = {440: []}
    mock_tag_repo_pr.find_tags_for_appids.return_value = {440: []}

    with (
        patch(
            "lambda_functions.batch_analysis.process_results.ReportRepository",
            return_value=mock_repo,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.GameRepository",
            return_value=mock_game_repo_pr,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.TagRepository",
            return_value=mock_tag_repo_pr,
        ),
    ):
        h.handler(_handler_event(), lambda_context)

    (rows,) = mock_game_repo_pr.bulk_update_revenue_estimates.call_args.args
    assert len(rows) == 1
    _, owners, revenue_usd, method, reason = rows[0]
    assert owners is None
    assert revenue_usd is None
    # Estimator still returns a method; the repo layer's bulk writer is
    # responsible for coercing it to NULL when both value fields are None.
    assert method == "boxleiter_v1"
    assert reason == "free_to_play"


@mock_aws
def test_process_results_revenue_estimate_failure_does_not_block_batch_complete(
    lambda_context: Any,
) -> None:
    """Systemic failure in the revenue-estimate pass must not abort the
    handler — the batch-complete SNS event must still fire and the result
    should still report the successful record."""
    s3 = boto3.client("s3", region_name=_REGION)
    s3.create_bucket(Bucket=_BUCKET)
    mock_sns = MagicMock()

    _write_pass2_output(s3, _minimal_game_report_json(appid=440), appid=440)

    h = _load_process_results()
    _configure_process_results(h, s3, mock_sns)

    mock_repo = MagicMock()
    mock_game_repo_pr = MagicMock()
    # Force the bulk update path to raise (e.g. lost DB connection).
    mock_game_repo_pr.find_for_revenue_estimate.side_effect = RuntimeError("boom")
    mock_tag_repo_pr = MagicMock()
    mock_tag_repo_pr.find_genres_for_appids.return_value = {440: []}
    mock_tag_repo_pr.find_tags_for_appids.return_value = {440: []}

    with (
        patch(
            "lambda_functions.batch_analysis.process_results.ReportRepository",
            return_value=mock_repo,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.GameRepository",
            return_value=mock_game_repo_pr,
        ),
        patch(
            "lambda_functions.batch_analysis.process_results.TagRepository",
            return_value=mock_tag_repo_pr,
        ),
    ):
        result = h.handler(_handler_event(), lambda_context)

    # Handler did not raise: report is still counted as processed.
    assert result["processed"] == 1
    assert result["failed"] == 0

    # batch-complete still published.
    batch_complete_calls = [
        c
        for c in mock_sns.publish.call_args_list
        if json.loads(c.kwargs["Message"]).get("event") == "batch-complete"
    ]
    assert len(batch_complete_calls) == 1
