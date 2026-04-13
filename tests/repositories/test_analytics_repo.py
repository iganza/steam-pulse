"""Tests for AnalyticsRepository."""

import json
from typing import Any

import pytest
from library_layer.repositories.analytics_repo import AnalyticsRepository
from library_layer.repositories.game_repo import GameRepository

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
            "platforms": kw.get(
                "platforms", json.dumps({"windows": True, "mac": False, "linux": False})
            ),
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


def _seed_genre(db_conn: Any, name: str, slug: str) -> int:
    # genres.id is INTEGER (not SERIAL) — derive a stable ID from the slug
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO genres (id, name, slug)
            VALUES (ABS(HASHTEXT(%s)) %% 999999 + 1, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (slug, name, slug),
        )
        genre_id = cur.fetchone()["id"]
    db_conn.commit()
    return genre_id


def _link_genre(db_conn: Any, appid: int, genre_id: int) -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO game_genres (appid, genre_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (appid, genre_id),
        )
    db_conn.commit()


def _seed_tag(db_conn: Any, name: str, slug: str) -> int:
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tags (name, slug) VALUES (%s, %s) ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id",
            (name, slug),
        )
        tag_id = cur.fetchone()["id"]
    db_conn.commit()
    return tag_id


def _link_tag(db_conn: Any, appid: int, tag_id: int) -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO game_tags (appid, tag_id, votes) VALUES (%s, %s, 1) ON CONFLICT DO NOTHING",
            (appid, tag_id),
        )
    db_conn.commit()


# ---------------------------------------------------------------------------
# find_price_positioning
# ---------------------------------------------------------------------------


def test_price_positioning_distribution(
    db_conn: Any,
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """Each price bucket is counted correctly."""
    genre_id = _seed_genre(db_conn, "Action", "action")
    # Seed 12 games at $7.99 so the bucket has enough for sweet_spot
    for i in range(12):
        _seed_game(game_repo, 1000 + i, price_usd=7.99, review_count=20, positive_pct=70)
        _link_genre(db_conn, 1000 + i, genre_id)
    refresh_matviews()

    result = analytics_repo.find_price_positioning("action")
    bucket_names = [d["price_range"] for d in result["distribution"]]
    assert "$5-10" in bucket_names
    dollar5_10 = next(d for d in result["distribution"] if d["price_range"] == "$5-10")
    assert dollar5_10["game_count"] == 12


def test_price_positioning_sweet_spot(
    db_conn: Any,
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """sweet_spot is the price_range with highest avg_sentiment (>= 10 games)."""
    genre_id = _seed_genre(db_conn, "RPG", "rpg")
    # 12 cheap games with low sentiment
    for i in range(12):
        _seed_game(game_repo, 2000 + i, price_usd=3.99, review_count=20, positive_pct=50)
        _link_genre(db_conn, 2000 + i, genre_id)
    # 12 mid-tier games with high sentiment
    for i in range(12):
        _seed_game(game_repo, 2100 + i, price_usd=12.99, review_count=20, positive_pct=90)
        _link_genre(db_conn, 2100 + i, genre_id)
    refresh_matviews()

    result = analytics_repo.find_price_positioning("rpg")
    assert result["summary"]["sweet_spot"] == "$10-15"


def test_price_positioning_revenue_quartiles(
    db_conn: Any,
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """revenue_quartiles is populated per bucket from stored estimates."""
    from decimal import Decimal

    genre_id = _seed_genre(db_conn, "Strategy", "strategy")
    # Seed 4 games in the $5-10 bucket with distinct revenue estimates so
    # PERCENTILE_CONT has a well-defined Q1/median/Q3 to return.
    revenues = [
        Decimal("1000.00"),
        Decimal("2000.00"),
        Decimal("3000.00"),
        Decimal("4000.00"),
    ]
    for i, rev in enumerate(revenues):
        appid = 4000 + i
        _seed_game(game_repo, appid, price_usd=7.99, review_count=60, positive_pct=70)
        _link_genre(db_conn, appid, genre_id)
        game_repo.update_revenue_estimate(
            appid=appid,
            owners=int(rev),
            revenue_usd=rev,
            method="boxleiter_v1",
        )
    refresh_matviews()

    result = analytics_repo.find_price_positioning("strategy")
    bucket = next(d for d in result["distribution"] if d["price_range"] == "$5-10")
    quartiles = bucket["revenue_quartiles"]
    assert quartiles["sample_size"] == 4
    assert quartiles["q1"] == 1750.0
    assert quartiles["median"] == 2500.0
    assert quartiles["q3"] == 3250.0


def test_price_positioning_revenue_quartiles_null_when_missing(
    db_conn: Any,
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """Buckets with zero estimated games report null quartiles + sample_size 0."""
    genre_id = _seed_genre(db_conn, "Casual", "casual")
    for i in range(12):
        _seed_game(game_repo, 5000 + i, price_usd=7.99, review_count=20, positive_pct=70)
        _link_genre(db_conn, 5000 + i, genre_id)
    refresh_matviews()

    result = analytics_repo.find_price_positioning("casual")
    bucket = next(d for d in result["distribution"] if d["price_range"] == "$5-10")
    q = bucket["revenue_quartiles"]
    assert q["sample_size"] == 0
    assert q["q1"] is None
    assert q["median"] is None
    assert q["q3"] is None


def test_price_positioning_free_games(
    db_conn: Any,
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """Free games appear in distribution and summary free_count is accurate."""
    genre_id = _seed_genre(db_conn, "FPS", "fps")
    for i in range(3):
        _seed_game(game_repo, 3000 + i, is_free=True, price_usd=None, review_count=20)
        _link_genre(db_conn, 3000 + i, genre_id)
    refresh_matviews()

    result = analytics_repo.find_price_positioning("fps")
    free_bucket = next((d for d in result["distribution"] if d["price_range"] == "Free"), None)
    assert free_bucket is not None
    assert free_bucket["game_count"] == 3
    assert result["summary"]["free_count"] == 3


# ---------------------------------------------------------------------------
# find_release_timing
# ---------------------------------------------------------------------------


def test_release_timing_aggregation(
    db_conn: Any,
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """Monthly grouping is correct — games in the same month aggregate together."""
    genre_id = _seed_genre(db_conn, "Strategy", "strategy")
    for i in range(3):
        _seed_game(game_repo, 4000 + i, release_date="2023-03-10", review_count=20, positive_pct=70)
        _link_genre(db_conn, 4000 + i, genre_id)
    refresh_matviews()

    result = analytics_repo.find_release_timing("strategy")
    march = next((m for m in result["monthly"] if m["month"] == 3), None)
    assert march is not None
    assert march["releases"] == 3
    assert march["month_name"] == "March"


def test_release_timing_best_worst_month(
    db_conn: Any,
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """best_month has highest avg_sentiment, worst_month has lowest."""
    genre_id = _seed_genre(db_conn, "Puzzle", "puzzle")
    # January: 2 games at 90% sentiment
    for i in range(2):
        _seed_game(game_repo, 5000 + i, release_date="2023-01-10", review_count=20, positive_pct=90)
        _link_genre(db_conn, 5000 + i, genre_id)
    # June: 2 games at 50% sentiment
    for i in range(2):
        _seed_game(game_repo, 5100 + i, release_date="2023-06-10", review_count=20, positive_pct=50)
        _link_genre(db_conn, 5100 + i, genre_id)
    refresh_matviews()

    result = analytics_repo.find_release_timing("puzzle")
    assert result["best_month"]["month"] == 1
    assert result["worst_month"]["month"] == 6


def test_release_timing_quietest_busiest_month(
    db_conn: Any,
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """quietest_month has fewest releases, busiest_month has most."""
    genre_id = _seed_genre(db_conn, "Horror", "horror")
    # Feb: 1 game, Oct: 4 games
    _seed_game(game_repo, 6000, release_date="2023-02-01", review_count=20)
    _link_genre(db_conn, 6000, genre_id)
    for i in range(4):
        _seed_game(game_repo, 6100 + i, release_date="2023-10-01", review_count=20)
        _link_genre(db_conn, 6100 + i, genre_id)
    refresh_matviews()

    result = analytics_repo.find_release_timing("horror")
    assert result["quietest_month"]["month"] == 2
    assert result["busiest_month"]["month"] == 10


# ---------------------------------------------------------------------------
# find_platform_distribution
# ---------------------------------------------------------------------------


def test_platform_distribution_counts(
    db_conn: Any,
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """Platform counts and percentages are correct."""
    genre_id = _seed_genre(db_conn, "Platformer", "platformer")
    # 4 games total: all on Windows, 2 also on Mac
    for i in range(4):
        plat = json.dumps({"windows": True, "mac": i < 2, "linux": False})
        _seed_game(game_repo, 7000 + i, platforms=plat, review_count=20)
        _link_genre(db_conn, 7000 + i, genre_id)
    refresh_matviews()

    result = analytics_repo.find_platform_distribution("platformer")
    assert result["total_games"] == 4
    assert result["platforms"]["windows"]["count"] == 4
    assert result["platforms"]["mac"]["count"] == 2
    assert result["platforms"]["mac"]["pct"] == pytest.approx(50.0, abs=0.1)
    assert result["platforms"]["linux"]["count"] == 0


def test_platform_distribution_underserved(
    db_conn: Any,
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """Underserved is the supported platform with lowest percentage."""
    genre_id = _seed_genre(db_conn, "Sports", "sports")
    for i in range(4):
        plat = json.dumps({"windows": True, "mac": True, "linux": i == 0})
        _seed_game(game_repo, 8000 + i, platforms=plat, review_count=20)
        _link_genre(db_conn, 8000 + i, genre_id)
    refresh_matviews()

    result = analytics_repo.find_platform_distribution("sports")
    # linux only has 1/4 = 25%, mac has 4/4 = 100%, so linux is underserved
    assert result["underserved"] == "linux"


# ---------------------------------------------------------------------------
# find_tag_trend
# ---------------------------------------------------------------------------


def test_tag_trend_yearly(
    db_conn: Any,
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """Year grouping and game count are correct."""
    tag_id = _seed_tag(db_conn, "Roguelike", "roguelike")
    for i in range(3):
        _seed_game(game_repo, 9000 + i, release_date="2022-05-01")
        _link_tag(db_conn, 9000 + i, tag_id)
    for i in range(2):
        _seed_game(game_repo, 9100 + i, release_date="2023-05-01")
        _link_tag(db_conn, 9100 + i, tag_id)
    refresh_matviews()

    result = analytics_repo.find_tag_trend("roguelike")
    year_map = {y["year"]: y["game_count"] for y in result["yearly"]}
    assert year_map[2022] == 3
    assert year_map[2023] == 2
    assert result["total_games"] == 5


def test_tag_trend_growth_rate(
    db_conn: Any,
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """growth_rate is computed correctly and is None when first_year_count == 0."""
    tag_id = _seed_tag(db_conn, "Deckbuilder", "deckbuilder")
    # 2 games in 2021, 4 in 2022 → growth = (4-2)/2 = 1.0
    for i in range(2):
        _seed_game(game_repo, 10000 + i, release_date="2021-01-01")
        _link_tag(db_conn, 10000 + i, tag_id)
    for i in range(4):
        _seed_game(game_repo, 10100 + i, release_date="2022-01-01")
        _link_tag(db_conn, 10100 + i, tag_id)
    refresh_matviews()

    result = analytics_repo.find_tag_trend("deckbuilder")
    assert result["growth_rate"] == pytest.approx(1.0, abs=0.01)


def test_tag_trend_growth_rate_null_when_no_first_year(
    analytics_repo: AnalyticsRepository,
    refresh_matviews: Any,
) -> None:
    """growth_rate is None for a tag with no games (first_year_count == 0)."""
    refresh_matviews()
    result = analytics_repo.find_tag_trend("nonexistent-tag-xyz")
    assert result["growth_rate"] is None
    assert result["total_games"] == 0


def test_tag_trend_peak_year(
    db_conn: Any,
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """peak_year is the year with the highest game count."""
    tag_id = _seed_tag(db_conn, "CRPG", "crpg")
    for i in range(1):
        _seed_game(game_repo, 11000 + i, release_date="2021-01-01")
        _link_tag(db_conn, 11000 + i, tag_id)
    for i in range(5):
        _seed_game(game_repo, 11100 + i, release_date="2022-01-01")
        _link_tag(db_conn, 11100 + i, tag_id)
    for i in range(2):
        _seed_game(game_repo, 11200 + i, release_date="2023-01-01")
        _link_tag(db_conn, 11200 + i, tag_id)
    refresh_matviews()

    result = analytics_repo.find_tag_trend("crpg")
    assert result["peak_year"] == 2022


# ---------------------------------------------------------------------------
# find_developer_portfolio
# ---------------------------------------------------------------------------


def test_developer_portfolio_games_list(
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
) -> None:
    """Games are returned ordered by release_date DESC."""
    _seed_game(game_repo, 12000, developer="Acme", developer_slug="acme", release_date="2020-01-01")
    _seed_game(game_repo, 12001, developer="Acme", developer_slug="acme", release_date="2023-01-01")
    _seed_game(game_repo, 12002, developer="Acme", developer_slug="acme", release_date="2021-06-01")

    result = analytics_repo.find_developer_portfolio("acme")
    dates = [g["release_date"] for g in result["games"]]
    assert dates == sorted(dates, reverse=True)
    assert len(result["games"]) == 3


def test_developer_portfolio_summary(
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
) -> None:
    """Aggregate summary stats are correct."""
    for i in range(3):
        _seed_game(
            game_repo,
            13000 + i,
            developer="Pixel Studio",
            developer_slug="pixel-studio",
            positive_pct=80,
            review_count=1000,
            price_usd=14.99,
        )

    result = analytics_repo.find_developer_portfolio("pixel-studio")
    s = result["summary"]
    assert s["total_games"] == 3
    assert s["total_reviews"] == 3000
    assert s["well_received"] == 3
    assert s["poorly_received"] == 0
    assert s["avg_steam_pct"] == pytest.approx(80.0, abs=0.1)


def test_developer_portfolio_trajectory_improving(
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
) -> None:
    """Last 3 games avg > overall avg by 5+ → trajectory is 'improving'."""
    _seed_game(
        game_repo, 14000, developer_slug="indie-a", release_date="2018-01-01", positive_pct=50
    )
    _seed_game(
        game_repo, 14001, developer_slug="indie-a", release_date="2019-01-01", positive_pct=50
    )
    _seed_game(
        game_repo, 14002, developer_slug="indie-a", release_date="2020-01-01", positive_pct=90
    )
    _seed_game(
        game_repo, 14003, developer_slug="indie-a", release_date="2021-01-01", positive_pct=90
    )
    _seed_game(
        game_repo, 14004, developer_slug="indie-a", release_date="2022-01-01", positive_pct=90
    )

    result = analytics_repo.find_developer_portfolio("indie-a")
    assert result["summary"]["sentiment_trajectory"] == "improving"


def test_developer_portfolio_trajectory_declining(
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
) -> None:
    """Last 3 games avg < overall avg by 5+ → trajectory is 'declining'."""
    _seed_game(
        game_repo, 15000, developer_slug="indie-b", release_date="2018-01-01", positive_pct=90
    )
    _seed_game(
        game_repo, 15001, developer_slug="indie-b", release_date="2019-01-01", positive_pct=90
    )
    _seed_game(
        game_repo, 15002, developer_slug="indie-b", release_date="2020-01-01", positive_pct=50
    )
    _seed_game(
        game_repo, 15003, developer_slug="indie-b", release_date="2021-01-01", positive_pct=50
    )
    _seed_game(
        game_repo, 15004, developer_slug="indie-b", release_date="2022-01-01", positive_pct=50
    )

    result = analytics_repo.find_developer_portfolio("indie-b")
    assert result["summary"]["sentiment_trajectory"] == "declining"


def test_developer_portfolio_trajectory_stable(
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
) -> None:
    """All games at same sentiment → trajectory is 'stable'."""
    for i in range(4):
        _seed_game(
            game_repo,
            16000 + i,
            developer_slug="indie-c",
            release_date=f"202{i}-01-01",
            positive_pct=75,
        )

    result = analytics_repo.find_developer_portfolio("indie-c")
    assert result["summary"]["sentiment_trajectory"] == "stable"


def test_developer_portfolio_single_title(
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
) -> None:
    """A developer with only 1 game gets trajectory 'single_title'."""
    _seed_game(game_repo, 17000, developer_slug="solo-dev")

    result = analytics_repo.find_developer_portfolio("solo-dev")
    assert result["summary"]["sentiment_trajectory"] == "single_title"


# ---------------------------------------------------------------------------
# find_publisher_portfolio — mirrors find_developer_portfolio
# ---------------------------------------------------------------------------


def test_publisher_portfolio_basic(
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
) -> None:
    """Publisher portfolio returns entity_name under `publisher` key + games."""
    _seed_game(
        game_repo,
        18000,
        publisher="Big Pub",
        publisher_slug="big-pub",
        release_date="2022-01-01",
        positive_pct=80,
        review_count=500,
    )
    _seed_game(
        game_repo,
        18001,
        publisher="Big Pub",
        publisher_slug="big-pub",
        release_date="2023-01-01",
        positive_pct=80,
        review_count=500,
    )

    result = analytics_repo.find_publisher_portfolio("big-pub")
    assert result["publisher"] == "Big Pub"
    assert result["publisher_slug"] == "big-pub"
    assert result["summary"]["total_games"] == 2
    assert result["summary"]["total_reviews"] == 1000
    assert len(result["games"]) == 2


# ---------------------------------------------------------------------------
# query_metrics (Builder lens)
# ---------------------------------------------------------------------------


def test_query_metrics_catalog_single_metric(
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """Reads from mv_trend_catalog with no filter; returns releases per period."""
    _seed_game(game_repo, 18000, release_date="2024-01-15", positive_pct=80)
    _seed_game(game_repo, 18001, release_date="2024-01-20", positive_pct=72)
    _seed_game(game_repo, 18002, release_date="2024-02-10", positive_pct=90)
    refresh_matviews()

    rows = analytics_repo.query_metrics(metric_ids=["releases"], granularity="month", limit=12)
    # Two periods (2024-01 with 2 games, 2024-02 with 1).
    periods = {r["period"].strftime("%Y-%m"): r["releases"] for r in rows}
    assert periods["2024-01"] == 2
    assert periods["2024-02"] == 1


def test_query_metrics_multi_metric(
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """Multi-metric returns all requested keys per period."""
    _seed_game(game_repo, 18100, release_date="2024-03-01", positive_pct=80, price_usd=19.99)
    _seed_game(game_repo, 18101, release_date="2024-03-05", positive_pct=60, price_usd=9.99)
    refresh_matviews()

    rows = analytics_repo.query_metrics(
        metric_ids=["releases", "avg_steam_pct", "avg_paid_price"],
        granularity="month",
        limit=12,
    )
    assert len(rows) >= 1
    march = next(r for r in rows if r["period"].strftime("%Y-%m") == "2024-03")
    assert march["releases"] == 2
    assert float(march["avg_steam_pct"]) == pytest.approx(70.0, abs=0.1)
    assert float(march["avg_paid_price"]) == pytest.approx(14.99, abs=0.01)


def test_query_metrics_filter_by_genre(
    db_conn: Any,
    analytics_repo: AnalyticsRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """genre_slug routes to mv_trend_by_genre and filters correctly."""
    genre_id = _seed_genre(db_conn, "Action", "action-q")
    _seed_game(game_repo, 18200, release_date="2024-04-01")
    _link_genre(db_conn, 18200, genre_id)
    _seed_game(game_repo, 18201, release_date="2024-04-15")  # no genre
    refresh_matviews()

    rows = analytics_repo.query_metrics(
        metric_ids=["releases"], granularity="month", genre_slug="action-q", limit=12
    )
    april = next(r for r in rows if r["period"].strftime("%Y-%m") == "2024-04")
    assert april["releases"] == 1  # only the game linked to action-q


def test_query_metrics_combined_genre_and_tag_raises(
    analytics_repo: AnalyticsRepository,
) -> None:
    with pytest.raises(ValueError, match="combining"):
        analytics_repo.query_metrics(
            metric_ids=["releases"],
            granularity="month",
            genre_slug="action",
            tag_slug="indie",
        )


def test_query_metrics_unknown_metric_raises(
    analytics_repo: AnalyticsRepository,
) -> None:
    with pytest.raises(ValueError, match="unknown metric"):
        analytics_repo.query_metrics(metric_ids=["not_a_metric"], granularity="month")
