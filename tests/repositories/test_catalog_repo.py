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
    catalog_repo.set_meta_status(500, "done", review_count=1500, review_status="pending")
    entry = catalog_repo.find_by_appid(500)
    assert entry is not None
    assert entry.meta_status == "done"
    assert entry.review_count == 1500
    assert entry.review_status == "pending"


def test_set_review_status(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert([{"appid": 700, "name": "Review Game"}])
    catalog_repo.set_review_status(700, "done")
    entry = catalog_repo.find_by_appid(700)
    assert entry is not None
    assert entry.review_status == "done"


def test_status_summary(catalog_repo: CatalogRepository) -> None:
    catalog_repo.bulk_upsert(_entries(5))
    catalog_repo.set_meta_status(1000, "done", review_status="done")
    catalog_repo.set_meta_status(1001, "failed")
    summary = catalog_repo.status_summary()
    assert summary["meta"].get("done", 0) >= 1
    assert summary["meta"].get("failed", 0) >= 1
    assert summary["meta"].get("pending", 0) >= 3
