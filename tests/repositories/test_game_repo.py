"""Tests for GameRepository."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from library_layer.repositories.game_repo import GameRepository


def _game_data(appid: int = 440, name: str = "Team Fortress 2") -> dict:
    return {
        "appid": appid,
        "name": name,
        "slug": f"team-fortress-2-{appid}",
        "type": "game",
        "developer": "Valve",
        "developer_slug": "valve",
        "publisher": "Valve",
        "publisher_slug": "valve",
        "developers": '["Valve"]',
        "publishers": '["Valve"]',
        "website": "http://www.teamfortress.com/",
        "release_date": date(2007, 10, 10),
        "release_date_raw": None,
        "coming_soon": False,
        "price_usd": None,
        "is_free": True,
        "short_desc": "Nine classes, constant updates.",
        "detailed_description": "A detailed description.",
        "about_the_game": "About TF2.",
        "review_count": 188000,
        "review_count_english": 155000,
        "total_positive": 182000,
        "total_negative": 6000,
        "positive_pct": 96,
        "review_score_desc": "Overwhelmingly Positive",
        "header_image": "https://example.com/header.jpg",
        "background_image": "https://example.com/bg.jpg",
        "required_age": 0,
        "platforms": '{"windows": true, "mac": false, "linux": true}',
        "supported_languages": "English",
        "achievements_total": 520,
        "metacritic_score": 92,
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


def test_upsert_inserts_new_game(game_repo: GameRepository) -> None:
    game_repo.upsert(_game_data())
    game = game_repo.find_by_appid(440)
    assert game is not None
    assert game.appid == 440
    assert game.name == "Team Fortress 2"
    assert game.developer == "Valve"
    assert game.review_count == 188000


def test_upsert_updates_existing_game(game_repo: GameRepository) -> None:
    game_repo.upsert(_game_data())
    updated = _game_data()
    updated["name"] = "TF2 Updated"
    updated["review_count"] = 200000
    game_repo.upsert(updated)
    game = game_repo.find_by_appid(440)
    assert game is not None
    assert game.name == "TF2 Updated"
    assert game.review_count == 200000


def test_find_by_appid_returns_none_for_missing(game_repo: GameRepository) -> None:
    assert game_repo.find_by_appid(9999999) is None


def test_find_by_slug(game_repo: GameRepository) -> None:
    game_repo.upsert(_game_data())
    game = game_repo.find_by_slug("team-fortress-2-440")
    assert game is not None
    assert game.appid == 440


def test_find_eligible_for_reviews(game_repo: GameRepository) -> None:
    game_repo.upsert(_game_data(440, "TF2"))  # 188000 reviews
    small = _game_data(1, "Tiny Game")
    small["review_count"] = 50
    small["slug"] = "tiny-game-1"
    game_repo.upsert(small)

    eligible = game_repo.find_eligible_for_reviews(min_reviews=500)
    appids = [g.appid for g in eligible]
    assert 440 in appids
    assert 1 not in appids


def test_update_review_stats(game_repo: GameRepository) -> None:
    game_repo.upsert(_game_data())
    game_repo.update_review_stats(440, 190000, 6000, 196000, "Overwhelmingly Positive")
    game = game_repo.find_by_appid(440)
    assert game is not None
    assert game.total_positive == 190000
    assert game.review_count == 196000
    assert game.review_score_desc == "Overwhelmingly Positive"
    # Name unchanged
    assert game.name == "Team Fortress 2"


def test_get_review_count_returns_zero_for_missing(game_repo: GameRepository) -> None:
    assert game_repo.get_review_count(9999999) == 0


def test_update_post_release_metrics_persists_values(game_repo: GameRepository) -> None:
    game_repo.upsert(_game_data())
    game_repo.update_post_release_metrics(440, 1200, 1020, 85, "Very Positive")
    game = game_repo.find_by_appid(440)
    assert game is not None
    assert game.review_count_post_release == 1200
    assert game.positive_count_post_release == 1020
    assert game.positive_pct_post_release == 85
    assert game.review_score_desc_post_release == "Very Positive"


def test_update_post_release_metrics_zero_counts(game_repo: GameRepository) -> None:
    """A Project-Scrapper-like ex-EA game with no post-release reviews."""
    game_repo.upsert(_game_data())
    game_repo.update_post_release_metrics(440, 0, 0, 0, "")
    game = game_repo.find_by_appid(440)
    assert game is not None
    assert game.review_count_post_release == 0
    assert game.positive_count_post_release == 0
    assert game.positive_pct_post_release == 0
    assert game.review_score_desc_post_release == ""


def test_update_velocity_cache(game_repo: GameRepository) -> None:
    game_repo.upsert(_game_data())
    game_repo.update_velocity_cache(440, 2.5)
    with game_repo.conn.cursor() as cur:
        cur.execute(
            "SELECT review_velocity_lifetime, last_velocity_computed_at FROM games WHERE appid = %s",
            (440,),
        )
        row = cur.fetchone()
    assert row is not None
    assert float(row["review_velocity_lifetime"]) == 2.5
    assert row["last_velocity_computed_at"] is not None


def test_update_revenue_estimate_persists_values(game_repo: GameRepository) -> None:
    game_repo.upsert(_game_data())
    # Pass a stale reason alongside real numbers — the repo must coerce it
    # to NULL so inconsistent rows can't leak out of this layer.
    game_repo.update_revenue_estimate(
        appid=440,
        owners=30000,
        revenue_usd=Decimal("599700.00"),
        method="boxleiter_v1",
        reason="insufficient_reviews",
    )
    with game_repo.conn.cursor() as cur:
        cur.execute(
            """
            SELECT estimated_owners, estimated_revenue_usd,
                   revenue_estimate_method, revenue_estimate_reason,
                   revenue_estimate_computed_at
            FROM games WHERE appid = %s
            """,
            (440,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row["estimated_owners"] == 30000
    assert row["estimated_revenue_usd"] == Decimal("599700.00")
    assert row["revenue_estimate_method"] == "boxleiter_v1"
    assert row["revenue_estimate_reason"] is None
    assert row["revenue_estimate_computed_at"] is not None


def test_update_revenue_estimate_writes_null_method_when_no_estimate(
    game_repo: GameRepository,
) -> None:
    """Free-to-play / excluded-type games must land with a NULL method so
    downstream clients can treat NULL as 'no estimate available'. The reason
    code is persisted alongside so the UI can render precise empty-state copy.
    """
    game_repo.upsert(_game_data())
    game_repo.update_revenue_estimate(
        appid=440,
        owners=None,
        revenue_usd=None,
        method="boxleiter_v1",
        reason="insufficient_reviews",
    )
    with game_repo.conn.cursor() as cur:
        cur.execute(
            """
            SELECT estimated_owners, estimated_revenue_usd,
                   revenue_estimate_method, revenue_estimate_reason,
                   revenue_estimate_computed_at
            FROM games WHERE appid = %s
            """,
            (440,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row["estimated_owners"] is None
    assert row["estimated_revenue_usd"] is None
    assert row["revenue_estimate_method"] is None
    assert row["revenue_estimate_reason"] == "insufficient_reviews"
    # computed_at is still stamped — tracks the attempt, not the outcome.
    assert row["revenue_estimate_computed_at"] is not None


def test_find_for_revenue_estimate_returns_minimal_game(game_repo: GameRepository) -> None:
    game_repo.upsert(_game_data())
    game = game_repo.find_for_revenue_estimate(440)
    assert game is not None
    assert game.appid == 440
    assert game.type == "game"
    assert game.is_free is True
    assert game.review_count == 188000


def test_bulk_update_revenue_estimates_mixed_batch(game_repo: GameRepository) -> None:
    """One UPDATE path covers both estimate-present and estimate-absent rows,
    coercing `method` to NULL for the latter."""
    game_repo.upsert(_game_data(440, "TF2"))
    other = _game_data(441, "Half-Life 2")
    other["slug"] = "half-life-2-441"
    game_repo.upsert(other)

    game_repo.bulk_update_revenue_estimates(
        [
            # Stale reason alongside real numbers — must be coerced to NULL.
            (440, 30_000, Decimal("300000.00"), "boxleiter_v1", "insufficient_reviews"),
            (441, None, None, "boxleiter_v1", "free_to_play"),
        ]
    )

    with game_repo.conn.cursor() as cur:
        cur.execute(
            """
            SELECT appid, estimated_owners, estimated_revenue_usd,
                   revenue_estimate_method, revenue_estimate_reason,
                   revenue_estimate_computed_at
            FROM games WHERE appid IN (440, 441) ORDER BY appid
            """
        )
        a, b = cur.fetchall()
    assert a["estimated_owners"] == 30_000
    assert a["estimated_revenue_usd"] == Decimal("300000.00")
    assert a["revenue_estimate_method"] == "boxleiter_v1"
    assert a["revenue_estimate_reason"] is None
    assert a["revenue_estimate_computed_at"] is not None
    assert b["estimated_owners"] is None
    assert b["estimated_revenue_usd"] is None
    assert b["revenue_estimate_method"] is None  # coerced to NULL
    assert b["revenue_estimate_reason"] == "free_to_play"
    assert b["revenue_estimate_computed_at"] is not None


def test_bulk_update_revenue_estimates_empty_is_noop(game_repo: GameRepository) -> None:
    game_repo.bulk_update_revenue_estimates([])  # must not raise


def test_find_for_revenue_estimate_returns_none_for_missing(
    game_repo: GameRepository,
) -> None:
    assert game_repo.find_for_revenue_estimate(9999999) is None


def test_ensure_stub_creates_minimal_row(game_repo: GameRepository) -> None:
    game_repo.ensure_stub(12345)
    game = game_repo.find_by_appid(12345)
    assert game is not None
    assert game.name == "App 12345"
    assert game.slug == "app-12345"


# ---------------------------------------------------------------------------
# Helpers for genre linkage (find_benchmarks tests)
# ---------------------------------------------------------------------------


def _upsert_genre(db_conn: Any, genre_id: int, name: str) -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO genres (id, name, slug) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (genre_id, name, name.lower()),
        )
    db_conn.commit()


def _link_genre(db_conn: Any, appid: int, genre_id: int) -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO game_genres (appid, genre_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (appid, genre_id),
        )
    db_conn.commit()


# ---------------------------------------------------------------------------
# find_benchmarks tests
# ---------------------------------------------------------------------------


def test_find_benchmarks_null_ranks_for_small_review_count(
    db_conn: Any, game_repo: GameRepository
) -> None:
    """Game with review_count ≤ 50 is excluded from the cohort — returns null ranks."""
    data = _game_data()
    data["review_count"] = 10  # below the cohort threshold of >50
    data["is_free"] = True
    data["price_usd"] = None
    game_repo.upsert(data)
    _upsert_genre(db_conn, 1, "Action")
    _link_genre(db_conn, 440, 1)
    result = game_repo.find_benchmarks(440, genre="Action", year=2007, price=None, is_free=True)
    assert result["sentiment_rank"] is None
    assert result["popularity_rank"] is None
    assert result["cohort_size"] == 0


def test_find_benchmarks_single_game_in_cohort(db_conn: Any, game_repo: GameRepository) -> None:
    """Single game in its cohort has PERCENT_RANK 0.0 (sole row in window)."""
    data = _game_data()
    data["review_count"] = 200
    data["is_free"] = True
    data["price_usd"] = None
    game_repo.upsert(data)
    _upsert_genre(db_conn, 1, "Action")
    _link_genre(db_conn, 440, 1)
    result = game_repo.find_benchmarks(440, genre="Action", year=2007, price=None, is_free=True)
    assert result["cohort_size"] == 1
    assert result["sentiment_rank"] == 0.0
    assert result["popularity_rank"] == 0.0


def test_find_benchmarks_rank_within_multi_game_cohort(
    db_conn: Any, game_repo: GameRepository
) -> None:
    """Target game in the middle of a 3-game cohort has sentiment_rank ≈ 0.5."""
    _upsert_genre(db_conn, 1, "Action")
    for appid, pct in [(440, 80), (441, 70), (442, 90)]:
        data = _game_data(appid, f"Game {appid}")
        data["review_count"] = 200
        data["is_free"] = True
        data["price_usd"] = None
        data["positive_pct"] = pct
        data["slug"] = f"game-{appid}"
        game_repo.upsert(data)
        _link_genre(db_conn, appid, 1)
    result = game_repo.find_benchmarks(440, genre="Action", year=2007, price=None, is_free=True)
    assert result["cohort_size"] == 3
    # Game 440 (pct=80) sits between 70 and 90 → PERCENT_RANK = 1/(3-1) = 0.5
    assert result["sentiment_rank"] == pytest.approx(0.5, abs=0.01)


def test_find_benchmarks_excludes_different_genre(db_conn: Any, game_repo: GameRepository) -> None:
    """A game in a different genre is not counted in the Action cohort."""
    _upsert_genre(db_conn, 1, "Action")
    _upsert_genre(db_conn, 2, "RPG")
    data = _game_data(440, "TF2")
    data["review_count"] = 200
    data["is_free"] = True
    data["price_usd"] = None
    game_repo.upsert(data)
    _link_genre(db_conn, 440, 1)
    other = _game_data(441, "RPG Game")
    other["review_count"] = 200
    other["is_free"] = True
    other["price_usd"] = None
    other["slug"] = "rpg-game-441"
    game_repo.upsert(other)
    _link_genre(db_conn, 441, 2)
    result = game_repo.find_benchmarks(440, genre="Action", year=2007, price=None, is_free=True)
    assert result["cohort_size"] == 1  # only game 440


def test_find_benchmarks_excludes_different_release_year(
    db_conn: Any, game_repo: GameRepository
) -> None:
    """Games released in a different year are excluded from the cohort."""
    _upsert_genre(db_conn, 1, "Action")
    data = _game_data(440, "TF2")
    data["review_count"] = 200
    data["is_free"] = True
    data["price_usd"] = None
    data["release_date"] = date(2007, 10, 10)
    game_repo.upsert(data)
    _link_genre(db_conn, 440, 1)
    other = _game_data(441, "Newer Game")
    other["review_count"] = 200
    other["is_free"] = True
    other["price_usd"] = None
    other["slug"] = "newer-game-441"
    other["release_date"] = date(2020, 1, 1)
    game_repo.upsert(other)
    _link_genre(db_conn, 441, 1)
    result = game_repo.find_benchmarks(440, genre="Action", year=2007, price=None, is_free=True)
    assert result["cohort_size"] == 1  # only game 440


# ---------------------------------------------------------------------------
# list_games — sentiment and price_tier filter tests
# ---------------------------------------------------------------------------


def test_list_games_sentiment_positive_filter(game_repo: GameRepository) -> None:
    """sentiment='positive' returns only games with Steam positive_pct >= 65."""
    game_repo.upsert({**_game_data(440, "High Sentiment"), "positive_pct": 90})
    game_repo.upsert(
        {**_game_data(441, "Low Sentiment"), "slug": "low-sentiment-441", "positive_pct": 40}
    )
    result = game_repo.list_games(sentiment="positive")
    appids = [g["appid"] for g in result["games"]]
    assert 440 in appids
    assert 441 not in appids


def test_list_games_sentiment_mixed_filter(game_repo: GameRepository) -> None:
    """sentiment='mixed' returns only games with 45 <= positive_pct < 65."""
    game_repo.upsert({**_game_data(440, "Mixed Game"), "positive_pct": 55})
    game_repo.upsert(
        {**_game_data(441, "Positive Game"), "slug": "positive-game-441", "positive_pct": 90}
    )
    result = game_repo.list_games(sentiment="mixed")
    appids = [g["appid"] for g in result["games"]]
    assert 440 in appids
    assert 441 not in appids


def test_list_games_sentiment_negative_filter(game_repo: GameRepository) -> None:
    """sentiment='negative' returns only games with positive_pct < 45."""
    game_repo.upsert({**_game_data(440, "Bad Game"), "positive_pct": 30})
    game_repo.upsert({**_game_data(441, "Good Game"), "slug": "good-game-441", "positive_pct": 80})
    result = game_repo.list_games(sentiment="negative")
    appids = [g["appid"] for g in result["games"]]
    assert 440 in appids
    assert 441 not in appids


def test_list_games_price_tier_free(game_repo: GameRepository) -> None:
    """price_tier='free' returns only free games."""
    free_game = _game_data(440, "Free Game")
    free_game["is_free"] = True
    free_game["price_usd"] = None
    game_repo.upsert(free_game)
    paid_game = {
        **_game_data(441, "Paid Game"),
        "is_free": False,
        "price_usd": 9.99,
        "slug": "paid-game-441",
    }
    game_repo.upsert(paid_game)
    result = game_repo.list_games(price_tier="free")
    appids = [g["appid"] for g in result["games"]]
    assert 440 in appids
    assert 441 not in appids


def test_list_games_price_tier_under_10(game_repo: GameRepository) -> None:
    """price_tier='under_10' returns non-free paid games priced below $10."""
    cheap = {**_game_data(440, "Cheap Game"), "is_free": False, "price_usd": 4.99}
    game_repo.upsert(cheap)
    pricey = {
        **_game_data(441, "Pricey Game"),
        "is_free": False,
        "price_usd": 29.99,
        "slug": "pricey-game-441",
    }
    game_repo.upsert(pricey)
    free_game = {
        **_game_data(442, "Free Game"),
        "is_free": True,
        "price_usd": None,
        "slug": "free-game-442",
    }
    game_repo.upsert(free_game)
    result = game_repo.list_games(price_tier="under_10")
    appids = [g["appid"] for g in result["games"]]
    assert 440 in appids
    assert 441 not in appids
    assert 442 not in appids


def test_list_games_price_tier_10_to_20(game_repo: GameRepository) -> None:
    """price_tier='10_to_20' returns games priced between $10 and $20 inclusive."""
    mid = {**_game_data(440, "Mid Game"), "is_free": False, "price_usd": 14.99}
    game_repo.upsert(mid)
    cheap = {**_game_data(441, "Cheap"), "is_free": False, "price_usd": 4.99, "slug": "cheap-441"}
    game_repo.upsert(cheap)
    result = game_repo.list_games(price_tier="10_to_20")
    appids = [g["appid"] for g in result["games"]]
    assert 440 in appids
    assert 441 not in appids


def test_list_games_price_tier_over_20(game_repo: GameRepository) -> None:
    """price_tier='over_20' returns games priced above $20."""
    pricey = {**_game_data(440, "AAA"), "is_free": False, "price_usd": 59.99}
    game_repo.upsert(pricey)
    cheap = {**_game_data(441, "Indie"), "is_free": False, "price_usd": 9.99, "slug": "indie-441"}
    game_repo.upsert(cheap)
    result = game_repo.list_games(price_tier="over_20")
    appids = [g["appid"] for g in result["games"]]
    assert 440 in appids
    assert 441 not in appids


def test_list_games_sentiment_and_price_tier_combined(game_repo: GameRepository) -> None:
    """Both sentiment and price_tier must match — a game passing only one is excluded."""
    match = {**_game_data(440, "Match"), "is_free": False, "price_usd": 4.99, "positive_pct": 80}
    game_repo.upsert(match)
    no_match = {
        **_game_data(441, "Pricey"),
        "is_free": False,
        "price_usd": 39.99,
        "slug": "pricey-441",
        "positive_pct": 80,
    }
    game_repo.upsert(no_match)
    result = game_repo.list_games(sentiment="positive", price_tier="under_10")
    appids = [g["appid"] for g in result["games"]]
    assert 440 in appids
    assert 441 not in appids


# ---------------------------------------------------------------------------
# list_games pagination (total from matviews, not from repo)
# ---------------------------------------------------------------------------


def test_list_games_total_is_none(game_repo: GameRepository) -> None:
    """list_games returns total=None — handler provides count from matviews."""
    for i in range(5):
        game_repo.upsert({**_game_data(100 + i, f"Game {i}"), "slug": f"game-{100 + i}"})
    result = game_repo.list_games(limit=2, offset=0)
    assert result["total"] is None
    assert len(result["games"]) == 2


def test_list_games_empty_result(game_repo: GameRepository) -> None:
    """No matching games returns total=None and empty list."""
    result = game_repo.list_games(q="nonexistent-query-xyz", limit=10, offset=0)
    assert result["total"] is None
    assert result["games"] == []
