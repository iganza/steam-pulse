"""Tests for CatalogRepository."""

from library_layer.repositories.catalog_repo import CatalogRepository


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


def test_mark_reviews_complete_sets_timestamp(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert([{"appid": 100, "name": "G"}])
    catalog_repo.mark_reviews_complete(100)
    entry = catalog_repo.find_by_appid(100)
    assert entry is not None
    assert entry.reviews_completed_at is not None


def test_mark_reviews_complete_overwrites_previous_timestamp(
    catalog_repo: CatalogRepository,
) -> None:
    catalog_repo.bulk_upsert([{"appid": 101, "name": "G"}])
    catalog_repo.mark_reviews_complete(101)
    t1 = catalog_repo.find_by_appid(101).reviews_completed_at
    catalog_repo.mark_reviews_complete(101)
    t2 = catalog_repo.find_by_appid(101).reviews_completed_at
    assert t2 >= t1


def test_get_reviews_completed_at_none_before_any_crawl(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert([{"appid": 200, "name": "G"}])
    assert catalog_repo.get_reviews_completed_at(200) is None


def test_get_reviews_completed_at_returns_timestamp_after_complete(
    catalog_repo: CatalogRepository,
) -> None:
    catalog_repo.bulk_upsert([{"appid": 201, "name": "G"}])
    catalog_repo.mark_reviews_complete(201)
    assert catalog_repo.get_reviews_completed_at(201) is not None


def test_get_reviews_completed_at_none_for_missing_appid(catalog_repo: CatalogRepository) -> None:
    assert catalog_repo.get_reviews_completed_at(99999) is None


def _set_meta_crawled_at(catalog_repo: CatalogRepository, appid: int, days_ago: int) -> None:
    with catalog_repo.conn.cursor() as cur:
        cur.execute(
            "UPDATE app_catalog SET meta_crawled_at = NOW() - (%s || ' days')::interval WHERE appid = %s",
            (days_ago, appid),
        )
    catalog_repo.conn.commit()


def test_find_stale_meta_tier3_default(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert([{"appid": 7001, "name": "A"}, {"appid": 7002, "name": "B"}])
    catalog_repo.set_meta_status(7001, "done")
    catalog_repo.set_meta_status(7002, "done")
    _set_meta_crawled_at(catalog_repo, 7001, days_ago=40)  # stale tier 3
    _set_meta_crawled_at(catalog_repo, 7002, days_ago=5)  # fresh
    stale = catalog_repo.find_stale_meta(limit=10)
    appids = [e.appid for e in stale]
    assert 7001 in appids
    assert 7002 not in appids


def test_find_stale_meta_nulls_first(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert([{"appid": 7100, "name": "Legacy"}])
    # Legacy row: set meta_status='done' but keep meta_crawled_at NULL
    with catalog_repo.conn.cursor() as cur:
        cur.execute(
            "UPDATE app_catalog SET meta_status='done', meta_crawled_at=NULL WHERE appid = 7100"
        )
    catalog_repo.conn.commit()
    stale = catalog_repo.find_stale_meta(limit=10)
    assert 7100 in [e.appid for e in stale]


def test_find_stale_meta_respects_limit(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert([{"appid": 7200 + i, "name": f"G{i}"} for i in range(5)])
    for i in range(5):
        catalog_repo.set_meta_status(7200 + i, "done")
        _set_meta_crawled_at(catalog_repo, 7200 + i, days_ago=60)
    stale = catalog_repo.find_stale_meta(limit=3)
    assert len(stale) == 3
