"""Tests for GenreSynthesisService — prepare + collect batch lifecycle."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from aws_lambda_powertools import Metrics
from library_layer.config import SteamPulseConfig
from library_layer.llm.backend import BatchCollectResult
from library_layer.models.genre_synthesis import (
    BenchmarkGame,
    ChurnInsight,
    DevPriority,
    FrictionPoint,
    GenreSynthesis,
    WishlistItem,
)
from library_layer.models.report import Report
from library_layer.services.genre_synthesis_service import (
    GENRE_SYNTHESIS_PHASE,
    GenreSynthesisService,
    NotEnoughReportsError,
    PrepareResult,
    UnknownPromptVersionError,
    _compute_input_hash,
)


class FakeBatchBackend:
    """Minimal stand-in for AnthropicBatchBackend — records calls, returns canned output.

    Mirrors the three methods the service touches in these tests —
    ``prepare`` / ``submit`` / ``collect``. ``status`` isn't exercised
    here (the per-slug SFN owns polling via the shared check_status
    Lambda), so the fake doesn't implement it. Tests drive
    ``collect_response`` to control what ``collect_batch`` sees from the
    Anthropic batch result iterator.
    """

    def __init__(
        self,
        *,
        job_id: str = "msgbatch_test_001",
        collect_response: BatchCollectResult | None = None,
    ) -> None:
        self.job_id = job_id
        self.collect_response = collect_response
        self.prepare_calls: list[tuple[list[Any], str]] = []
        self.submit_calls: list[tuple[list[Any], Any, str]] = []
        self.collect_calls: list[tuple[str, Any]] = []

    def prepare(self, requests: list[Any], *, phase: str) -> list[dict]:
        self.prepare_calls.append((requests, phase))
        return [{"custom_id": r.record_id, "params": {}} for r in requests]

    def submit(self, prepared: list[dict], task: Any, *, phase: str) -> str:
        self.submit_calls.append((prepared, task, phase))
        return self.job_id

    def collect(
        self,
        batch_id: str,
        *,
        default_response_model: Any = None,
    ) -> BatchCollectResult:
        self.collect_calls.append((batch_id, default_response_model))
        if self.collect_response is None:
            raise RuntimeError("FakeBatchBackend.collect called without collect_response set")
        return self.collect_response


def _canned_synthesis() -> GenreSynthesis:
    return GenreSynthesis(
        narrative_summary="Runs are long; players want shareable seeds.",
        friction_points=[
            FrictionPoint(
                title="Run length",
                description="Too long",
                representative_quote="90 minutes is too much",
                source_appid=1001,
                mention_count=5,
            )
        ],
        wishlist_items=[
            WishlistItem(
                title="Daily seed",
                description="Share runs",
                representative_quote="Let us share seeds",
                source_appid=1002,
                mention_count=3,
            )
        ],
        benchmark_games=[
            BenchmarkGame(appid=646570, name="Slay the Spire", why_benchmark="Defines pacing")
        ],
        churn_insight=ChurnInsight(
            typical_dropout_hour=8.0,
            primary_reason="Grind",
            representative_quote="Stopped at hour 8",
            source_appid=1001,
        ),
        dev_priorities=[
            DevPriority(
                action="Add daily seed", why_it_matters="Share", frequency=3, effort="medium"
            )
        ],
    )


def _canned_collect_result(synthesis: GenreSynthesis) -> BatchCollectResult:
    return BatchCollectResult(
        results=[("genre_synthesis:roguelike-deckbuilder:v1", synthesis)],
        failed_ids=[],
        skipped=0,
        input_tokens=12345,
        output_tokens=678,
        cache_read_tokens=200,
        cache_write_tokens=100,
    )


@pytest.fixture
def service_parts() -> dict[str, Any]:
    config = SteamPulseConfig(
        MIN_REPORTS_PER_GENRE=3,
        MAX_REPORTS_PER_GENRE=10,
        GENRE_SYNTHESIS_MAX_TOKENS=8000,
        GENRE_SYNTHESIS_PROMPT_VERSION="v1",
        GENRE_SYNTHESIS_MIN_GAME_REVIEW_COUNT=100,
        # Pin to a model ID present in _BATCH_PRICING so collect_batch
        # can estimate cost without tripping the unknown-model guard.
        LLM_MODEL={"genre_synthesis": "claude-sonnet-4-6"},
    )
    report_repo = MagicMock()
    tag_repo = MagicMock()
    game_repo = MagicMock()
    synthesis_repo = MagicMock()
    batch_exec_repo = MagicMock()
    metrics = Metrics(namespace="SteamPulseTest", service="genre-synthesis-test")
    canned = _canned_synthesis()
    backend = FakeBatchBackend(collect_response=_canned_collect_result(canned))

    tag_repo.find_eligible_for_synthesis.return_value = [1001, 1002, 1003]
    tag_repo.find_display_name_for_slug.return_value = "Roguelike Deckbuilder"

    report_repo.find_by_appid.side_effect = lambda appid: Report.model_validate(
        {"appid": appid, "report_json": {"one_liner": f"Game {appid}"}}
    )
    game_repo.find_review_stats_for_appids.return_value = [
        {"appid": 1001, "positive_pct": 90, "review_count": 5000},
        {"appid": 1002, "positive_pct": 85, "review_count": 3000},
        {"appid": 1003, "positive_pct": 80, "review_count": 1500},
    ]
    synthesis_repo.get_by_slug.return_value = None

    service = GenreSynthesisService(
        report_repo=report_repo,
        tag_repo=tag_repo,
        game_repo=game_repo,
        synthesis_repo=synthesis_repo,
        batch_exec_repo=batch_exec_repo,
        config=config,
        metrics=metrics,
        required_pipeline_version="3.0/test",
    )
    return {
        "service": service,
        "backend": backend,
        "synthesis_repo": synthesis_repo,
        "batch_exec_repo": batch_exec_repo,
        "tag_repo": tag_repo,
        "game_repo": game_repo,
        "canned": canned,
    }


# ── prepare_batch ────────────────────────────────────────────────────────────


def test_prepare_batch_submits_and_inserts_tracking_row(service_parts: dict[str, Any]) -> None:
    svc: GenreSynthesisService = service_parts["service"]
    backend: FakeBatchBackend = service_parts["backend"]
    batch_exec_repo = service_parts["batch_exec_repo"]

    result = svc.prepare_batch(
        slug="roguelike-deckbuilder",
        prompt_version="v1",
        execution_id="exec-abc",
        backend=backend,  # type: ignore[arg-type]
    )

    assert isinstance(result, PrepareResult)
    assert result.skip is False
    assert result.job_id == "msgbatch_test_001"
    assert result.slug == "roguelike-deckbuilder"
    assert result.display_name == "Roguelike Deckbuilder"
    assert result.selected_appids == [1001, 1002, 1003]
    assert result.avg_positive_pct == pytest.approx(85.0)
    assert result.median_review_count == 3000
    assert result.input_hash  # non-empty
    assert result.execution_id == "exec-abc"

    assert len(backend.prepare_calls) == 1
    assert len(backend.submit_calls) == 1
    _prepared, task, phase = backend.submit_calls[0]
    assert task == "genre_synthesis"
    assert phase == GENRE_SYNTHESIS_PHASE

    batch_exec_repo.insert.assert_called_once()
    insert_kwargs = batch_exec_repo.insert.call_args.kwargs
    assert insert_kwargs["slug"] == "roguelike-deckbuilder"
    assert insert_kwargs["phase"] == GENRE_SYNTHESIS_PHASE
    assert insert_kwargs["batch_id"] == "msgbatch_test_001"
    assert insert_kwargs["request_count"] == 1
    assert insert_kwargs["execution_id"] == "exec-abc"
    assert insert_kwargs["prompt_version"] == "v1"
    # No appid for slug-keyed rows.
    assert insert_kwargs.get("appid") is None


def test_prepare_batch_returns_job_id_when_tracking_insert_fails(
    service_parts: dict[str, Any],
) -> None:
    """If the tracking-row insert fails (transient DB error), the Lambda
    must still return the submitted job_id so Step Functions doesn't
    retry-and-resubmit a new batch, doubling the LLM spend."""
    svc: GenreSynthesisService = service_parts["service"]
    backend: FakeBatchBackend = service_parts["backend"]
    batch_exec_repo = service_parts["batch_exec_repo"]
    batch_exec_repo.insert.side_effect = RuntimeError("transient DB error")

    result = svc.prepare_batch(
        slug="roguelike-deckbuilder",
        prompt_version="v1",
        execution_id="exec-abc",
        backend=backend,  # type: ignore[arg-type]
    )

    # Batch was submitted — job_id must be threaded forward even though
    # the tracking row never landed.
    assert result.skip is False
    assert result.job_id == "msgbatch_test_001"
    assert len(backend.submit_calls) == 1
    batch_exec_repo.insert.assert_called_once()


def test_prepare_batch_cache_hit_skips_and_bumps_timestamp(
    service_parts: dict[str, Any],
) -> None:
    svc: GenreSynthesisService = service_parts["service"]
    backend: FakeBatchBackend = service_parts["backend"]
    synthesis_repo = service_parts["synthesis_repo"]
    batch_exec_repo = service_parts["batch_exec_repo"]

    # First call — build and submit.
    svc.prepare_batch(
        slug="roguelike-deckbuilder",
        prompt_version="v1",
        execution_id="exec-1",
        backend=backend,  # type: ignore[arg-type]
    )

    # Seed the repo mock so the cache check hits on the next call.
    stored_row = MagicMock()
    stored_row.input_hash = _compute_input_hash(
        prompt_version="v1",
        pipeline_version="3.0/test",
        appids=[1001, 1002, 1003],
    )
    synthesis_repo.get_by_slug.return_value = stored_row

    backend.prepare_calls.clear()
    backend.submit_calls.clear()
    batch_exec_repo.insert.reset_mock()

    second = svc.prepare_batch(
        slug="roguelike-deckbuilder",
        prompt_version="v1",
        execution_id="exec-2",
        backend=backend,  # type: ignore[arg-type]
    )

    assert second.skip is True
    assert second.job_id == ""
    assert backend.prepare_calls == []
    assert backend.submit_calls == []
    batch_exec_repo.insert.assert_not_called()
    synthesis_repo.touch_computed_at.assert_called_once()


def test_prepare_batch_input_set_change_resubmits(service_parts: dict[str, Any]) -> None:
    """A new appid in the eligible set changes input_hash → new batch submitted."""
    svc: GenreSynthesisService = service_parts["service"]
    backend: FakeBatchBackend = service_parts["backend"]
    synthesis_repo = service_parts["synthesis_repo"]
    tag_repo = service_parts["tag_repo"]
    game_repo = service_parts["game_repo"]

    first = svc.prepare_batch(
        slug="roguelike-deckbuilder",
        prompt_version="v1",
        execution_id="exec-1",
        backend=backend,  # type: ignore[arg-type]
    )
    # Seed the repo so the cache check runs — but input_hash will differ.
    stored_row = MagicMock()
    stored_row.input_hash = first.input_hash
    synthesis_repo.get_by_slug.return_value = stored_row

    tag_repo.find_eligible_for_synthesis.return_value = [1001, 1002, 1003, 1004]
    game_repo.find_review_stats_for_appids.return_value = [
        {"appid": 1001, "positive_pct": 90, "review_count": 5000},
        {"appid": 1002, "positive_pct": 85, "review_count": 3000},
        {"appid": 1003, "positive_pct": 80, "review_count": 1500},
        {"appid": 1004, "positive_pct": 92, "review_count": 8000},
    ]
    second = svc.prepare_batch(
        slug="roguelike-deckbuilder",
        prompt_version="v1",
        execution_id="exec-2",
        backend=backend,  # type: ignore[arg-type]
    )

    assert second.skip is False
    assert second.input_hash != first.input_hash
    assert len(backend.submit_calls) == 2


def test_prepare_batch_unknown_prompt_version_raises(service_parts: dict[str, Any]) -> None:
    svc: GenreSynthesisService = service_parts["service"]
    backend: FakeBatchBackend = service_parts["backend"]
    with pytest.raises(UnknownPromptVersionError):
        svc.prepare_batch(
            slug="roguelike-deckbuilder",
            prompt_version="v99",
            execution_id="exec-x",
            backend=backend,  # type: ignore[arg-type]
        )


def test_prepare_batch_refuses_below_minimum(service_parts: dict[str, Any]) -> None:
    svc: GenreSynthesisService = service_parts["service"]
    backend: FakeBatchBackend = service_parts["backend"]
    service_parts["tag_repo"].find_eligible_for_synthesis.return_value = [1001]
    with pytest.raises(NotEnoughReportsError):
        svc.prepare_batch(
            slug="roguelike-deckbuilder",
            prompt_version="v1",
            execution_id="exec-x",
            backend=backend,  # type: ignore[arg-type]
        )


# ── collect_batch ────────────────────────────────────────────────────────────


def test_collect_batch_upserts_row_and_marks_completed(service_parts: dict[str, Any]) -> None:
    svc: GenreSynthesisService = service_parts["service"]
    backend: FakeBatchBackend = service_parts["backend"]
    synthesis_repo = service_parts["synthesis_repo"]
    batch_exec_repo = service_parts["batch_exec_repo"]

    row = svc.collect_batch(
        slug="roguelike-deckbuilder",
        job_id="msgbatch_test_001",
        selected_appids=[1001, 1002, 1003],
        display_name="Roguelike Deckbuilder",
        avg_positive_pct=85.0,
        median_review_count=3000,
        input_hash="hash-abc",
        prompt_version="v1",
        backend=backend,  # type: ignore[arg-type]
    )

    assert row.slug == "roguelike-deckbuilder"
    assert row.display_name == "Roguelike Deckbuilder"
    assert row.input_appids == [1001, 1002, 1003]
    assert row.input_count == 3
    assert row.input_hash == "hash-abc"
    assert row.prompt_version == "v1"
    assert row.synthesis.narrative_summary.startswith("Runs are long")
    assert row.avg_positive_pct == pytest.approx(85.0)
    assert row.median_review_count == 3000

    synthesis_repo.upsert.assert_called_once()
    batch_exec_repo.mark_completed.assert_called_once()
    mark_kwargs = batch_exec_repo.mark_completed.call_args.kwargs
    assert mark_kwargs["succeeded_count"] == 1
    assert mark_kwargs["failed_count"] == 0
    assert mark_kwargs["input_tokens"] == 12345
    assert mark_kwargs["output_tokens"] == 678
    assert mark_kwargs["cache_read_tokens"] == 200
    assert mark_kwargs["cache_write_tokens"] == 100
    assert mark_kwargs["estimated_cost_usd"] > 0


def test_collect_batch_unknown_model_does_not_strand_row(
    service_parts: dict[str, Any],
) -> None:
    """An unknown model_id raises in estimate_batch_cost_usd. The tracking
    row must still reach a terminal state (cost=0, mark_completed runs)
    rather than being stuck in 'submitted'."""
    config = SteamPulseConfig(
        MIN_REPORTS_PER_GENRE=3,
        MAX_REPORTS_PER_GENRE=10,
        GENRE_SYNTHESIS_MAX_TOKENS=8000,
        GENRE_SYNTHESIS_PROMPT_VERSION="v1",
        GENRE_SYNTHESIS_MIN_GAME_REVIEW_COUNT=100,
        # Model not in _BATCH_PRICING — exercises the safety net.
        LLM_MODEL={"genre_synthesis": "unknown-pricing-model"},
    )
    svc = GenreSynthesisService(
        report_repo=MagicMock(),
        tag_repo=MagicMock(),
        game_repo=MagicMock(),
        synthesis_repo=service_parts["synthesis_repo"],
        batch_exec_repo=service_parts["batch_exec_repo"],
        config=config,
        metrics=service_parts["service"]._metrics,
        required_pipeline_version="3.0/test",
    )

    canned = service_parts["canned"]
    backend = FakeBatchBackend(
        collect_response=BatchCollectResult(
            results=[("genre_synthesis:roguelike-deckbuilder:v1", canned)],
            failed_ids=[],
            skipped=0,
            input_tokens=12345,
            output_tokens=678,
            cache_read_tokens=200,
            cache_write_tokens=100,
        )
    )
    svc.collect_batch(
        slug="roguelike-deckbuilder",
        job_id="msgbatch_test_001",
        selected_appids=[1001, 1002, 1003],
        display_name="Roguelike Deckbuilder",
        avg_positive_pct=85.0,
        median_review_count=3000,
        input_hash="hash-abc",
        prompt_version="v1",
        backend=backend,  # type: ignore[arg-type]
    )

    # mark_completed still runs with cost=0 so the row reaches terminal state.
    service_parts["batch_exec_repo"].mark_completed.assert_called_once()
    mark_kwargs = service_parts["batch_exec_repo"].mark_completed.call_args.kwargs
    assert mark_kwargs["estimated_cost_usd"] == 0


def test_collect_batch_multiple_results_marks_failed(
    service_parts: dict[str, Any],
) -> None:
    """prepare_batch submits one request per slug; more than one result
    means the backend returned something we didn't ask for. Bail rather
    than silently persist results[0]."""
    svc: GenreSynthesisService = service_parts["service"]
    canned = service_parts["canned"]
    bogus_backend = FakeBatchBackend(
        collect_response=BatchCollectResult(
            results=[
                ("genre_synthesis:roguelike-deckbuilder:v1", canned),
                ("genre_synthesis:stowaway:v1", canned),
            ],
            failed_ids=[],
            skipped=0,
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=0,
            cache_write_tokens=0,
        )
    )
    with pytest.raises(RuntimeError, match="Expected exactly 1"):
        svc.collect_batch(
            slug="roguelike-deckbuilder",
            job_id="msgbatch_test_001",
            selected_appids=[1001, 1002, 1003],
            display_name="Roguelike Deckbuilder",
            avg_positive_pct=85.0,
            median_review_count=3000,
            input_hash="hash-abc",
            prompt_version="v1",
            backend=bogus_backend,  # type: ignore[arg-type]
        )
    # Counts reflect the validated outcome — NOT len(collect_result.results).
    mark_kwargs = service_parts["batch_exec_repo"].mark_completed.call_args.kwargs
    assert mark_kwargs["succeeded_count"] == 0
    assert mark_kwargs["failed_count"] == 2
    assert "genre_synthesis:stowaway:v1" in mark_kwargs["failed_record_ids"]
    service_parts["batch_exec_repo"].mark_failed.assert_called_once()


def test_collect_batch_record_id_mismatch_marks_failed(
    service_parts: dict[str, Any],
) -> None:
    """Result's record_id must match the one prepare_batch submitted."""
    svc: GenreSynthesisService = service_parts["service"]
    canned = service_parts["canned"]
    wrong_id_backend = FakeBatchBackend(
        collect_response=BatchCollectResult(
            results=[("genre_synthesis:wrong-slug:v1", canned)],
            failed_ids=[],
            skipped=0,
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=0,
            cache_write_tokens=0,
        )
    )
    with pytest.raises(RuntimeError, match="record_id mismatch"):
        svc.collect_batch(
            slug="roguelike-deckbuilder",
            job_id="msgbatch_test_001",
            selected_appids=[1001, 1002, 1003],
            display_name="Roguelike Deckbuilder",
            avg_positive_pct=85.0,
            median_review_count=3000,
            input_hash="hash-abc",
            prompt_version="v1",
            backend=wrong_id_backend,  # type: ignore[arg-type]
        )
    mark_kwargs = service_parts["batch_exec_repo"].mark_completed.call_args.kwargs
    assert mark_kwargs["succeeded_count"] == 0
    assert mark_kwargs["failed_count"] == 1
    assert "genre_synthesis:wrong-slug:v1" in mark_kwargs["failed_record_ids"]
    service_parts["batch_exec_repo"].mark_failed.assert_called_once()


def test_collect_batch_no_results_marks_failed(service_parts: dict[str, Any]) -> None:
    svc: GenreSynthesisService = service_parts["service"]
    batch_exec_repo = service_parts["batch_exec_repo"]
    empty_backend = FakeBatchBackend(
        collect_response=BatchCollectResult(
            results=[],
            failed_ids=["genre_synthesis:roguelike-deckbuilder:v1"],
            skipped=1,
            input_tokens=100,
            output_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
        )
    )
    with pytest.raises(RuntimeError, match="No genre_synthesis output"):
        svc.collect_batch(
            slug="roguelike-deckbuilder",
            job_id="msgbatch_test_001",
            selected_appids=[1001, 1002, 1003],
            display_name="Roguelike Deckbuilder",
            avg_positive_pct=85.0,
            median_review_count=3000,
            input_hash="hash-abc",
            prompt_version="v1",
            backend=empty_backend,  # type: ignore[arg-type]
        )
    # mark_completed still recorded token usage first, then mark_failed
    # was called with the error reason.
    batch_exec_repo.mark_completed.assert_called_once()
    batch_exec_repo.mark_failed.assert_called_once()


# ── Constructor guard + hash invariants (unchanged) ──────────────────────────


def test_service_rejects_min_reports_below_mention_floor(
    service_parts: dict[str, Any],
) -> None:
    """Constructor guard: MIN_REPORTS_PER_GENRE < SHARED_SIGNAL_MIN_MENTIONS
    is rejected because the LLM tool_use schema cannot satisfy
    mention_count >= 3 from fewer than 3 input reports."""
    config = SteamPulseConfig(
        MIN_REPORTS_PER_GENRE=2,
        MAX_REPORTS_PER_GENRE=10,
        GENRE_SYNTHESIS_MAX_TOKENS=8000,
        GENRE_SYNTHESIS_PROMPT_VERSION="v1",
        GENRE_SYNTHESIS_MIN_GAME_REVIEW_COUNT=100,
    )
    with pytest.raises(ValueError, match="MIN_REPORTS_PER_GENRE"):
        GenreSynthesisService(
            report_repo=MagicMock(),
            tag_repo=MagicMock(),
            game_repo=MagicMock(),
            synthesis_repo=MagicMock(),
            batch_exec_repo=MagicMock(),
            config=config,
            metrics=service_parts["service"]._metrics,
            required_pipeline_version="3.0/test",
        )


def test_compute_input_hash_stable_and_order_independent() -> None:
    def h(**kwargs: object) -> str:
        return _compute_input_hash(
            prompt_version=kwargs.get("prompt_version", "v1"),  # type: ignore[arg-type]
            pipeline_version=kwargs.get("pipeline_version", "3.0/test"),  # type: ignore[arg-type]
            appids=kwargs.get("appids", [1, 2, 3]),  # type: ignore[arg-type]
        )

    a = h()
    assert a == h()
    assert a == h(appids=[3, 1, 2])
    assert a == h(appids=[2, 3, 1])
    assert a != h(prompt_version="v2")
    assert a != h(pipeline_version="3.0/other")
