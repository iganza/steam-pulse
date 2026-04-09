"""Three-phase analyzer tests using an in-memory FakeBackend.

Covers:
- Phase 1 cache hit vs miss (idempotency via chunk_hash).
- run_chunk_phase issues exactly one LLMRequest per non-cached chunk.
- run_merge_phase short-circuits to _promote_single_chunk on 1-chunk input.
- build_chunk_requests respects cached_hashes.
- plan_merge_groups slicing.
"""

from unittest.mock import MagicMock

from library_layer.analyzer import (
    _promote_single_chunk,
    build_chunk_requests,
    run_chunk_phase,
    run_merge_phase,
)
from library_layer.llm.backend import LLMRequest
from library_layer.models.analyzer_models import (
    MergedSummary,
    RichBatchStats,
    RichChunkSummary,
    TopicSignal,
)
from library_layer.utils.chunking import compute_chunk_hash


def _review(rid: str, *, voted_up: bool = True) -> dict:
    return {
        "steam_review_id": rid,
        "voted_up": voted_up,
        "playtime_hours": 10,
        "votes_helpful": 1,
        "posted_at": "2025-01-01T00:00:00+00:00",
        "written_during_early_access": False,
        "received_for_free": False,
        "review_text": f"review body {rid}",
    }


def _empty_summary(label: str = "t") -> RichChunkSummary:
    return RichChunkSummary(
        topics=[
            TopicSignal(
                topic=label,
                category="design_praise",
                sentiment="positive",
                mention_count=1,
                confidence="low",
                summary="ok",
            )
        ],
        competitor_refs=[],
        notable_quotes=[],
        batch_stats=RichBatchStats(positive_count=1, negative_count=0),
    )


class _FakeBackend:
    """Records requests; returns canned responses in order."""

    mode = "realtime"

    def __init__(self, responses: list) -> None:
        self.received: list[LLMRequest] = []
        self._responses = list(responses)

    def run(self, requests: list[LLMRequest]) -> list:
        self.received.extend(requests)
        out = self._responses[: len(requests)]
        self._responses = self._responses[len(requests) :]
        return out


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_build_chunk_requests_skips_cached() -> None:
    reviews = [_review(f"r{i}") for i in range(120)]
    # Pretend the first two chunks are cached by computing their hashes
    # and inserting those into cached_hashes.
    from library_layer.utils.chunking import stratified_chunk_reviews

    chunks = stratified_chunk_reviews(reviews)
    cached = {compute_chunk_hash(chunks[0]), compute_chunk_hash(chunks[1])}

    _chunks_out, pending, meta = build_chunk_requests(
        appid=440, game_name="TF2", reviews=reviews, cached_hashes=cached
    )
    # All non-cached chunks should be pending
    assert len(pending) == len(chunks) - 2
    assert len(meta) == len(pending)
    # Record ids encode the chunk index
    assert pending[0].record_id.startswith("440-chunk-")
    assert pending[0].task == "chunking"


def test_promote_single_chunk_carries_source_id() -> None:
    s = _empty_summary("x")
    promoted = _promote_single_chunk(s, source_chunk_id=77)
    assert isinstance(promoted, MergedSummary)
    assert promoted.merge_level == 0
    assert promoted.chunks_merged == 1
    assert promoted.source_chunk_ids == [77]
    assert len(promoted.topics) == 1


# ---------------------------------------------------------------------------
# Phase orchestration with FakeBackend + mocked repositories
# ---------------------------------------------------------------------------


def test_run_chunk_phase_inserts_and_returns_in_order() -> None:
    reviews = [_review(f"r{i}") for i in range(120)]  # ~3 chunks
    chunk_repo = MagicMock()
    chunk_repo.find_by_appid.return_value = []  # nothing cached

    from library_layer.utils.chunking import stratified_chunk_reviews

    chunks = stratified_chunk_reviews(reviews)
    n = len(chunks)
    backend = _FakeBackend([_empty_summary(f"c{i}") for i in range(n)])

    # Assign sequential row ids as chunks are inserted.
    ids = iter(range(100, 100 + n))
    chunk_repo.insert.side_effect = lambda *a, **k: next(ids)

    summaries, chunk_ids = run_chunk_phase(
        appid=440,
        game_name="TF2",
        reviews=reviews,
        backend=backend,
        chunk_repo=chunk_repo,
    )
    assert len(summaries) == n
    assert len(chunk_ids) == n
    assert chunk_ids == list(range(100, 100 + n))
    # Backend was called once with n pending requests
    assert len(backend.received) == n
    assert all(r.task == "chunking" for r in backend.received)
    # All inserts went to chunk_repo
    assert chunk_repo.insert.call_count == n


def test_run_chunk_phase_uses_cache_and_skips_backend() -> None:
    reviews = [_review(f"r{i}") for i in range(60)]  # 2 chunks
    from library_layer.utils.chunking import stratified_chunk_reviews

    chunks = stratified_chunk_reviews(reviews)

    # Pre-populate the repo mock with cached rows for BOTH chunks.
    cached_rows = [
        {
            "id": 10 + i,
            "chunk_index": i,
            "chunk_hash": compute_chunk_hash(chunk),
            "summary_json": _empty_summary(f"cached{i}").model_dump(mode="json"),
        }
        for i, chunk in enumerate(chunks)
    ]
    chunk_repo = MagicMock()
    chunk_repo.find_by_appid.return_value = cached_rows

    backend = _FakeBackend([])  # zero responses expected

    summaries, chunk_ids = run_chunk_phase(
        appid=440,
        game_name="TF2",
        reviews=reviews,
        backend=backend,
        chunk_repo=chunk_repo,
    )
    assert len(summaries) == len(chunks)
    assert chunk_ids == [10, 11]
    assert backend.received == []  # ZERO backend calls
    assert chunk_repo.insert.call_count == 0


def test_run_merge_phase_short_circuits_single_chunk() -> None:
    backend = _FakeBackend([])  # must never be called
    merge_repo = MagicMock()
    merge_repo.find_latest_by_source_ids.return_value = None

    merged, merged_id = run_merge_phase(
        appid=440,
        game_name="TF2",
        chunk_summaries=[_empty_summary("solo")],
        chunk_ids=[99],
        backend=backend,
        merge_repo=merge_repo,
    )
    assert isinstance(merged, MergedSummary)
    assert merged.merge_level == 0
    assert merged.source_chunk_ids == [99]
    assert merged_id is None  # promotion doesn't persist
    assert backend.received == []
    assert merge_repo.insert.call_count == 0


def test_run_merge_phase_uses_cached_merge_row() -> None:
    """Full-set cache hit on merge_repo skips LLM entirely."""
    backend = _FakeBackend([])
    cached_merged = MergedSummary(
        topics=[], competitor_refs=[], notable_quotes=[],
        total_stats=RichBatchStats(), merge_level=1, chunks_merged=3,
        source_chunk_ids=[1, 2, 3],
    )
    merge_repo = MagicMock()
    merge_repo.find_latest_by_source_ids.return_value = {
        "id": 42,
        "summary_json": cached_merged.model_dump(mode="json"),
    }

    merged, merged_id = run_merge_phase(
        appid=440,
        game_name="TF2",
        chunk_summaries=[_empty_summary(f"c{i}") for i in range(3)],
        chunk_ids=[1, 2, 3],
        backend=backend,
        merge_repo=merge_repo,
    )
    assert isinstance(merged, MergedSummary)
    assert merged.chunks_merged == 3
    assert merged_id == 42
    assert backend.received == []
    assert merge_repo.insert.call_count == 0


def test_run_merge_phase_single_call_with_full_source_ids() -> None:
    """Fresh merge: one LLM call, source_chunk_ids stored from the chunk_ids
    passed in (never trusted from the LLM response)."""
    merged_from_llm = MergedSummary(
        topics=[], competitor_refs=[], notable_quotes=[],
        total_stats=RichBatchStats(),
        merge_level=0,   # LLM may guess wrong — server overrides
        chunks_merged=999,  # LLM may guess wrong — server overrides
        source_chunk_ids=[],  # LLM may omit — server fills
    )
    backend = _FakeBackend([merged_from_llm])
    merge_repo = MagicMock()
    merge_repo.find_latest_by_source_ids.return_value = None
    merge_repo.insert.return_value = 7

    chunk_ids = [10, 20, 30, 40]
    merged, merged_id = run_merge_phase(
        appid=440,
        game_name="TF2",
        chunk_summaries=[_empty_summary(f"c{i}") for i in range(4)],
        chunk_ids=chunk_ids,
        backend=backend,
        merge_repo=merge_repo,
    )
    assert merged_id == 7
    assert merged.merge_level == 1
    assert merged.chunks_merged == 4   # server-computed from len(chunk_ids)
    assert merged.source_chunk_ids == sorted(chunk_ids)
    # Exactly ONE LLM call — no hierarchy.
    assert len(backend.received) == 1
    assert backend.received[0].task == "merging"
    # Persisted row carries the real source ids.
    call_args = merge_repo.insert.call_args
    assert call_args.args[3] == chunk_ids
