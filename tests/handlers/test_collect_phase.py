"""Tests for batch_analysis/collect_phase.py — the parametrized collect Lambda.

Covers the three contracts called out in PR review:
  1. chunk collection persists rows using metadata parsed from record_id;
     malformed ids are dropped (never raise).
  2. synthesis collection applies Python score overrides, writes
     pipeline-bookkeeping keys via ReportRepository.upsert.
  3. publish-event failure is swallowed — the pipeline completes.

Follows the test_ingest_handler pattern: moto's `mock_aws` wraps each test
so the module-level `get_parameter(CONTENT_EVENTS_TOPIC_PARAM_NAME)` call
that runs at import time resolves against a seeded SSM parameter.
"""

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import boto3
from library_layer.models.analyzer_models import (
    AudienceProfile,
    CommunityHealth,
    ContentDepth,
    DevPriority,
    GameReport,
    MonetizationSentiment,
    RefundSignals,
    RichBatchStats,
    RichChunkSummary,
    TopicSignal,
)
from library_layer.utils.events import EventPublishError
from moto import mock_aws


def _seed_ssm() -> None:
    ssm = boto3.client("ssm", region_name="us-east-1")
    ssm.put_parameter(
        Name="/steampulse/test/messaging/content-events-topic-arn",
        Value="arn:aws:sns:us-east-1:123:content-events",
        Type="String",
        Overwrite=True,
    )


def _get_module() -> Any:
    _seed_ssm()
    import lambda_functions.batch_analysis.collect_phase as cp

    return cp


def _empty_chunk_summary(label: str = "t") -> RichChunkSummary:
    return RichChunkSummary(
        topics=[
            TopicSignal(
                topic=label,
                category="design_praise",
                sentiment="positive",
                mention_count=1,
                confidence="low",
                summary="ok",
            )
        ],
        competitor_refs=[],
        notable_quotes=[],
        batch_stats=RichBatchStats(positive_count=1, negative_count=0),
    )


def _minimal_game_report() -> GameReport:
    """The smallest valid GameReport the synthesis collect path can handle."""
    return GameReport(
        game_name="TF2",
        total_reviews_analyzed=10,
        sentiment_trend="stable",
        sentiment_trend_note="steady",
        one_liner="A class-based shooter.",
        audience_profile=AudienceProfile(
            ideal_player="FPS fans",
            casual_friendliness="medium",
            archetypes=["competitive", "casual"],
            not_for=["tactical sim fans", "solo-only players"],
        ),
        design_strengths=["class variety", "map design"],
        gameplay_friction=["bot problem"],
        player_wishlist=["new maps"],
        churn_triggers=["bots in casual"],
        technical_issues=[],
        refund_signals=RefundSignals(
            refund_language_frequency="none",
            primary_refund_drivers=[],
            risk_level="low",
        ),
        community_health=CommunityHealth(
            overall="active",
            signals=["active community"],
            multiplayer_population="healthy",
        ),
        monetization_sentiment=MonetizationSentiment(
            overall="fair",
            signals=["fair cosmetics"],
            dlc_sentiment="not_applicable",
        ),
        content_depth=ContentDepth(
            perceived_length="endless",
            replayability="high",
            value_perception="excellent",
            signals=["tons of content"],
            confidence="high",
            sample_size=5,
        ),
        dev_priorities=[
            DevPriority(
                action="Fix bots",
                why_it_matters="Ruins casual play",
                frequency="constant",
                effort="high",
            )
        ],
        genre_context="Strong class-based shooter.",
    )


def _stub_backend(cp: Any) -> MagicMock:
    backend = MagicMock()
    cp._backend_for = MagicMock(return_value=backend)
    return backend


def _install_fake_game(cp: Any) -> Any:
    game = MagicMock()
    game.name = "TF2"
    game.positive_pct = 85
    game.review_count = 500
    game.review_score_desc = "Very Positive"
    cp._game_repo = MagicMock()
    cp._game_repo.find_by_appid.return_value = game
    return game


# ---------------------------------------------------------------------------
# Chunk collection
# ---------------------------------------------------------------------------


@mock_aws
def test_collect_chunk_persists_rows_from_record_id_metadata() -> None:
    cp = _get_module()
    cp._chunk_repo = MagicMock()

    backend = _stub_backend(cp)
    backend.collect.return_value = [
        ("440-chunk-0-50-abc123def4567890", _empty_chunk_summary("c0")),
        ("440-chunk-1-50-fedcba9876543210", _empty_chunk_summary("c1")),
    ]

    result = cp.handler(
        {
            "appid": 440,
            "phase": "chunk",
            "execution_id": "exec-1",
            "job_id": "arn:aws:bedrock:...:job/abc",
        },
        context=None,
    )
    assert result["collected"] == 2
    assert cp._chunk_repo.insert.call_count == 2
    # Every insert used the hash parsed from record_id (not re-computed).
    first_call = cp._chunk_repo.insert.call_args_list[0]
    assert first_call.args[0] == 440  # appid
    assert first_call.args[1] == 0  # chunk_index
    assert first_call.args[2] == "abc123def4567890"  # chunk_hash from record_id
    assert first_call.args[3] == 50  # chunk_size


@mock_aws
def test_collect_chunk_drops_malformed_record_ids() -> None:
    cp = _get_module()
    cp._chunk_repo = MagicMock()

    backend = _stub_backend(cp)
    backend.collect.return_value = [
        ("garbage-record-id", _empty_chunk_summary("bad")),
        ("440-chunk-0-50-goodhash12345678", _empty_chunk_summary("good")),
    ]

    result = cp.handler(
        {
            "appid": 440,
            "phase": "chunk",
            "execution_id": "exec-2",
            "job_id": "arn:aws:bedrock:...:job/abc",
        },
        context=None,
    )
    # Only the well-formed record was persisted.
    assert result["collected"] == 1
    assert cp._chunk_repo.insert.call_count == 1


@mock_aws
def test_collect_chunk_drops_record_id_with_wrong_appid() -> None:
    cp = _get_module()
    cp._chunk_repo = MagicMock()
    backend = _stub_backend(cp)
    backend.collect.return_value = [
        ("999-chunk-0-50-abc123def4567890", _empty_chunk_summary("wrong")),
    ]
    result = cp.handler(
        {
            "appid": 440,
            "phase": "chunk",
            "execution_id": "exec-3",
            "job_id": "arn:aws:bedrock:...:job/abc",
        },
        context=None,
    )
    assert result["collected"] == 0
    cp._chunk_repo.insert.assert_not_called()


# ---------------------------------------------------------------------------
# Synthesis collection
# ---------------------------------------------------------------------------


def _db_review(rid: str, *, voted_up: bool = True) -> Any:
    r = MagicMock()
    r.steam_review_id = rid
    r.voted_up = voted_up
    r.posted_at = datetime.fromisoformat("2025-01-01T00:00:00+00:00")
    return r


def _install_fake_reviews_for_synth(cp: Any) -> None:
    cp._review_repo = MagicMock()
    cp._review_repo.find_by_appid.return_value = [_db_review(f"r{i}") for i in range(5)]


@mock_aws
def test_collect_synthesis_upserts_report_with_pipeline_bookkeeping() -> None:
    cp = _get_module()
    _install_fake_game(cp)
    _install_fake_reviews_for_synth(cp)

    cp._report_repo = MagicMock()
    cp._merge_repo = MagicMock()
    cp._merge_repo.find_latest_by_appid.return_value = {"id": 99}
    cp._chunk_repo = MagicMock()
    cp._chunk_repo.find_by_appid.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]
    cp._sns = MagicMock()

    backend = _stub_backend(cp)
    backend.collect.return_value = [("440-synthesis", _minimal_game_report())]

    result = cp.handler(
        {
            "appid": 440,
            "phase": "synthesis",
            "execution_id": "exec-4",
            "job_id": "arn:aws:bedrock:...:job/abc",
        },
        context=None,
    )
    assert result["done"] is True
    assert result["collected"] == 1

    # upsert was called once with pipeline-bookkeeping keys injected.
    cp._report_repo.upsert.assert_called_once()
    payload = cp._report_repo.upsert.call_args.args[0]
    assert payload["pipeline_version"]  # non-empty
    assert payload["merged_summary_id"] == 99
    assert payload["chunk_count"] == 3
    # Python overrides were applied to the returned report before upsert.
    assert payload["appid"] == 440
    assert "hidden_gem_score" in payload
    assert "sentiment_trend" in payload


@mock_aws
def test_collect_synthesis_tolerates_event_publish_failure() -> None:
    """If SNS publish_event raises EventPublishError, the collect handler
    MUST NOT propagate the exception — the report is already persisted
    and the pipeline is considered complete."""
    cp = _get_module()
    _install_fake_game(cp)
    _install_fake_reviews_for_synth(cp)

    cp._report_repo = MagicMock()
    cp._merge_repo = MagicMock()
    cp._merge_repo.find_latest_by_appid.return_value = {"id": 99}
    cp._chunk_repo = MagicMock()
    cp._chunk_repo.find_by_appid.return_value = [{"id": 1}]

    # Force publish_event to raise.
    import lambda_functions.batch_analysis.collect_phase as cp_mod

    original_publish = cp_mod.publish_event

    def _boom(*args: object, **kwargs: object) -> None:
        raise EventPublishError("simulated SNS outage")

    cp_mod.publish_event = _boom  # type: ignore[assignment]
    try:
        backend = _stub_backend(cp)
        backend.collect.return_value = [("440-synthesis", _minimal_game_report())]

        # Must NOT raise.
        result = cp.handler(
            {
                "appid": 440,
                "phase": "synthesis",
                "execution_id": "exec-5",
                "job_id": "arn:aws:bedrock:...:job/abc",
            },
            context=None,
        )
        assert result["done"] is True
        cp._report_repo.upsert.assert_called_once()
    finally:
        cp_mod.publish_event = original_publish  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


@mock_aws
def test_handler_rejects_merge_phase() -> None:
    """Merge is handled inline by prepare_phase; collect_phase must
    never route a merge event."""
    cp = _get_module()
    _stub_backend(cp)
    try:
        cp.handler(
            {
                "appid": 440,
                "phase": "merge",
                "execution_id": "exec-6",
                "job_id": "arn:aws:bedrock:...:job/abc",
            },
            context=None,
        )
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "Unknown phase" in str(exc)
