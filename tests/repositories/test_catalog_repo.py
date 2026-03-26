"""Tests for CatalogRepository."""

from typing import Any

from library_layer.repositories.catalog_repo import CatalogRepository
from library_layer.repositories.game_repo import GameRepository


def _seed_game(
    db_conn: Any,
    appid: int,
    *,
    review_count_english: int = 100,
    coming_soon: bool = False,
    release_date: str | None = "2023-01-01",
) -> None:
    GameRepository(db_conn).upsert({
        "appid": appid,
        "name": f"Game {appid}",
        "slug": f"game-{appid}",
        "type": "game",
        "developer": None,
        "developer_slug": None,
        "publisher": None,
        "developers": "[]",
        "publishers": "[]",
        "website": None,
        "release_date": release_date,
        "coming_soon": coming_soon,
        "price_usd": None,
        "is_free": False,
        "short_desc": None,
        "detailed_description": None,
        "about_the_game": None,
        "review_count": review_count_english,
        "review_count_english": review_count_english,
        "total_positive": review_count_english,
        "total_negative": 0,
        "positive_pct": 100,
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


def _entries(n: int = 3) -> list[dict]:
    return [{"appid": 1000 + i, "name": f"Game {i}"} for i in range(n)]


def test_bulk_upsert_inserts_new_rows(catalog_repo: CatalogRepository) -> None:
    new_rows = catalog_repo.bulk_upsert(_entries(3))
    assert new_rows == 3


def test_bulk_upsert_skips_existing(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert(_entries(3))
    # Second upsert with same + 2 new
    entries = [*_entries(3), {"appid": 2000, "name": "New"}, {"appid": 2001, "name": "New2"}]
    new_rows = catalog_repo.bulk_upsert(entries)
    assert new_rows == 2


def test_find_by_appid(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert([{"appid": 5000, "name": "Test Game"}])
    entry = catalog_repo.find_by_appid(5000)
    assert entry is not None
    assert entry.name == "Test Game"
    assert entry.meta_status == "pending"


def test_find_pending_meta(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert(_entries(3))
    # Mark one as done
    catalog_repo.set_meta_status(1000, "done")
    pending = catalog_repo.find_pending_meta()
    appids = [e.appid for e in pending]
    assert 1000 not in appids
    assert 1001 in appids
    assert 1002 in appids


def test_set_meta_status_with_review_count(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert([{"appid": 500, "name": "Big Game"}])
    catalog_repo.set_meta_status(500, "done", review_count=1500)
    entry = catalog_repo.find_by_appid(500)
    assert entry is not None
    assert entry.meta_status == "done"
    assert entry.review_count == 1500


def test_status_summary(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert(_entries(5))
    catalog_repo.set_meta_status(1000, "done")
    catalog_repo.set_meta_status(1001, "failed")
    summary = catalog_repo.status_summary()
    assert summary["meta"].get("done", 0) >= 1
    assert summary["meta"].get("failed", 0) >= 1
    assert summary["meta"].get("pending", 0) >= 3


def test_mark_reviews_complete_sets_cursor_null_and_timestamp(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert([{"appid": 100, "name": "G"}])
    catalog_repo.save_review_cursor(100, "abc123")
    catalog_repo.mark_reviews_complete(100)
    entry = catalog_repo.find_by_appid(100)
    assert entry is not None
    assert entry.review_cursor is None
    assert entry.reviews_completed_at is not None


def test_mark_reviews_complete_overwrites_previous_timestamp(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert([{"appid": 101, "name": "G"}])
    catalog_repo.mark_reviews_complete(101)
    t1 = catalog_repo.find_by_appid(101).reviews_completed_at
    catalog_repo.save_review_cursor(101, "new_cursor")
    catalog_repo.mark_reviews_complete(101)
    t2 = catalog_repo.find_by_appid(101).reviews_completed_at
    assert t2 >= t1


def test_get_reviews_completed_at_none_before_any_crawl(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert([{"appid": 200, "name": "G"}])
    assert catalog_repo.get_reviews_completed_at(200) is None


def test_get_reviews_completed_at_returns_timestamp_after_complete(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert([{"appid": 201, "name": "G"}])
    catalog_repo.mark_reviews_complete(201)
    assert catalog_repo.get_reviews_completed_at(201) is not None


def test_get_reviews_completed_at_none_for_missing_appid(catalog_repo: CatalogRepository) -> None:
    assert catalog_repo.get_reviews_completed_at(99999) is None


def test_find_uncrawled_eligible_returns_eligible_appids(
    catalog_repo: CatalogRepository, db_conn: Any
) -> None:
    _seed_game(db_conn, 3000, review_count_english=200, release_date="2023-06-01")
    catalog_repo.bulk_upsert([{"appid": 3000, "name": "G"}])
    catalog_repo.set_meta_status(3000, "done")

    result = catalog_repo.find_uncrawled_eligible(threshold=50, limit=10)
    assert 3000 in result


def test_find_uncrawled_eligible_excludes_completed(
    catalog_repo: CatalogRepository, db_conn: Any
) -> None:
    _seed_game(db_conn, 3001, review_count_english=200, release_date="2023-06-01")
    catalog_repo.bulk_upsert([{"appid": 3001, "name": "G"}])
    catalog_repo.set_meta_status(3001, "done")
    catalog_repo.mark_reviews_complete(3001)

    result = catalog_repo.find_uncrawled_eligible(threshold=50, limit=10)
    assert 3001 not in result


def test_find_uncrawled_eligible_excludes_below_threshold(
    catalog_repo: CatalogRepository, db_conn: Any
) -> None:
    _seed_game(db_conn, 3002, review_count_english=10, release_date="2023-06-01")
    catalog_repo.bulk_upsert([{"appid": 3002, "name": "G"}])
    catalog_repo.set_meta_status(3002, "done")

    result = catalog_repo.find_uncrawled_eligible(threshold=50, limit=10)
    assert 3002 not in result


def test_find_uncrawled_eligible_excludes_coming_soon(
    catalog_repo: CatalogRepository, db_conn: Any
) -> None:
    _seed_game(db_conn, 3003, review_count_english=200, coming_soon=True, release_date="2025-01-01")
    catalog_repo.bulk_upsert([{"appid": 3003, "name": "G"}])
    catalog_repo.set_meta_status(3003, "done")

    result = catalog_repo.find_uncrawled_eligible(threshold=50, limit=10)
    assert 3003 not in result


def test_find_uncrawled_eligible_orders_newest_first(
    catalog_repo: CatalogRepository, db_conn: Any
) -> None:
    _seed_game(db_conn, 3010, review_count_english=200, release_date="2022-01-01")
    _seed_game(db_conn, 3011, review_count_english=200, release_date="2024-01-01")
    catalog_repo.bulk_upsert([{"appid": 3010, "name": "Old"}, {"appid": 3011, "name": "New"}])
    catalog_repo.set_meta_status(3010, "done")
    catalog_repo.set_meta_status(3011, "done")

    result = catalog_repo.find_uncrawled_eligible(threshold=50, limit=10)
    assert result.index(3011) < result.index(3010)


def test_find_uncrawled_eligible_is_idempotent(
    catalog_repo: CatalogRepository, db_conn: Any
) -> None:
    _seed_game(db_conn, 3020, review_count_english=200, release_date="2023-06-01")
    catalog_repo.bulk_upsert([{"appid": 3020, "name": "G"}])
    catalog_repo.set_meta_status(3020, "done")

    first = catalog_repo.find_uncrawled_eligible(threshold=50, limit=10)
    assert 3020 in first
    # Commit to persist the claim (simulating a successful SQS send)
    catalog_repo.conn.commit()

    # Second call must not return the same appid — it was claimed (review_cursor='*')
    second = catalog_repo.find_uncrawled_eligible(threshold=50, limit=10)
    catalog_repo.conn.rollback()
    assert 3020 not in second
