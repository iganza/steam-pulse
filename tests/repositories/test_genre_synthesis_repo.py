"""Tests for GenreSynthesisRepository + TagRepository.find_eligible_for_synthesis."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from library_layer.models.genre_synthesis import (
    BenchmarkGame,
    ChurnInsight,
    DevPriority,
    FrictionPoint,
    GenreSynthesis,
    GenreSynthesisRow,
    WishlistItem,
)
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.genre_synthesis_repo import (
    GenreSynthesisRepository,
)
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.tag_repo import TagRepository


@pytest.fixture
def genre_synthesis_repo(db_conn: Any) -> GenreSynthesisRepository:
    return GenreSynthesisRepository(lambda: db_conn)


def _seed_game(
    game_repo: GameRepository,
    *,
    appid: int,
    name: str,
    review_count: int,
) -> None:
    game_repo.upsert(
        {
            "appid": appid,
            "name": name,
            "slug": f"{name.lower().replace(' ', '-')}-{appid}",
            "type": "game",
            "developer": "Dev",
            "developer_slug": "dev",
            "publisher": "Pub",
            "publisher_slug": "pub",
            "developers": "[]",
            "publishers": "[]",
            "website": None,
            "release_date": None,
            "release_date_raw": None,
            "coming_soon": False,
            "price_usd": 19.99,
            "is_free": False,
            "short_desc": None,
            "detailed_description": None,
            "about_the_game": None,
            "review_count": review_count,
            "review_count_english": review_count,
            "total_positive": int(review_count * 0.9),
            "total_negative": int(review_count * 0.1),
            "positive_pct": 90,
            "review_score_desc": "Very Positive",
            "header_image": None,
            "background_image": None,
            "required_age": 0,
            "platforms": "{}",
            "supported_languages": None,
            "achievements_total": 0,
            "metacritic_score": None,
            "deck_compatibility": None,
            "deck_test_results": None,
            "content_descriptor_ids": None,
            "content_descriptor_notes": None,
            "controller_support": None,
            "dlc_appids": None,
            "parent_appid": None,
            "capsule_image": None,
            "recommendations_total": None,
            "support_url": None,
            "support_email": None,
            "legal_notice": None,
            "requirements_windows": None,
            "requirements_mac": None,
            "requirements_linux": None,
            "data_source": "steam_direct",
        }
    )


def _sample_synthesis() -> GenreSynthesis:
    return GenreSynthesis(
        narrative_summary="Players love tight runs and hate grind.",
        friction_points=[
            FrictionPoint(
                title="Run length too long",
                description="Runs routinely exceed 90 minutes.",
                representative_quote="2-hour runs are brutal on mobile.",
                source_appid=1001,
                mention_count=5,
            )
        ],
        wishlist_items=[
            WishlistItem(
                title="Daily seed",
                description="Shared seed for leaderboard comparison.",
                representative_quote="I wish runs were shareable.",
                source_appid=1002,
                mention_count=4,
            )
        ],
        benchmark_games=[
            BenchmarkGame(appid=646570, name="Slay the Spire", why_benchmark="Defines pacing"),
        ],
        churn_insight=ChurnInsight(
            typical_dropout_hour=8.0,
            primary_reason="Unlock grind",
            representative_quote="Stopped at hour 8.",
            source_appid=1001,
        ),
        dev_priorities=[
            DevPriority(
                action="Add daily seed",
                why_it_matters="Shareability",
                frequency=3,
                effort="medium",
            )
        ],
    )


def _sample_row(slug: str = "roguelike-deckbuilder") -> GenreSynthesisRow:
    synthesis = _sample_synthesis()
    return GenreSynthesisRow(
        slug=slug,
        display_name="Roguelike Deckbuilder",
        input_appids=[1001, 1002, 1003],
        input_count=3,
        prompt_version="v1",
        input_hash="abc123",
        synthesis=synthesis,
        narrative_summary=synthesis.narrative_summary,
        avg_positive_pct=88.5,
        median_review_count=1200,
        computed_at=datetime.now(UTC),
    )


def test_upsert_then_get_roundtrip(
    genre_synthesis_repo: GenreSynthesisRepository,
) -> None:
    row = _sample_row()
    genre_synthesis_repo.upsert(row)

    got = genre_synthesis_repo.get_by_slug("roguelike-deckbuilder")
    assert got is not None
    assert got.slug == "roguelike-deckbuilder"
    assert got.input_count == 3
    assert got.input_appids == [1001, 1002, 1003]
    assert got.synthesis.friction_points[0].mention_count == 5
    assert got.synthesis.benchmark_games[0].name == "Slay the Spire"
    assert got.avg_positive_pct == pytest.approx(88.5)
    assert got.input_hash == "abc123"
    # computed_at is persisted from the Python model (not DB NOW()), so the
    # roundtrip timestamp matches what the service sets at synthesis time.
    assert got.computed_at == row.computed_at


def test_get_by_slug_missing_returns_none(
    genre_synthesis_repo: GenreSynthesisRepository,
) -> None:
    assert genre_synthesis_repo.get_by_slug("does-not-exist") is None


def test_upsert_overwrites_on_conflict(
    genre_synthesis_repo: GenreSynthesisRepository,
) -> None:
    genre_synthesis_repo.upsert(_sample_row())
    updated = _sample_row()
    updated.input_hash = "def456"
    updated.input_count = 42
    genre_synthesis_repo.upsert(updated)

    got = genre_synthesis_repo.get_by_slug("roguelike-deckbuilder")
    assert got is not None
    assert got.input_hash == "def456"
    assert got.input_count == 42


def test_find_stale_returns_old_rows(
    db_conn: Any, genre_synthesis_repo: GenreSynthesisRepository
) -> None:
    # Insert a fresh row and a stale row, assert find_stale(7) only returns the stale one.
    fresh = _sample_row(slug="fresh-slug")
    stale = _sample_row(slug="stale-slug")
    genre_synthesis_repo.upsert(fresh)
    genre_synthesis_repo.upsert(stale)

    # Backdate the stale row by 14 days.
    with db_conn.cursor() as cur:
        cur.execute(
            "UPDATE mv_genre_synthesis SET computed_at = %s WHERE slug = %s",
            (datetime.now(UTC) - timedelta(days=14), "stale-slug"),
        )
    db_conn.commit()

    stale_slugs = genre_synthesis_repo.find_stale(max_age_days=7)
    assert stale_slugs == ["stale-slug"]


def test_find_eligible_for_synthesis_filters_and_sorts(
    db_conn: Any,
    game_repo: GameRepository,
    tag_repo: TagRepository,
    report_repo: ReportRepository,
) -> None:
    # Seed three games with the same tag, two with reports, one without.
    # Only the two with reports AND review_count >= min should come back,
    # sorted by review_count DESC.
    _seed_game(game_repo, appid=2001, name="Slay the Spire", review_count=50000)
    _seed_game(game_repo, appid=2002, name="Balatro", review_count=30000)
    _seed_game(game_repo, appid=2003, name="Tiny Indie", review_count=150)
    _seed_game(game_repo, appid=2004, name="No Report Game", review_count=40000)

    tag_repo.upsert_tags(
        [
            {"appid": 2001, "name": "Deckbuilder", "votes": 100, "tagid": 9001},
            {"appid": 2002, "name": "Deckbuilder", "votes": 80, "tagid": 9001},
            {"appid": 2003, "name": "Deckbuilder", "votes": 10, "tagid": 9001},
            {"appid": 2004, "name": "Deckbuilder", "votes": 90, "tagid": 9001},
        ]
    )

    # Reports at the current pipeline_version for 2001, 2002 — and a stale
    # report at an older pipeline_version for 2003. 2004 has no report.
    for appid in (2001, 2002):
        report_repo.upsert(
            {
                "appid": appid,
                "game_name": f"Game {appid}",
                "pipeline_version": "3.0/current",
                "chunk_count": 1,
                "merged_summary_id": 1,
                "total_reviews_analyzed": 1,
            }
        )
    report_repo.upsert(
        {
            "appid": 2003,
            "game_name": "Game 2003",
            "pipeline_version": "3.0/old",  # stale — should be filtered out
            "chunk_count": 1,
            "merged_summary_id": 1,
            "total_reviews_analyzed": 1,
        }
    )

    eligible = tag_repo.find_eligible_for_synthesis(
        "deckbuilder",
        min_reviews=200,
        limit=10,
        pipeline_version="3.0/current",
    )
    # 2003 filtered by pipeline_version + below review threshold; 2004 has no report.
    assert eligible == [2001, 2002]

    # SQL LIMIT is honoured — requesting only the top 1 returns the highest
    # review_count.
    top_one = tag_repo.find_eligible_for_synthesis(
        "deckbuilder",
        min_reviews=200,
        limit=1,
        pipeline_version="3.0/current",
    )
    assert top_one == [2001]

    # Querying the old pipeline_version returns only the stale-report game
    # (and only if it meets the review threshold — 2003 has 150 reviews,
    # below min=200, so empty).
    at_old_version = tag_repo.find_eligible_for_synthesis(
        "deckbuilder",
        min_reviews=100,  # loosen to pick up 2003
        limit=10,
        pipeline_version="3.0/old",
    )
    assert at_old_version == [2003]
