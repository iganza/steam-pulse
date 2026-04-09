"""DB-backed tests for MergedSummaryRepository.

Covers the Phase 2 cache-keyed persistence contract. A regression in
`find_latest_by_source_ids` ordering or prompt_version scoping would
silently break merge cache reuse and force every analysis to repay for
a fresh merge LLM call.
"""

import time

from library_layer.models.analyzer_models import MergedSummary, RichBatchStats
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.merged_summary_repo import MergedSummaryRepository


def _seed_game(game_repo: GameRepository, appid: int = 440) -> None:
    game_repo.upsert(
        {
            "appid": appid,
            "name": f"Game {appid}",
            "slug": f"game-{appid}",
            "type": "game",
            "developer": "Dev",
            "developer_slug": "dev",
            "publisher": "Pub",
            "publisher_slug": "pub",
            "developers": "[]",
            "publishers": "[]",
            "website": None,
            "release_date": None,
            "coming_soon": False,
            "price_usd": None,
            "is_free": True,
            "short_desc": None,
            "detailed_description": None,
            "about_the_game": None,
            "review_count": 100,
            "review_count_english": 100,
            "total_positive": 90,
            "total_negative": 10,
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
            "data_source": "steam_direct",
        }
    )


def _merged(label: str) -> MergedSummary:
    return MergedSummary(
        topics=[],
        competitor_refs=[],
        notable_quotes=[],
        total_stats=RichBatchStats(),
        merge_level=1,
        chunks_merged=3,
        source_chunk_ids=[10, 20, 30],
    )


def test_insert_and_find_latest_by_appid(
    game_repo: GameRepository, merged_summary_repo: MergedSummaryRepository
) -> None:
    _seed_game(game_repo)
    row_id = merged_summary_repo.insert(
        appid=440,
        merge_level=1,
        summary=_merged("first"),
        source_chunk_ids=[10, 20, 30],
        chunks_merged=3,
        model_id="test",
        prompt_version="merge-v1.0",
    )
    assert row_id > 0
    latest = merged_summary_repo.find_latest_by_appid(440)
    assert latest is not None
    assert latest["id"] == row_id


def test_find_latest_by_source_ids_is_order_insensitive(
    game_repo: GameRepository, merged_summary_repo: MergedSummaryRepository
) -> None:
    """The merge cache key is the SET of leaf chunk ids — callers may
    pass them in any order. Repo must normalize before lookup so
    [30, 10, 20] and [10, 20, 30] find the same row."""
    _seed_game(game_repo)
    row_id = merged_summary_repo.insert(
        appid=440,
        merge_level=1,
        summary=_merged("m1"),
        source_chunk_ids=[10, 20, 30],
        chunks_merged=3,
        model_id="test",
        prompt_version="merge-v1.0",
    )
    # Caller passes the same ids in a different order.
    found = merged_summary_repo.find_latest_by_source_ids(440, [30, 10, 20], "merge-v1.0")
    assert found is not None
    assert found["id"] == row_id


def test_find_latest_by_source_ids_scoped_by_prompt_version(
    game_repo: GameRepository, merged_summary_repo: MergedSummaryRepository
) -> None:
    """Bumping MERGE_PROMPT_VERSION must invalidate the cache — a row
    stored under version X is invisible to a lookup for version Y."""
    _seed_game(game_repo)
    merged_summary_repo.insert(
        appid=440,
        merge_level=1,
        summary=_merged("v1"),
        source_chunk_ids=[10, 20, 30],
        chunks_merged=3,
        model_id="test",
        prompt_version="merge-v1.0",
    )
    assert (
        merged_summary_repo.find_latest_by_source_ids(440, [10, 20, 30], "merge-v1.0") is not None
    )
    assert merged_summary_repo.find_latest_by_source_ids(440, [10, 20, 30], "merge-v2.0") is None


def test_find_latest_by_source_ids_requires_exact_set(
    game_repo: GameRepository, merged_summary_repo: MergedSummaryRepository
) -> None:
    """Subset and superset lookups must NOT match — the cache key is an
    exact match on the leaf chunk ids."""
    _seed_game(game_repo)
    merged_summary_repo.insert(
        appid=440,
        merge_level=1,
        summary=_merged("m1"),
        source_chunk_ids=[10, 20, 30],
        chunks_merged=3,
        model_id="test",
        prompt_version="merge-v1.0",
    )
    assert merged_summary_repo.find_latest_by_source_ids(440, [10, 20], "merge-v1.0") is None
    assert (
        merged_summary_repo.find_latest_by_source_ids(440, [10, 20, 30, 40], "merge-v1.0") is None
    )


def test_find_latest_by_source_ids_picks_newest_row(
    game_repo: GameRepository, merged_summary_repo: MergedSummaryRepository
) -> None:
    """When two rows share the same (appid, source_chunk_ids,
    prompt_version), the repo returns the most recent one (ORDER BY
    created_at DESC LIMIT 1)."""
    _seed_game(game_repo)
    first_id = merged_summary_repo.insert(
        appid=440,
        merge_level=1,
        summary=_merged("older"),
        source_chunk_ids=[10, 20, 30],
        chunks_merged=3,
        model_id="test",
        prompt_version="merge-v1.0",
    )
    # created_at has NOW() default — sleep a hair to force a distinct timestamp.
    time.sleep(0.05)
    newer_id = merged_summary_repo.insert(
        appid=440,
        merge_level=1,
        summary=_merged("newer"),
        source_chunk_ids=[10, 20, 30],
        chunks_merged=3,
        model_id="test",
        prompt_version="merge-v1.0",
    )
    assert newer_id != first_id
    latest = merged_summary_repo.find_latest_by_source_ids(440, [10, 20, 30], "merge-v1.0")
    assert latest is not None
    assert latest["id"] == newer_id


def test_find_latest_by_appid_prefers_higher_merge_level(
    game_repo: GameRepository, merged_summary_repo: MergedSummaryRepository
) -> None:
    """find_latest_by_appid orders by (merge_level DESC, created_at DESC).
    When the analyzer persists both a level-1 (group) and a level-2
    (root) merge for the same appid, the ROOT must be returned."""
    _seed_game(game_repo)
    level1_id = merged_summary_repo.insert(
        appid=440,
        merge_level=1,
        summary=_merged("l1"),
        source_chunk_ids=[10, 20],
        chunks_merged=2,
        model_id="test",
        prompt_version="merge-v1.0",
    )
    time.sleep(0.05)
    level2_id = merged_summary_repo.insert(
        appid=440,
        merge_level=2,
        summary=_merged("l2"),
        source_chunk_ids=[10, 20, 30, 40],
        chunks_merged=4,
        model_id="test",
        prompt_version="merge-v1.0",
    )
    latest = merged_summary_repo.find_latest_by_appid(440)
    assert latest is not None
    # Level 2 wins regardless of timestamp order.
    assert latest["id"] == level2_id
    assert latest["merge_level"] == 2
    # Level 1 row still exists.
    assert level1_id != level2_id


def test_delete_by_appid_drops_all_rows(
    game_repo: GameRepository, merged_summary_repo: MergedSummaryRepository
) -> None:
    _seed_game(game_repo)
    merged_summary_repo.insert(
        appid=440,
        merge_level=1,
        summary=_merged("a"),
        source_chunk_ids=[1, 2],
        chunks_merged=2,
        model_id="test",
        prompt_version="merge-v1.0",
    )
    merged_summary_repo.insert(
        appid=440,
        merge_level=2,
        summary=_merged("b"),
        source_chunk_ids=[1, 2, 3],
        chunks_merged=3,
        model_id="test",
        prompt_version="merge-v1.0",
    )
    deleted = merged_summary_repo.delete_by_appid(440)
    assert deleted == 2
    assert merged_summary_repo.find_latest_by_appid(440) is None
