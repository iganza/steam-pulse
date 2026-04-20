"""Tests for CatalogRepository."""

from library_layer.config import SteamPulseConfig
from library_layer.repositories.catalog_repo import CatalogRepository


def _config() -> SteamPulseConfig:
    return SteamPulseConfig()


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


def _set_review_crawled_at(
    catalog_repo: CatalogRepository, appid: int, days_ago: int
) -> None:
    with catalog_repo.conn.cursor() as cur:
        cur.execute(
            "UPDATE app_catalog SET review_crawled_at = NOW() - (%s || ' days')::interval WHERE appid = %s",
            (days_ago, appid),
        )
    catalog_repo.conn.commit()


def _seed_game_row(
    catalog_repo: CatalogRepository,
    appid: int,
    coming_soon: bool = False,
    review_count: int = 0,
) -> None:
    """Insert a minimal `games` row for the JOIN in tiered refresh queries."""
    with catalog_repo.conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO games (appid, name, slug, type, coming_soon, review_count)
            VALUES (%s, %s, %s, 'game', %s, %s)
            ON CONFLICT (appid) DO UPDATE SET
                coming_soon = EXCLUDED.coming_soon,
                review_count = EXCLUDED.review_count
            """,
            (appid, f"Game {appid}", f"game-{appid}", coming_soon, review_count),
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


# ── find_due_meta ────────────────────────────────────────────────────────────


def test_find_due_meta_s_tier_due_past_window(catalog_repo: CatalogRepository) -> None:
    """S-tier games (>=10k reviews) become due after ~2 days + smear."""
    catalog_repo.bulk_upsert([{"appid": 7001, "name": "Blockbuster"}])
    catalog_repo.set_meta_status(7001, "done")
    _seed_game_row(catalog_repo, 7001, review_count=50_000)
    _set_meta_crawled_at(catalog_repo, 7001, days_ago=5)  # well past 2d + 2d max smear

    appids = [e.appid for e in catalog_repo.find_due_meta(limit=10, config=_config())]
    assert 7001 in appids


def test_find_due_meta_s_tier_fresh_not_due(catalog_repo: CatalogRepository) -> None:
    """S-tier crawled < tier window ago is not due even without smear."""
    catalog_repo.bulk_upsert([{"appid": 7002, "name": "Blockbuster"}])
    catalog_repo.set_meta_status(7002, "done")
    _seed_game_row(catalog_repo, 7002, review_count=50_000)
    _set_meta_crawled_at(catalog_repo, 7002, days_ago=1)  # inside 2d window

    appids = [e.appid for e in catalog_repo.find_due_meta(limit=10, config=_config())]
    assert 7002 not in appids


def test_find_due_meta_a_tier_coming_soon(catalog_repo: CatalogRepository) -> None:
    """coming_soon=TRUE puts a game in A-tier (7d window) regardless of review count."""
    catalog_repo.bulk_upsert([{"appid": 7400, "name": "Upcoming"}])
    catalog_repo.set_meta_status(7400, "done")
    _seed_game_row(catalog_repo, 7400, coming_soon=True, review_count=0)
    _set_meta_crawled_at(catalog_repo, 7400, days_ago=20)  # past 7d + 7d max smear

    appids = [e.appid for e in catalog_repo.find_due_meta(limit=10, config=_config())]
    assert 7400 in appids


def test_find_due_meta_a_tier_ea_genre(catalog_repo: CatalogRepository) -> None:
    """EA genre (id=70) puts a game in A-tier."""
    catalog_repo.bulk_upsert([{"appid": 7300, "name": "EA Game"}])
    catalog_repo.set_meta_status(7300, "done")
    _seed_game_row(catalog_repo, 7300, review_count=10)
    _attach_genre(catalog_repo, 7300, 70)
    _set_meta_crawled_at(catalog_repo, 7300, days_ago=20)

    appids = [e.appid for e in catalog_repo.find_due_meta(limit=10, config=_config())]
    assert 7300 in appids


def test_find_due_meta_b_tier_eligible_vs_c_tier_tail(
    catalog_repo: CatalogRepository,
) -> None:
    """B-tier (>=50 reviews) due at 21d; C-tier long tail needs 90d."""
    catalog_repo.bulk_upsert(
        [{"appid": 7500, "name": "Mid"}, {"appid": 7501, "name": "Tail"}]
    )
    catalog_repo.set_meta_status(7500, "done")
    catalog_repo.set_meta_status(7501, "done")
    _seed_game_row(catalog_repo, 7500, review_count=200)  # B
    _seed_game_row(catalog_repo, 7501, review_count=5)  # C
    _set_meta_crawled_at(catalog_repo, 7500, days_ago=45)  # past 21d + 21d smear
    _set_meta_crawled_at(catalog_repo, 7501, days_ago=45)  # still inside 90d C window

    appids = [e.appid for e in catalog_repo.find_due_meta(limit=10, config=_config())]
    assert 7500 in appids
    assert 7501 not in appids


def test_find_due_meta_nulls_first(catalog_repo: CatalogRepository) -> None:
    """Legacy rows with NULL meta_crawled_at refresh immediately."""
    catalog_repo.bulk_upsert([{"appid": 7100, "name": "Legacy"}])
    catalog_repo.set_meta_status(7100, "done")
    _seed_game_row(catalog_repo, 7100, review_count=100)
    with catalog_repo.conn.cursor() as cur:
        cur.execute("UPDATE app_catalog SET meta_crawled_at=NULL WHERE appid = 7100")
    catalog_repo.conn.commit()

    appids = [e.appid for e in catalog_repo.find_due_meta(limit=10, config=_config())]
    assert 7100 in appids


def test_find_due_meta_tier_ranking_s_before_a_before_b(
    catalog_repo: CatalogRepository,
) -> None:
    """Result order: S tier → A tier → B tier (by tier_rank)."""
    catalog_repo.bulk_upsert(
        [
            {"appid": 7600, "name": "Tail"},
            {"appid": 7601, "name": "Popular"},
            {"appid": 7602, "name": "Blockbuster"},
        ]
    )
    catalog_repo.set_meta_status(7600, "done")
    catalog_repo.set_meta_status(7601, "done")
    catalog_repo.set_meta_status(7602, "done")
    _seed_game_row(catalog_repo, 7600, review_count=100)  # B
    _seed_game_row(catalog_repo, 7601, review_count=2_000)  # A
    _seed_game_row(catalog_repo, 7602, review_count=50_000)  # S
    for appid in (7600, 7601, 7602):
        _set_meta_crawled_at(catalog_repo, appid, days_ago=180)  # everyone due

    appids = [e.appid for e in catalog_repo.find_due_meta(limit=10, config=_config())]
    assert appids.index(7602) < appids.index(7601) < appids.index(7600)


def test_find_due_meta_respects_limit(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert([{"appid": 7200 + i, "name": f"G{i}"} for i in range(5)])
    for i in range(5):
        appid = 7200 + i
        catalog_repo.set_meta_status(appid, "done")
        _seed_game_row(catalog_repo, appid, review_count=100)
        _set_meta_crawled_at(catalog_repo, appid, days_ago=180)
    due = catalog_repo.find_due_meta(limit=3, config=_config())
    assert len(due) == 3


def test_find_due_meta_smear_spreads_due_times(
    catalog_repo: CatalogRepository,
) -> None:
    """Deterministic smear: games with identical tier+crawl-time are NOT all due simultaneously.

    With S-tier (2d window) and meta_crawled_at exactly 2d ago, the hash-based
    offset pushes each game's due time into [now, now+2d]. Some subset is due
    (hash bucket in [0, ~0s]), the rest aren't yet. Compared to the old
    un-smeared query which would return all 10, the smeared query returns fewer.
    """
    appids = list(range(8000, 8020))  # 20 games, diverse appids → diverse hashes
    catalog_repo.bulk_upsert([{"appid": a, "name": f"G{a}"} for a in appids])
    for appid in appids:
        catalog_repo.set_meta_status(appid, "done")
        _seed_game_row(catalog_repo, appid, review_count=50_000)  # all S tier
        _set_meta_crawled_at(catalog_repo, appid, days_ago=2)  # exactly at window boundary

    due = catalog_repo.find_due_meta(limit=100, config=_config())
    # With 20 appids and a 2d smear window, very nearly zero should be due
    # at exactly last_crawl + window. Without smearing, all 20 would be due.
    assert len(due) < len(appids)


# ── find_due_reviews ─────────────────────────────────────────────────────────


def test_find_due_reviews_excludes_tier_c(catalog_repo: CatalogRepository) -> None:
    """Games with review_count < B-tier threshold (50) never appear in review refresh."""
    catalog_repo.bulk_upsert([{"appid": 8100, "name": "LowSignal"}])
    catalog_repo.set_meta_status(8100, "done")
    _seed_game_row(catalog_repo, 8100, review_count=10)  # tier C
    # Even with NULL review_crawled_at, it must not appear
    with catalog_repo.conn.cursor() as cur:
        cur.execute("UPDATE app_catalog SET review_crawled_at=NULL WHERE appid = 8100")
    catalog_repo.conn.commit()

    appids = [e.appid for e in catalog_repo.find_due_reviews(limit=10, config=_config())]
    assert 8100 not in appids


def test_find_due_reviews_excludes_coming_soon(catalog_repo: CatalogRepository) -> None:
    """Unreleased games skip review refresh — they get reviews after launch naturally."""
    catalog_repo.bulk_upsert([{"appid": 8200, "name": "PreRelease"}])
    catalog_repo.set_meta_status(8200, "done")
    _seed_game_row(catalog_repo, 8200, coming_soon=True, review_count=200)
    with catalog_repo.conn.cursor() as cur:
        cur.execute("UPDATE app_catalog SET review_crawled_at=NULL WHERE appid = 8200")
    catalog_repo.conn.commit()

    appids = [e.appid for e in catalog_repo.find_due_reviews(limit=10, config=_config())]
    assert 8200 not in appids


def test_find_due_reviews_s_tier_due(catalog_repo: CatalogRepository) -> None:
    """S-tier review window is 1 day."""
    catalog_repo.bulk_upsert([{"appid": 8300, "name": "Popular"}])
    catalog_repo.set_meta_status(8300, "done")
    _seed_game_row(catalog_repo, 8300, review_count=50_000)
    _set_review_crawled_at(catalog_repo, 8300, days_ago=3)  # past 1d + 1d smear

    appids = [e.appid for e in catalog_repo.find_due_reviews(limit=10, config=_config())]
    assert 8300 in appids


def test_find_due_reviews_b_tier_fresh_not_due(
    catalog_repo: CatalogRepository,
) -> None:
    """B-tier review window is 14 days — a 10-day-old crawl is not yet due."""
    catalog_repo.bulk_upsert([{"appid": 8400, "name": "Mid"}])
    catalog_repo.set_meta_status(8400, "done")
    _seed_game_row(catalog_repo, 8400, review_count=100)
    _set_review_crawled_at(catalog_repo, 8400, days_ago=10)  # inside 14d window

    appids = [e.appid for e in catalog_repo.find_due_reviews(limit=10, config=_config())]
    assert 8400 not in appids


def test_find_due_reviews_nulls_first(catalog_repo: CatalogRepository) -> None:
    """Eligible games with NULL review_crawled_at get picked up immediately."""
    catalog_repo.bulk_upsert([{"appid": 8500, "name": "Legacy"}])
    catalog_repo.set_meta_status(8500, "done")
    _seed_game_row(catalog_repo, 8500, review_count=200)
    with catalog_repo.conn.cursor() as cur:
        cur.execute("UPDATE app_catalog SET review_crawled_at=NULL WHERE appid = 8500")
    catalog_repo.conn.commit()

    appids = [e.appid for e in catalog_repo.find_due_reviews(limit=10, config=_config())]
    assert 8500 in appids
