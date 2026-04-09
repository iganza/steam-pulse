"""Tests for batch_analysis/prepare_phase.py — the parametrized prepare Lambda.

Covers the four contracts called out in PR review:
  1. chunk phase returns skip=true when all chunks are cache-hits
  2. chunk phase submits a Bedrock batch job when pending chunks exist
  3. merge phase always runs inline via ConverseBackend and returns skip=true
  4. synthesis phase raises cleanly when no merged summary exists

Tests stub the repos + ConverseBackend / BatchBackend at module level (the
same pattern the ingest_handler tests use) so no real AWS/DB calls happen.
"""

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from library_layer.models.analyzer_models import (
    MergedSummary,
    RichBatchStats,
    RichChunkSummary,
    TopicSignal,
)
from library_layer.utils.chunking import (
    compute_chunk_hash,
    dataset_reference_time,
    stratified_chunk_reviews,
)


def _get_module() -> Any:
    import lambda_functions.batch_analysis.prepare_phase as pp

    return pp


def _empty_summary(label: str = "t") -> RichChunkSummary:
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


def _db_review(rid: str, *, voted_up: bool = True) -> Any:
    """Mimic the subset of `Review` that `_prepare_chunk` reads."""
    r = MagicMock()
    r.steam_review_id = rid
    r.voted_up = voted_up
    r.body = f"review body {rid}"
    r.playtime_hours = 10
    r.votes_helpful = 1
    r.votes_funny = 0
    r.posted_at = datetime.fromisoformat("2025-01-01T00:00:00+00:00")
    r.written_during_early_access = False
    r.received_for_free = False
    return r


def _install_fake_game(pp: Any) -> None:
    game = MagicMock()
    game.name = "Test Game"
    pp._game_repo = MagicMock()
    pp._game_repo.find_by_appid.return_value = game


def _install_fake_reviews(pp: Any, count: int) -> None:
    pp._review_repo = MagicMock()
    pp._review_repo.find_by_appid.return_value = [
        _db_review(f"r{i}", voted_up=i % 2 == 0) for i in range(count)
    ]


def _install_fake_backend(pp: Any) -> MagicMock:
    backend = MagicMock()
    backend.prepare.return_value = "s3://bucket/key"
    backend.submit.return_value = "arn:aws:bedrock:...:job/abc"
    pp._backend_for = MagicMock(return_value=backend)
    return backend


# ---------------------------------------------------------------------------
# Chunk phase
# ---------------------------------------------------------------------------


def test_prepare_chunk_returns_skip_when_all_chunks_cached() -> None:
    pp = _get_module()
    _install_fake_game(pp)
    # 60 reviews at chunk_size=50 → 2 chunks (50 + 10 remainder).
    _install_fake_reviews(pp, count=60)

    # Pre-seed the cache with hashes that match EVERY chunk prepare would
    # build. We compute them the exact same way prepare does.
    reviews_for_chunk_build = [
        {
            "steam_review_id": r.steam_review_id,
            "voted_up": r.voted_up,
            "review_text": r.body,
            "playtime_hours": r.playtime_hours or 0,
            "votes_helpful": r.votes_helpful,
            "votes_funny": r.votes_funny,
            "posted_at": r.posted_at.isoformat(),
            "written_during_early_access": r.written_during_early_access,
            "received_for_free": r.received_for_free,
        }
        for r in pp._review_repo.find_by_appid.return_value
    ]
    chunks = stratified_chunk_reviews(
        reviews_for_chunk_build,
        chunk_size=pp._analyzer_settings.chunk_size,
        reference_time=dataset_reference_time(reviews_for_chunk_build),
        seed=pp._analyzer_settings.shuffle_seed,
    )
    cached_rows = [
        {
            "chunk_hash": compute_chunk_hash(c),
            "summary_json": _empty_summary().model_dump(mode="json"),
        }
        for c in chunks
    ]
    pp._chunk_repo = MagicMock()
    pp._chunk_repo.find_by_appid.return_value = cached_rows

    backend = _install_fake_backend(pp)

    result = pp.handler(
        {"appid": 440, "phase": "chunk", "execution_id": "exec-1"},
        context=None,
    )
    assert result["skip"] is True
    assert result["job_id"] is None
    # Cache hit → no Bedrock call.
    backend.prepare.assert_not_called()
    backend.submit.assert_not_called()


def test_prepare_chunk_submits_when_pending_exist() -> None:
    pp = _get_module()
    _install_fake_game(pp)
    _install_fake_reviews(pp, count=100)
    pp._chunk_repo = MagicMock()
    pp._chunk_repo.find_by_appid.return_value = []  # no cached rows
    backend = _install_fake_backend(pp)

    result = pp.handler(
        {"appid": 440, "phase": "chunk", "execution_id": "exec-2"},
        context=None,
    )
    assert result["skip"] is False
    assert result["job_id"] == "arn:aws:bedrock:...:job/abc"
    backend.prepare.assert_called_once()
    backend.submit.assert_called_once()
    # Sanity: every pending LLMRequest was a chunking task.
    pending_requests = backend.prepare.call_args.args[0]
    assert all(req.task == "chunking" for req in pending_requests)


# ---------------------------------------------------------------------------
# Merge phase (inline via ConverseBackend)
# ---------------------------------------------------------------------------


def test_prepare_merge_always_returns_skip_and_persists() -> None:
    pp = _get_module()
    _install_fake_game(pp)

    # One cached chunk → single-chunk promotion path (no LLM call needed).
    pp._chunk_repo = MagicMock()
    pp._chunk_repo.find_by_appid.return_value = [
        {"id": 42, "summary_json": _empty_summary("solo").model_dump(mode="json")}
    ]
    pp._merge_repo = MagicMock()
    pp._merge_repo.find_latest_by_source_ids.return_value = None
    pp._merge_repo.insert.return_value = 99

    # The BatchBackend should NEVER be touched for the merge phase.
    batch_backend = _install_fake_backend(pp)

    result = pp.handler(
        {"appid": 440, "phase": "merge", "execution_id": "exec-3"},
        context=None,
    )
    assert result["skip"] is True
    assert result["job_id"] is None
    batch_backend.prepare.assert_not_called()
    batch_backend.submit.assert_not_called()
    # Promotion row was persisted via the inline Converse path.
    pp._merge_repo.insert.assert_called_once()
    insert_call = pp._merge_repo.insert.call_args
    assert insert_call.kwargs["model_id"] == "python-promotion"


def test_prepare_merge_raises_when_no_chunk_summaries_exist() -> None:
    pp = _get_module()
    _install_fake_game(pp)
    pp._chunk_repo = MagicMock()
    pp._chunk_repo.find_by_appid.return_value = []
    _install_fake_backend(pp)

    with pytest.raises(ValueError, match="no chunk_summaries"):
        pp.handler(
            {"appid": 440, "phase": "merge", "execution_id": "exec-4"},
            context=None,
        )


# ---------------------------------------------------------------------------
# Synthesis phase
# ---------------------------------------------------------------------------


def test_prepare_synthesis_raises_when_no_merged_summary() -> None:
    pp = _get_module()
    _install_fake_game(pp)
    pp._merge_repo = MagicMock()
    pp._merge_repo.find_latest_by_appid.return_value = None
    _install_fake_backend(pp)

    with pytest.raises(ValueError, match="No merged_summary"):
        pp.handler(
            {"appid": 440, "phase": "synthesis", "execution_id": "exec-5"},
            context=None,
        )


def test_prepare_synthesis_submits_when_merged_summary_exists() -> None:
    pp = _get_module()
    _install_fake_game(pp)
    # Attach a positive_pct / review_count so sentiment context has real values
    pp._game_repo.find_by_appid.return_value.positive_pct = 85
    pp._game_repo.find_by_appid.return_value.review_count = 500
    pp._game_repo.find_by_appid.return_value.review_score_desc = "Very Positive"

    merged = MergedSummary(
        topics=[],
        competitor_refs=[],
        notable_quotes=[],
        total_stats=RichBatchStats(),
        merge_level=1,
        chunks_merged=3,
        source_chunk_ids=[1, 2, 3],
    )
    pp._merge_repo = MagicMock()
    pp._merge_repo.find_latest_by_appid.return_value = {
        "id": 7,
        "summary_json": merged.model_dump(mode="json"),
    }
    _install_fake_reviews(pp, count=10)
    pp._review_repo.find_review_velocity = MagicMock(return_value={"summary": {}})
    pp._review_repo.find_early_access_impact = MagicMock(return_value={})
    # Game needs release_date / coming_soon for build_temporal_context.
    pp._game_repo.find_by_appid.return_value.release_date = None
    pp._game_repo.find_by_appid.return_value.coming_soon = False
    backend = _install_fake_backend(pp)

    result = pp.handler(
        {"appid": 440, "phase": "synthesis", "execution_id": "exec-6"},
        context=None,
    )
    assert result["skip"] is False
    assert result["job_id"] == "arn:aws:bedrock:...:job/abc"
    # The merged_summary_id we synthesised against is threaded through
    # the payload so collect_phase doesn't race on find_latest_by_appid.
    assert result["merged_summary_id"] == 7
    backend.prepare.assert_called_once()
    backend.submit.assert_called_once()
    # Exactly one synthesis request submitted.
    submitted_requests = backend.prepare.call_args.args[0]
    assert len(submitted_requests) == 1
    assert submitted_requests[0].task == "summarizer"


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_handler_rejects_unknown_phase() -> None:
    pp = _get_module()
    _install_fake_backend(pp)
    with pytest.raises(ValueError, match="Unknown phase"):
        pp.handler(
            {"appid": 440, "phase": "bogus", "execution_id": "exec-7"},
            context=None,
        )
