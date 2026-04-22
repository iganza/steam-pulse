"""Tests for MatviewRepository — audience overlap (mv_audience_overlap)."""

from datetime import UTC, datetime
from typing import Any

import pytest
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.matview_repo import MatviewRepository
from library_layer.repositories.review_repo import ReviewRepository

# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_game(game_repo: GameRepository, appid: int = 440, **kw: Any) -> None:
    game_repo.upsert(
        {
            "appid": appid,
            "name": kw.get("name", f"Game {appid}"),
            "slug": kw.get("slug", f"game-{appid}"),
            "type": "game",
            "developer": kw.get("developer", "Test Dev"),
            "developer_slug": kw.get("developer_slug", "test-dev"),
            "publisher": kw.get("publisher"),
            "publisher_slug": kw.get("publisher_slug"),
            "developers": "[]",
            "publishers": "[]",
            "website": None,
            "release_date": kw.get("release_date", "2022-06-15"),
            "release_date_raw": None,
            "coming_soon": False,
            "price_usd": kw.get("price_usd", 9.99),
            "is_free": kw.get("is_free", False),
            "short_desc": None,
            "detailed_description": None,
            "about_the_game": None,
            "review_count": kw.get("review_count", 100),
            "review_count_english": kw.get("review_count", 100),
            "total_positive": 75,
            "total_negative": 25,
            "positive_pct": kw.get("positive_pct", 75),
            "review_score_desc": "Mostly Positive",
            "header_image": None,
            "background_image": None,
            "required_age": 0,
            "platforms": kw.get("platforms", '{"windows": true, "mac": false, "linux": false}'),
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


def _make_review(appid: int, author: str, voted_up: bool = True, idx: int = 0) -> dict:
    return {
        "appid": appid,
        "steam_review_id": f"rev-{appid}-{author}-{idx}",
        "author_steamid": author,
        "voted_up": voted_up,
        "playtime_hours": 10,
        "body": "review",
        "posted_at": datetime(2024, 1, 1, tzinfo=UTC),
        "language": "english",
        "votes_helpful": 0,
        "votes_funny": 0,
        "written_during_early_access": False,
        "received_for_free": False,
    }


# ---------------------------------------------------------------------------
# get_audience_overlap (mv_audience_overlap)
# ---------------------------------------------------------------------------


def test_audience_overlap_basic(
    db_conn: Any,
    matview_repo: MatviewRepository,
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    refresh_matviews: Any,
) -> None:
    """Shared reviewers counted correctly with correct overlap_pct math.

    Both games need >= 100 unique reviewers to pass the matview's
    games_with_reviews threshold.
    """
    _seed_game(game_repo, 440)
    _seed_game(game_repo, 570)

    # 10 shared reviewers + 90 unique to each game = 100 per game
    shared_authors = [f"shared_{i}" for i in range(10)]
    reviews = [_make_review(440, a) for a in shared_authors]
    reviews += [_make_review(440, f"only440_{i}", idx=i) for i in range(90)]
    reviews += [_make_review(570, a) for a in shared_authors]
    reviews += [_make_review(570, f"only570_{i}", idx=i) for i in range(90)]
    review_repo.bulk_upsert(reviews)
    refresh_matviews()

    result = matview_repo.get_audience_overlap(440, limit=10)
    assert result["total_reviewers"] == 100
    assert len(result["overlaps"]) == 1
    overlap = result["overlaps"][0]
    assert overlap["appid"] == 570
    assert overlap["overlap_count"] == 10
    assert overlap["overlap_pct"] == pytest.approx(10.0, abs=0.2)
    assert isinstance(overlap["shared_sentiment_pct"], float)


def test_audience_overlap_no_reviews(
    matview_repo: MatviewRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """Returns empty structure when appid has no reviews."""
    _seed_game(game_repo, 440)
    refresh_matviews()
    result = matview_repo.get_audience_overlap(440, limit=20)
    assert result == {"total_reviewers": 0, "overlaps": []}


def test_audience_overlap_excludes_self(
    db_conn: Any,
    matview_repo: MatviewRepository,
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    refresh_matviews: Any,
) -> None:
    """Game with reviewers but no overlaps returns correct total_reviewers."""
    _seed_game(game_repo, 440)
    review_repo.bulk_upsert([_make_review(440, "user1")])
    refresh_matviews()
    result = matview_repo.get_audience_overlap(440, limit=20)
    assert result["total_reviewers"] == 1
    assert result["overlaps"] == []


def test_audience_overlap_limit(
    db_conn: Any,
    matview_repo: MatviewRepository,
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    refresh_matviews: Any,
) -> None:
    """Result is capped at the requested limit.

    Each game needs >= 100 unique reviewers to pass the matview threshold.
    """
    for i in range(5):
        _seed_game(game_repo, 440 + i)
    # 1 shared reviewer across all 5 games + 99 unique per game = 100 each
    reviews: list[dict] = []
    for i in range(5):
        reviews.append(_make_review(440 + i, "shared"))
        reviews += [_make_review(440 + i, f"uniq{440 + i}_{j}", idx=j) for j in range(99)]
    review_repo.bulk_upsert(reviews)
    refresh_matviews()

    result = matview_repo.get_audience_overlap(440, limit=2)
    assert len(result["overlaps"]) <= 2


# ---------------------------------------------------------------------------
# Refresh management — refresh_one / start_cycle / complete_cycle
# ---------------------------------------------------------------------------


def test_refresh_one_rejects_unknown_view(
    db_conn: Any,
    matview_repo: MatviewRepository,
) -> None:
    """refresh_one raises ValueError for names not in MATVIEW_NAMES.

    Guards the sql.Identifier path — an attacker-controlled string would
    otherwise be interpolated directly into the REFRESH statement.
    """
    with pytest.raises(ValueError):
        matview_repo.refresh_one("not_a_view")


def test_refresh_one_returns_duration(
    db_conn: Any,
    matview_repo: MatviewRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """refresh_one succeeds and returns a non-negative duration."""
    _seed_game(game_repo, 440)
    # Prime the matview so CONCURRENTLY doesn't fail on empty content.
    refresh_matviews()
    duration_ms = matview_repo.refresh_one("mv_genre_counts")
    assert duration_ms >= 0


def test_start_cycle_inserts_running_row(
    db_conn: Any,
    matview_repo: MatviewRepository,
) -> None:
    """start_cycle writes a row with status='running' and started_at set."""
    matview_repo.start_cycle("cycle-abc")
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT cycle_id, status, started_at, per_view_results, duration_ms
            FROM matview_refresh_log
            WHERE cycle_id = %s
            """,
            ("cycle-abc",),
        )
        row = cur.fetchone()
    assert row is not None
    assert row["cycle_id"] == "cycle-abc"
    assert row["status"] == "running"
    assert row["started_at"] is not None
    assert row["per_view_results"] is None
    assert row["duration_ms"] is None


def test_complete_cycle_all_success(
    db_conn: Any,
    matview_repo: MatviewRepository,
) -> None:
    """All-success results → status='complete', views_refreshed populated."""
    matview_repo.start_cycle("cycle-ok")
    per_view = {
        "mv_a": {"success": True, "duration_ms": 100, "error": ""},
        "mv_b": {"success": True, "duration_ms": 200, "error": ""},
    }
    matview_repo.complete_cycle("cycle-ok", 1234, per_view)
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, duration_ms, per_view_results, views_refreshed
            FROM matview_refresh_log WHERE cycle_id = %s
            """,
            ("cycle-ok",),
        )
        row = cur.fetchone()
    assert row["status"] == "complete"
    assert row["duration_ms"] == 1234
    assert set(row["per_view_results"].keys()) == {"mv_a", "mv_b"}
    assert set(row["views_refreshed"]) == {"mv_a", "mv_b"}


def test_complete_cycle_partial_failure(
    db_conn: Any,
    matview_repo: MatviewRepository,
) -> None:
    """Mixed results → status='partial_failure'; only successes in views_refreshed."""
    matview_repo.start_cycle("cycle-mixed")
    per_view = {
        "mv_a": {"success": True, "duration_ms": 100, "error": ""},
        "mv_b": {"success": False, "duration_ms": 0, "error": "boom"},
    }
    matview_repo.complete_cycle("cycle-mixed", 500, per_view)
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT status, views_refreshed FROM matview_refresh_log WHERE cycle_id = %s",
            ("cycle-mixed",),
        )
        row = cur.fetchone()
    assert row["status"] == "partial_failure"
    assert row["views_refreshed"] == ["mv_a"]


def test_complete_cycle_all_failure(
    db_conn: Any,
    matview_repo: MatviewRepository,
) -> None:
    """All-failure results → status='failed'."""
    matview_repo.start_cycle("cycle-bad")
    per_view = {
        "mv_a": {"success": False, "duration_ms": 0, "error": "boom"},
    }
    matview_repo.complete_cycle("cycle-bad", 50, per_view)
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM matview_refresh_log WHERE cycle_id = %s",
            ("cycle-bad",),
        )
        row = cur.fetchone()
    assert row["status"] == "failed"


def test_complete_cycle_raises_when_no_match(
    db_conn: Any,
    matview_repo: MatviewRepository,
) -> None:
    """Raise if the UPDATE matches no row — silently losing a cycle would
    break debounce/observability."""
    with pytest.raises(RuntimeError):
        matview_repo.complete_cycle(
            "never-started",
            1000,
            {"mv_a": {"success": True, "duration_ms": 100, "error": ""}},
        )


def test_get_running_cycle_id_returns_recent_running(
    db_conn: Any,
    matview_repo: MatviewRepository,
) -> None:
    """A running cycle started inside the stale window is returned."""
    matview_repo.start_cycle("cycle-live")
    got = matview_repo.get_running_cycle_id(stale_after_seconds=3600)
    assert got == "cycle-live"


def test_get_running_cycle_id_ignores_stale(
    db_conn: Any,
    matview_repo: MatviewRepository,
) -> None:
    """Running rows older than the cutoff are treated as crashed."""
    # Insert a running row with a deliberately old started_at.
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO matview_refresh_log (cycle_id, status, started_at)
            VALUES ('cycle-stuck', 'running', NOW() - INTERVAL '2 hours')
            """,
        )
    db_conn.commit()

    assert matview_repo.get_running_cycle_id(stale_after_seconds=3600) is None


def test_get_running_cycle_id_ignores_complete(
    db_conn: Any,
    matview_repo: MatviewRepository,
) -> None:
    """Only status='running' rows count toward the in-flight guard."""
    matview_repo.start_cycle("cycle-done")
    matview_repo.complete_cycle(
        "cycle-done", 100, {"mv_a": {"success": True, "duration_ms": 100, "error": ""}}
    )
    assert matview_repo.get_running_cycle_id(stale_after_seconds=3600) is None


def test_get_last_refresh_time_only_reads_complete(
    db_conn: Any,
    matview_repo: MatviewRepository,
) -> None:
    """Running/failed/legacy-NULL rows are ignored by the debounce read."""
    # Legacy row with NULL status (pre-0054).
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO matview_refresh_log (duration_ms, views_refreshed) VALUES (%s, %s)",
            (100, ["mv_a"]),
        )
    db_conn.commit()

    matview_repo.start_cycle("cycle-running")
    matview_repo.start_cycle("cycle-done")
    matview_repo.complete_cycle(
        "cycle-done", 200, {"mv_a": {"success": True, "duration_ms": 100, "error": ""}}
    )
    matview_repo.start_cycle("cycle-fail")
    matview_repo.complete_cycle(
        "cycle-fail", 10, {"mv_a": {"success": False, "duration_ms": 0, "error": "boom"}}
    )

    ts = matview_repo.get_last_refresh_time()
    assert ts is not None

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT EXTRACT(EPOCH FROM refreshed_at) AS ts FROM matview_refresh_log "
            "WHERE cycle_id = %s",
            ("cycle-done",),
        )
        done_ts = cur.fetchone()["ts"]
    assert ts == pytest.approx(float(done_ts), abs=0.001)
