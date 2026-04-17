"""Tests for GenreSynthesisService — cache-hit short-circuit + happy path."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from aws_lambda_powertools import Metrics
from library_layer.config import SteamPulseConfig
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
    GenreSynthesisService,
    NotEnoughReportsError,
    UnknownPromptVersionError,
    _compute_input_hash,
)


class FakeBackend:
    """Minimal stand-in for ConverseBackend — records calls, returns canned output."""

    def __init__(self, response: GenreSynthesis) -> None:
        self._response = response
        self.calls: list[Any] = []

    def run(self, requests: list[Any], *, on_result: Any = None) -> list[GenreSynthesis]:
        self.calls.append(requests)
        return [self._response]


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


@pytest.fixture
def service_parts(monkeypatch: pytest.MonkeyPatch) -> dict:
    config = SteamPulseConfig(
        MIN_REPORTS_PER_GENRE=2,
        MAX_REPORTS_PER_GENRE=10,
        GENRE_SYNTHESIS_MAX_TOKENS=8000,
        GENRE_SYNTHESIS_PROMPT_VERSION="v1",
        GENRE_SYNTHESIS_MIN_GAME_REVIEW_COUNT=100,
    )
    report_repo = MagicMock()
    tag_repo = MagicMock()
    game_repo = MagicMock()
    synthesis_repo = MagicMock()
    metrics = Metrics(namespace="SteamPulseTest", service="genre-synthesis-test")
    canned = _canned_synthesis()
    backend = FakeBackend(canned)

    # Return the three eligible appids in review-count-desc order.
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
        llm_backend=backend,  # type: ignore[arg-type]
        config=config,
        metrics=metrics,
        required_pipeline_version="3.0/test",
    )
    return {
        "service": service,
        "backend": backend,
        "synthesis_repo": synthesis_repo,
        "tag_repo": tag_repo,
        "canned": canned,
    }


def test_synthesize_happy_path(service_parts: dict) -> None:
    svc: GenreSynthesisService = service_parts["service"]
    backend: FakeBackend = service_parts["backend"]
    synthesis_repo = service_parts["synthesis_repo"]

    row = svc.synthesize(slug="roguelike-deckbuilder", prompt_version="v1")

    assert row.slug == "roguelike-deckbuilder"
    assert row.display_name == "Roguelike Deckbuilder"
    assert row.input_appids == [1001, 1002, 1003]
    assert row.input_count == 3
    assert row.prompt_version == "v1"
    assert row.synthesis.narrative_summary.startswith("Runs are long")
    # Median of [5000, 3000, 1500] = 3000
    assert row.median_review_count == 3000
    # Mean of [90, 85, 80] = 85.0
    assert row.avg_positive_pct == pytest.approx(85.0)

    assert len(backend.calls) == 1
    synthesis_repo.upsert.assert_called_once()


def test_synthesize_cache_short_circuits(service_parts: dict) -> None:
    """Re-running with the same input set hits the cache and skips the LLM."""
    svc: GenreSynthesisService = service_parts["service"]
    backend: FakeBackend = service_parts["backend"]
    synthesis_repo = service_parts["synthesis_repo"]

    # First run — real synth.
    first_row = svc.synthesize(slug="roguelike-deckbuilder", prompt_version="v1")
    # Seed the repo mock so get_by_slug returns the row we just upserted.
    synthesis_repo.get_by_slug.return_value = first_row
    synthesis_repo.upsert.reset_mock()

    second = svc.synthesize(slug="roguelike-deckbuilder", prompt_version="v1")

    assert len(backend.calls) == 1  # still just one LLM call
    assert second.input_hash == first_row.input_hash
    synthesis_repo.upsert.assert_not_called()


def test_synthesize_input_set_change_triggers_rerun(service_parts: dict) -> None:
    svc: GenreSynthesisService = service_parts["service"]
    backend: FakeBackend = service_parts["backend"]
    synthesis_repo = service_parts["synthesis_repo"]
    tag_repo = service_parts["tag_repo"]

    first = svc.synthesize(slug="roguelike-deckbuilder", prompt_version="v1")
    synthesis_repo.get_by_slug.return_value = first

    # New appid enters the eligible set — input_hash changes, LLM re-runs.
    tag_repo.find_eligible_for_synthesis.return_value = [1001, 1002, 1003, 1004]
    # Extend game stats so _compute_aggregates has data for the new appid.
    service_parts["service"]._game_repo.find_review_stats_for_appids.return_value = [
        {"appid": 1001, "positive_pct": 90, "review_count": 5000},
        {"appid": 1002, "positive_pct": 85, "review_count": 3000},
        {"appid": 1003, "positive_pct": 80, "review_count": 1500},
        {"appid": 1004, "positive_pct": 92, "review_count": 8000},
    ]
    svc.synthesize(slug="roguelike-deckbuilder", prompt_version="v1")

    assert len(backend.calls) == 2


def test_synthesize_unknown_prompt_version_raises(service_parts: dict) -> None:
    svc: GenreSynthesisService = service_parts["service"]
    with pytest.raises(UnknownPromptVersionError):
        svc.synthesize(slug="roguelike-deckbuilder", prompt_version="v99")


def test_synthesize_refuses_below_minimum(service_parts: dict) -> None:
    svc: GenreSynthesisService = service_parts["service"]
    # Drop eligible to 1 — below MIN_REPORTS_PER_GENRE=2.
    service_parts["tag_repo"].find_eligible_for_synthesis.return_value = [1001]
    with pytest.raises(NotEnoughReportsError):
        svc.synthesize(slug="roguelike-deckbuilder", prompt_version="v1")


def test_compute_input_hash_stable_and_order_independent() -> None:
    a = _compute_input_hash(prompt_version="v1", appids=[1, 2, 3])
    b = _compute_input_hash(prompt_version="v1", appids=[1, 2, 3])
    assert a == b
    # Same set, permuted order — function sorts internally.
    assert a == _compute_input_hash(prompt_version="v1", appids=[3, 1, 2])
    assert a == _compute_input_hash(prompt_version="v1", appids=[2, 3, 1])
    # Version bump changes the hash.
    c = _compute_input_hash(prompt_version="v2", appids=[1, 2, 3])
    assert a != c
