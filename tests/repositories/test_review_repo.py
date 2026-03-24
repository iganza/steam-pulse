"""Tests for ReviewRepository."""

from datetime import UTC, datetime, timedelta

import pytest
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.review_repo import ReviewRepository


def _seed_game(game_repo: GameRepository, appid: int = 440) -> None:
    game_repo.upsert({
        "appid": appid,
        "name": f"App {appid}",
        "slug": f"app-{appid}",
        "type": "game",
        "developer": None,
        "developer_slug": None,
        "publisher": None,
        "developers": "[]",
        "publishers": "[]",
        "website": None,
        "release_date": None,
        "coming_soon": False,
        "price_usd": None,
        "is_free": False,
        "short_desc": None,
        "detailed_description": None,
        "about_the_game": None,
        "review_count": 100,
        "review_count_english": 100,
        "total_positive": 80,
        "total_negative": 20,
        "positive_pct": 80,
        "review_score_desc": "Positive",
        "header_image": None,
        "background_image": None,
        "required_age": 0,
        "platforms": "{}",
        "supported_languages": None,
        "achievements_total": 0,
        "metacritic_score": None,
        "deck_compatibility": None,
        "deck_test_results": None,
        "data_source": "steam_direct",
    })


def _make_reviews(appid: int = 440, count: int = 3) -> list[dict]:
    base_ts = 1700000000
    return [
        {
            "appid": appid,
            "steam_review_id": f"rev-{appid}-{i}",
            "author_steamid": f"steam-{appid}-{i}",
            "voted_up": i % 2 == 0,
            "playtime_hours": i * 10,
            "body": f"Review body {i}",
            "posted_at": datetime.fromtimestamp(base_ts + i, tz=UTC),
            "language": "english",
            "votes_helpful": i,
            "votes_funny": 0,
            "written_during_early_access": False,
            "received_for_free": False,
        }
        for i in range(count)
    ]


def test_bulk_upsert_inserts_reviews(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    _seed_game(game_repo)
    reviews = _make_reviews(count=3)
    review_repo.bulk_upsert(reviews)
    assert review_repo.count_by_appid(440) == 3


def test_bulk_upsert_is_idempotent(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    _seed_game(game_repo)
    reviews = _make_reviews(count=3)
    review_repo.bulk_upsert(reviews)
    review_repo.bulk_upsert(reviews)  # second upsert — no duplicates
    assert review_repo.count_by_appid(440) == 3


def test_find_by_appid_paginates(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    _seed_game(game_repo)
    review_repo.bulk_upsert(_make_reviews(count=5))
    page1 = review_repo.find_by_appid(440, limit=2, offset=0)
    page2 = review_repo.find_by_appid(440, limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    # Pages should not overlap
    ids1 = {r.steam_review_id for r in page1}
    ids2 = {r.steam_review_id for r in page2}
    assert ids1.isdisjoint(ids2)


def test_latest_posted_at(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    _seed_game(game_repo)
    reviews = _make_reviews(count=3)
    review_repo.bulk_upsert(reviews)
    latest = review_repo.latest_posted_at(440)
    assert latest is not None
    # The latest should be the review with i=2 (base_ts + 2)
    expected = datetime.fromtimestamp(1700000002, tz=UTC)
    assert latest.replace(tzinfo=UTC) == expected


def test_latest_posted_at_returns_none_for_empty(
    review_repo: ReviewRepository,
) -> None:
    assert review_repo.latest_posted_at(9999) is None


# ---------------------------------------------------------------------------
# find_review_stats tests
# ---------------------------------------------------------------------------


def test_find_review_stats_empty_when_no_reviews(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """find_review_stats returns empty structures when the game has no reviews."""
    _seed_game(game_repo)
    stats = review_repo.find_review_stats(440)
    assert stats["timeline"] == []
    assert stats["playtime_buckets"] == []
    assert stats["review_velocity"]["reviews_per_day"] == 0.0
    assert stats["review_velocity"]["reviews_last_30_days"] == 0


def test_find_review_stats_timeline_keys_and_pct(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """Timeline entries expose week, total, positive, pct_positive with correct values."""
    _seed_game(game_repo)
    reviews = [
        {
            "appid": 440,
            "steam_review_id": "rs-1",
            "voted_up": True,
            "playtime_hours": 10,
            "body": "",
            "posted_at": datetime(2023, 10, 2, 12, 0, 0, tzinfo=UTC),
        },
        {
            "appid": 440,
            "steam_review_id": "rs-2",
            "voted_up": False,
            "playtime_hours": 5,
            "body": "",
            "posted_at": datetime(2023, 10, 2, 13, 0, 0, tzinfo=UTC),
        },
    ]
    review_repo.bulk_upsert(reviews)
    stats = review_repo.find_review_stats(440)
    assert len(stats["timeline"]) == 1
    entry = stats["timeline"][0]
    assert entry["total"] == 2
    assert entry["positive"] == 1
    assert entry["pct_positive"] == 50


def test_find_review_stats_groups_by_week(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """Reviews spanning 3 distinct weeks produce 3 separate timeline entries."""
    _seed_game(game_repo)
    base = datetime(2023, 10, 2, 12, 0, 0, tzinfo=UTC)  # a Monday
    reviews = [
        {
            "appid": 440,
            "steam_review_id": f"wk-{w}",
            "voted_up": True,
            "playtime_hours": 10,
            "body": "",
            "posted_at": base + timedelta(weeks=w),
        }
        for w in range(3)
    ]
    review_repo.bulk_upsert(reviews)
    stats = review_repo.find_review_stats(440)
    assert len(stats["timeline"]) == 3


def test_find_review_stats_playtime_buckets(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """One review per playtime range maps to the correct bucket label."""
    _seed_game(game_repo)
    cases = [(0, "0h"), (1, "<2h"), (5, "2-10h"), (20, "10-50h"), (100, "50-200h"), (300, "200h+")]
    reviews = [
        {
            "appid": 440,
            "steam_review_id": f"pt-{hours}",
            "voted_up": True,
            "playtime_hours": hours,
            "body": "",
            "posted_at": datetime(2023, 10, 2, 12, 0, 0, tzinfo=UTC),
        }
        for hours, _ in cases
    ]
    review_repo.bulk_upsert(reviews)
    stats = review_repo.find_review_stats(440)
    labels = {b["bucket"] for b in stats["playtime_buckets"]}
    assert labels == {"0h", "<2h", "2-10h", "10-50h", "50-200h", "200h+"}


def test_find_review_stats_velocity_nonzero(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """reviews_per_day is positive when the game has reviews with posted_at set."""
    _seed_game(game_repo)
    now = datetime.now(UTC)
    reviews = [
        {
            "appid": 440,
            "steam_review_id": f"vel-{i}",
            "voted_up": True,
            "playtime_hours": 5,
            "body": "",
            "posted_at": now - timedelta(days=i),
        }
        for i in range(5)
    ]
    review_repo.bulk_upsert(reviews)
    stats = review_repo.find_review_stats(440)
    assert stats["review_velocity"]["reviews_per_day"] > 0


# ---------------------------------------------------------------------------
# find_playtime_sentiment tests
# ---------------------------------------------------------------------------


def _make_review_pt(appid: int, rid: str, playtime: int, voted_up: bool, **kw: object) -> dict:
    return {
        "appid": appid,
        "steam_review_id": rid,
        "voted_up": voted_up,
        "playtime_hours": playtime,
        "body": "x",
        "posted_at": datetime(2024, 1, 1, tzinfo=UTC),
        "votes_helpful": kw.get("votes_helpful", 0),
        "votes_funny": kw.get("votes_funny", 0),
        "written_during_early_access": False,
        "received_for_free": False,
    }


def _seed_priced_game(game_repo: GameRepository, appid: int = 440, price_usd: float | None = 9.99, is_free: bool = False) -> None:
    game_repo.upsert({
        "appid": appid,
        "name": f"App {appid}",
        "slug": f"app-{appid}",
        "type": "game",
        "developer": None,
        "developer_slug": None,
        "publisher": None,
        "developers": "[]",
        "publishers": "[]",
        "website": None,
        "release_date": None,
        "coming_soon": False,
        "price_usd": price_usd,
        "is_free": is_free,
        "short_desc": None,
        "detailed_description": None,
        "about_the_game": None,
        "review_count": 100,
        "review_count_english": 100,
        "total_positive": 80,
        "total_negative": 20,
        "positive_pct": 80,
        "review_score_desc": "Positive",
        "header_image": None,
        "background_image": None,
        "required_age": 0,
        "platforms": "{}",
        "supported_languages": None,
        "achievements_total": 0,
        "metacritic_score": None,
        "deck_compatibility": None,
        "deck_test_results": None,
        "data_source": "steam_direct",
    })


def test_playtime_sentiment_buckets(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """Reviews land in the correct playtime bucket."""
    _seed_priced_game(game_repo)
    reviews = [
        _make_review_pt(440, "pt-0h", 0, True),
        _make_review_pt(440, "pt-0h-b", 0, True),  # same 0h bucket
        _make_review_pt(440, "pt-7h", 7, False),    # 5-10h bucket (< 10)
    ]
    review_repo.bulk_upsert(reviews)
    result = review_repo.find_playtime_sentiment(440)
    bucket_names = {b["bucket"] for b in result["buckets"]}
    assert "0h" in bucket_names
    assert "5-10h" in bucket_names


def test_playtime_sentiment_churn_wall_detected(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """A drop of >= 10 pts between adjacent buckets (both >= 5 reviews) is flagged."""
    _seed_priced_game(game_repo)
    # 5 reviews in 2-5h bucket: all positive (100%)
    reviews = [_make_review_pt(440, f"low-{i}", 3, True) for i in range(5)]
    # 5 reviews in 5-10h bucket: all negative (0%) → drop of 100 pts
    reviews += [_make_review_pt(440, f"high-{i}", 7, False) for i in range(5)]
    review_repo.bulk_upsert(reviews)

    result = review_repo.find_playtime_sentiment(440)
    assert result["churn_point"] is not None
    assert result["churn_point"]["delta"] < -10


def test_playtime_sentiment_no_churn_wall(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """No churn_point when sentiment is consistent across buckets."""
    _seed_priced_game(game_repo)
    # Spread reviews with consistent ~80% positive across a few buckets
    reviews = [_make_review_pt(440, f"c-low-{i}", 3, i < 4) for i in range(5)]
    reviews += [_make_review_pt(440, f"c-high-{i}", 7, i < 4) for i in range(5)]
    review_repo.bulk_upsert(reviews)

    result = review_repo.find_playtime_sentiment(440)
    assert result["churn_point"] is None


def test_playtime_sentiment_value_score(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """value_score = median_playtime / price_usd; None for free games."""
    _seed_priced_game(game_repo, 440, price_usd=10.0)
    # 5 reviews all at 20h playtime → median = 20h
    reviews = [_make_review_pt(440, f"vs-{i}", 20, True) for i in range(5)]
    review_repo.bulk_upsert(reviews)
    result = review_repo.find_playtime_sentiment(440)
    assert result["value_score"] == pytest.approx(2.0, abs=0.01)

    # Now a free game — value_score should be None
    _seed_priced_game(game_repo, 441, price_usd=None, is_free=True)
    reviews2 = [_make_review_pt(441, f"free-{i}", 10, True) for i in range(3)]
    review_repo.bulk_upsert(reviews2)
    result2 = review_repo.find_playtime_sentiment(441)
    assert result2["value_score"] is None


# ---------------------------------------------------------------------------
# find_early_access_impact tests
# ---------------------------------------------------------------------------


def test_early_access_impact_improved(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """Post-launch pct > EA pct by >= 5 → verdict 'improved'."""
    _seed_game(game_repo)
    # EA: 5 reviews, 50% positive
    ea = [
        {**_make_reviews(count=1)[0], "steam_review_id": f"ea-{i}",
         "voted_up": i < 5, "written_during_early_access": True}
        for i in range(10)
    ]
    # Post: 10 reviews, 90% positive
    post = [
        {**_make_reviews(count=1)[0], "steam_review_id": f"post-{i}",
         "voted_up": i < 9, "written_during_early_access": False}
        for i in range(10)
    ]
    review_repo.bulk_upsert(ea + post)
    result = review_repo.find_early_access_impact(440)
    assert result["verdict"] == "improved"
    assert result["has_ea_reviews"] is True


def test_early_access_impact_declined(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """Post-launch pct < EA pct by >= 5 → verdict 'declined'."""
    _seed_game(game_repo)
    ea = [
        {**_make_reviews(count=1)[0], "steam_review_id": f"ea2-{i}",
         "voted_up": i < 9, "written_during_early_access": True}
        for i in range(10)
    ]
    post = [
        {**_make_reviews(count=1)[0], "steam_review_id": f"post2-{i}",
         "voted_up": i < 5, "written_during_early_access": False}
        for i in range(10)
    ]
    review_repo.bulk_upsert(ea + post)
    result = review_repo.find_early_access_impact(440)
    assert result["verdict"] == "declined"


def test_early_access_impact_stable(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """Sentiment delta within 5 pts → verdict 'stable'."""
    _seed_game(game_repo)
    # EA: 7/10 = 70%, post: 7/10 = 70% → delta = 0, well within the 5pt threshold
    ea = [
        {**_make_reviews(count=1)[0], "steam_review_id": f"ea3-{i}",
         "voted_up": i < 7, "written_during_early_access": True}
        for i in range(10)
    ]
    post = [
        {**_make_reviews(count=1)[0], "steam_review_id": f"post3-{i}",
         "voted_up": i < 7, "written_during_early_access": False}
        for i in range(10)
    ]
    review_repo.bulk_upsert(ea + post)
    result = review_repo.find_early_access_impact(440)
    assert result["verdict"] == "stable"


def test_early_access_impact_no_ea(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """No EA reviews → verdict 'no_ea' and early_access is None."""
    _seed_game(game_repo)
    reviews = [
        {**_make_reviews(count=1)[0], "steam_review_id": f"noea-{i}",
         "written_during_early_access": False}
        for i in range(5)
    ]
    review_repo.bulk_upsert(reviews)
    result = review_repo.find_early_access_impact(440)
    assert result["verdict"] == "no_ea"
    assert result["early_access"] is None
    assert result["has_ea_reviews"] is False


def test_early_access_impact_no_post(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """EA reviews exist but no post-launch reviews → verdict 'no_post', impact_delta None."""
    _seed_game(game_repo)
    ea = [
        {**_make_reviews(count=1)[0], "steam_review_id": f"ea-nopost-{i}",
         "voted_up": True, "written_during_early_access": True}
        for i in range(5)
    ]
    review_repo.bulk_upsert(ea)
    result = review_repo.find_early_access_impact(440)
    assert result["verdict"] == "no_post"
    assert result["has_ea_reviews"] is True
    assert result["post_launch"] is None
    assert result["impact_delta"] is None


# ---------------------------------------------------------------------------
# find_review_velocity tests
# ---------------------------------------------------------------------------


def test_review_velocity_trend_accelerating(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """last_3_months_avg > avg_monthly * 1.2 → trend 'accelerating'."""
    _seed_game(game_repo)
    now = datetime.now(UTC)
    reviews = []
    # 20 months of 2 reviews each (avg = 2), then last 3 months: 10 each
    for m in range(20, 3, -1):
        for j in range(2):
            reviews.append({
                "appid": 440,
                "steam_review_id": f"vel-acc-{m}-{j}",
                "voted_up": True,
                "playtime_hours": 5,
                "body": "",
                "posted_at": now - timedelta(days=m * 30 + j),
            })
    for m in range(3):
        for j in range(10):
            reviews.append({
                "appid": 440,
                "steam_review_id": f"vel-acc-recent-{m}-{j}",
                "voted_up": True,
                "playtime_hours": 5,
                "body": "",
                "posted_at": now - timedelta(days=m * 30 + j),
            })
    review_repo.bulk_upsert(reviews)
    result = review_repo.find_review_velocity(440)
    assert result["summary"]["trend"] == "accelerating"


def test_review_velocity_trend_decelerating(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """last_3_months_avg < avg_monthly * 0.8 → trend 'decelerating'."""
    _seed_game(game_repo)
    now = datetime.now(UTC)
    reviews = []
    # 20 months of 10 reviews each (avg = 10), then last 3 months: 1 each
    for m in range(20, 3, -1):
        for j in range(10):
            reviews.append({
                "appid": 440,
                "steam_review_id": f"vel-dec-{m}-{j}",
                "voted_up": True,
                "playtime_hours": 5,
                "body": "",
                "posted_at": now - timedelta(days=m * 30 + j),
            })
    for m in range(3):
        reviews.append({
            "appid": 440,
            "steam_review_id": f"vel-dec-recent-{m}",
            "voted_up": True,
            "playtime_hours": 5,
            "body": "",
            "posted_at": now - timedelta(days=m * 30),
        })
    review_repo.bulk_upsert(reviews)
    result = review_repo.find_review_velocity(440)
    assert result["summary"]["trend"] == "decelerating"


def test_review_velocity_peak_month(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """peak_month is the month with the highest review count."""
    _seed_game(game_repo)
    now = datetime.now(UTC)
    reviews = []
    # 1 review 10 months ago, 5 reviews 2 months ago
    reviews.append({
        "appid": 440, "steam_review_id": "vm-old",
        "voted_up": True, "playtime_hours": 5, "body": "",
        "posted_at": now - timedelta(days=300),
    })
    for j in range(5):
        reviews.append({
            "appid": 440, "steam_review_id": f"vm-recent-{j}",
            "voted_up": True, "playtime_hours": 5, "body": "",
            "posted_at": now - timedelta(days=60 + j),
        })
    review_repo.bulk_upsert(reviews)
    result = review_repo.find_review_velocity(440)
    assert result["summary"]["peak_month"]["total"] == 5


# ---------------------------------------------------------------------------
# find_top_reviews tests
# ---------------------------------------------------------------------------


def test_top_reviews_sort_helpful(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """Reviews are ordered by votes_helpful DESC."""
    _seed_game(game_repo)
    reviews = [
        _make_review_pt(440, f"tr-{i}", 10, True, votes_helpful=i * 10)
        for i in range(5)
    ]
    review_repo.bulk_upsert(reviews)
    result = review_repo.find_top_reviews(440, sort="helpful", limit=5)
    helpful_counts = [r["votes_helpful"] for r in result]
    assert helpful_counts == sorted(helpful_counts, reverse=True)


def test_top_reviews_sort_funny(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """Reviews are ordered by votes_funny DESC."""
    _seed_game(game_repo)
    reviews = [
        _make_review_pt(440, f"tf-{i}", 10, True, votes_funny=i * 5, votes_helpful=1)
        for i in range(5)
    ]
    review_repo.bulk_upsert(reviews)
    result = review_repo.find_top_reviews(440, sort="funny", limit=5)
    funny_counts = [r["votes_funny"] for r in result]
    assert funny_counts == sorted(funny_counts, reverse=True)


def test_top_reviews_limit(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    """Result is capped at the requested limit."""
    _seed_game(game_repo)
    reviews = [
        _make_review_pt(440, f"lim-{i}", 10, True, votes_helpful=i + 1)
        for i in range(10)
    ]
    review_repo.bulk_upsert(reviews)
    result = review_repo.find_top_reviews(440, sort="helpful", limit=3)
    assert len(result) == 3
