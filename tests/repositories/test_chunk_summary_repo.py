"""DB-backed tests for ChunkSummaryRepository.

Covers the Phase 1 cache/persistence contract the three-phase analyzer
relies on. A regression here would silently invalidate chunk caching and
force every re-analysis to pay for fresh LLM calls.
"""

from library_layer.models.analyzer_models import (
    RichBatchStats,
    RichChunkSummary,
    TopicSignal,
)
from library_layer.repositories.chunk_summary_repo import ChunkSummaryRepository
from library_layer.repositories.game_repo import GameRepository


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
            "release_date_raw": None,
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


def _summary(label: str) -> RichChunkSummary:
    return RichChunkSummary(
        topics=[
            TopicSignal(
                topic=label,
                category="design_praise",
                sentiment="positive",
                mention_count=1,
                confidence="low",
                summary=f"summary for {label}",
            )
        ],
        competitor_refs=[],
        notable_quotes=[],
        batch_stats=RichBatchStats(positive_count=1, negative_count=0),
    )


def test_insert_and_find_by_hash(
    game_repo: GameRepository, chunk_summary_repo: ChunkSummaryRepository
) -> None:
    _seed_game(game_repo)
    row_id = chunk_summary_repo.insert(
        appid=440,
        chunk_index=0,
        chunk_hash="abc123",
        review_count=50,
        summary=_summary("first"),
        model_id="test-model",
        prompt_version="chunk-v2.0",
    )
    assert row_id > 0

    found = chunk_summary_repo.find_by_hash(440, "abc123", "chunk-v2.0")
    assert found is not None
    assert found["id"] == row_id
    assert found["chunk_hash"] == "abc123"
    assert found["review_count"] == 50
    assert found["summary_json"]["topics"][0]["topic"] == "first"


def test_find_by_hash_is_scoped_by_prompt_version(
    game_repo: GameRepository, chunk_summary_repo: ChunkSummaryRepository
) -> None:
    """A row stored under prompt_version X must NOT be returned when the
    caller asks for version Y — this is the invalidation mechanism for
    prompt changes."""
    _seed_game(game_repo)
    chunk_summary_repo.insert(
        appid=440,
        chunk_index=0,
        chunk_hash="samehash",
        review_count=50,
        summary=_summary("v1"),
        model_id="test",
        prompt_version="chunk-v1.0",
    )
    assert chunk_summary_repo.find_by_hash(440, "samehash", "chunk-v1.0") is not None
    assert chunk_summary_repo.find_by_hash(440, "samehash", "chunk-v2.0") is None


def test_insert_is_idempotent_on_same_hash(
    game_repo: GameRepository, chunk_summary_repo: ChunkSummaryRepository
) -> None:
    """ON CONFLICT(appid, chunk_hash, prompt_version) must return the
    original row's id, NOT insert a duplicate. Callers rely on this to
    get a canonical id back from every insert() call."""
    _seed_game(game_repo)
    first_id = chunk_summary_repo.insert(
        appid=440,
        chunk_index=0,
        chunk_hash="abc123",
        review_count=50,
        summary=_summary("first"),
        model_id="test",
        prompt_version="chunk-v2.0",
    )
    second_id = chunk_summary_repo.insert(
        appid=440,
        chunk_index=0,
        chunk_hash="abc123",
        review_count=50,
        summary=_summary("replacement"),
        model_id="test",
        prompt_version="chunk-v2.0",
    )
    assert second_id == first_id
    # Exactly one row for this (appid, hash, version).
    rows = chunk_summary_repo.find_by_appid(440, "chunk-v2.0")
    assert len(rows) == 1


def test_find_by_appid_orders_by_chunk_index_then_id(
    game_repo: GameRepository, chunk_summary_repo: ChunkSummaryRepository
) -> None:
    """find_by_appid orders by (chunk_index ASC, id ASC). The id tiebreak
    matters when two rows share a chunk_index (e.g. a re-analysis run
    inserted new rows alongside stale ones at the same index) so the
    caller gets a deterministic ordering."""
    _seed_game(game_repo)
    # Insert in non-monotonic order to prove the SQL sort, not insertion
    # order, controls the result.
    chunk_summary_repo.insert(
        appid=440,
        chunk_index=2,
        chunk_hash="h2",
        review_count=50,
        summary=_summary("c2"),
        model_id="test",
        prompt_version="chunk-v2.0",
    )
    chunk_summary_repo.insert(
        appid=440,
        chunk_index=0,
        chunk_hash="h0",
        review_count=50,
        summary=_summary("c0"),
        model_id="test",
        prompt_version="chunk-v2.0",
    )
    chunk_summary_repo.insert(
        appid=440,
        chunk_index=1,
        chunk_hash="h1",
        review_count=50,
        summary=_summary("c1"),
        model_id="test",
        prompt_version="chunk-v2.0",
    )

    rows = chunk_summary_repo.find_by_appid(440, "chunk-v2.0")
    assert [r["chunk_index"] for r in rows] == [0, 1, 2]
    assert [r["chunk_hash"] for r in rows] == ["h0", "h1", "h2"]


def test_find_by_appid_scoped_by_prompt_version(
    game_repo: GameRepository, chunk_summary_repo: ChunkSummaryRepository
) -> None:
    _seed_game(game_repo)
    chunk_summary_repo.insert(
        appid=440,
        chunk_index=0,
        chunk_hash="h_old",
        review_count=50,
        summary=_summary("old"),
        model_id="test",
        prompt_version="chunk-v1.0",
    )
    chunk_summary_repo.insert(
        appid=440,
        chunk_index=0,
        chunk_hash="h_new",
        review_count=50,
        summary=_summary("new"),
        model_id="test",
        prompt_version="chunk-v2.0",
    )
    v1_rows = chunk_summary_repo.find_by_appid(440, "chunk-v1.0")
    v2_rows = chunk_summary_repo.find_by_appid(440, "chunk-v2.0")
    assert [r["chunk_hash"] for r in v1_rows] == ["h_old"]
    assert [r["chunk_hash"] for r in v2_rows] == ["h_new"]


def test_delete_by_appid_drops_all_rows(
    game_repo: GameRepository, chunk_summary_repo: ChunkSummaryRepository
) -> None:
    _seed_game(game_repo)
    chunk_summary_repo.insert(
        appid=440,
        chunk_index=0,
        chunk_hash="h0",
        review_count=50,
        summary=_summary("a"),
        model_id="test",
        prompt_version="chunk-v2.0",
    )
    chunk_summary_repo.insert(
        appid=440,
        chunk_index=1,
        chunk_hash="h1",
        review_count=50,
        summary=_summary("b"),
        model_id="test",
        prompt_version="chunk-v2.0",
    )
    deleted = chunk_summary_repo.delete_by_appid(440)
    assert deleted == 2
    assert chunk_summary_repo.find_by_appid(440, "chunk-v2.0") == []
