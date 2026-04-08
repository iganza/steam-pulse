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


def _seed_game_row(catalog_repo: CatalogRepository, appid: int, coming_soon: bool = False) -> None:
    """Insert a minimal `games` row so the LEFT JOIN in find_stale_meta has data."""
    with catalog_repo.conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO games (appid, name, slug, type, coming_soon)
            VALUES (%s, %s, %s, 'game', %s)
            ON CONFLICT (appid) DO UPDATE SET coming_soon = EXCLUDED.coming_soon
            """,
            (appid, f"Game {appid}", f"game-{appid}", coming_soon),
        )
    catalog_repo.conn.commit()


def _attach_genre(catalog_repo: CatalogRepository, appid: int, genre_id: int) -> None:
    with catalog_repo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO genres (id, name, slug) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (genre_id, f"Genre {genre_id}", f"genre-{genre_id}"),
        )
        cur.execute(
            "INSERT INTO game_genres (appid, genre_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (appid, genre_id),
        )
    catalog_repo.conn.commit()


def test_find_stale_meta_tier1_early_access(catalog_repo: CatalogRepository) -> None:
    # EA game (genre 70) crawled 8d ago — should be stale (tier 1: 7d)
    catalog_repo.bulk_upsert([{"appid": 7300, "name": "EA Game"}])
    catalog_repo.set_meta_status(7300, "done")
    _seed_game_row(catalog_repo, 7300)
    _attach_genre(catalog_repo, 7300, 70)
    _set_meta_crawled_at(catalog_repo, 7300, days_ago=8)

    # Non-EA game crawled 8d ago — NOT yet stale (tier 3 needs 30d)
    catalog_repo.bulk_upsert([{"appid": 7301, "name": "Old Game"}])
    catalog_repo.set_meta_status(7301, "done")
    _set_meta_crawled_at(catalog_repo, 7301, days_ago=8)

    appids = [e.appid for e in catalog_repo.find_stale_meta(limit=10)]
    assert 7300 in appids
    assert 7301 not in appids


def test_find_stale_meta_tier1_coming_soon(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert([{"appid": 7400, "name": "Upcoming"}])
    catalog_repo.set_meta_status(7400, "done")
    _seed_game_row(catalog_repo, 7400, coming_soon=True)
    _set_meta_crawled_at(catalog_repo, 7400, days_ago=8)

    assert 7400 in [e.appid for e in catalog_repo.find_stale_meta(limit=10)]


def test_find_stale_meta_tier2_popular(catalog_repo: CatalogRepository) -> None:
    # Popular game (review_count >= 1000) crawled 8d ago — stale (tier 2: 7d)
    catalog_repo.bulk_upsert([{"appid": 7500, "name": "Popular"}])
    catalog_repo.set_meta_status(7500, "done", review_count=1500)
    _set_meta_crawled_at(catalog_repo, 7500, days_ago=8)

    # Unpopular game same age — not stale (tier 3 needs 30d)
    catalog_repo.bulk_upsert([{"appid": 7501, "name": "Niche"}])
    catalog_repo.set_meta_status(7501, "done", review_count=10)
    _set_meta_crawled_at(catalog_repo, 7501, days_ago=8)

    appids = [e.appid for e in catalog_repo.find_stale_meta(limit=10)]
    assert 7500 in appids
    assert 7501 not in appids


def test_find_stale_meta_priority_ordering(catalog_repo: CatalogRepository) -> None:
    # Tier 3 (oldest), tier 2, tier 1 — should be returned in priority order regardless of age
    catalog_repo.bulk_upsert(
        [
            {"appid": 7600, "name": "Old Niche"},
            {"appid": 7601, "name": "Popular"},
            {"appid": 7602, "name": "EA"},
        ]
    )
    catalog_repo.set_meta_status(7600, "done", review_count=10)
    catalog_repo.set_meta_status(7601, "done", review_count=2000)
    catalog_repo.set_meta_status(7602, "done")
    _seed_game_row(catalog_repo, 7602)
    _attach_genre(catalog_repo, 7602, 70)
    _set_meta_crawled_at(catalog_repo, 7600, days_ago=60)  # tier 3
    _set_meta_crawled_at(catalog_repo, 7601, days_ago=10)  # tier 2
    _set_meta_crawled_at(catalog_repo, 7602, days_ago=10)  # tier 1

    appids = [e.appid for e in catalog_repo.find_stale_meta(limit=10)]
    # Tier 1 first, then tier 2, then tier 3
    assert appids.index(7602) < appids.index(7601) < appids.index(7600)


def test_find_stale_meta_respects_limit(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert([{"appid": 7200 + i, "name": f"G{i}"} for i in range(5)])
    for i in range(5):
        catalog_repo.set_meta_status(7200 + i, "done")
        _set_meta_crawled_at(catalog_repo, 7200 + i, days_ago=60)
    stale = catalog_repo.find_stale_meta(limit=3)
    assert len(stale) == 3
