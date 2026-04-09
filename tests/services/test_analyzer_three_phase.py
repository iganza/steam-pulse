"""Three-phase analyzer tests using an in-memory FakeBackend.

Every call into the pipeline passes explicit tuning knobs — no function
under test carries defaults. Misusing the API (e.g. calling without
`chunk_size`) must raise TypeError.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
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
from library_layer.utils.chunking import compute_chunk_hash, stratified_chunk_reviews

# Test defaults live HERE, at the test call site — NEVER inside the code
# under test. Pass them explicitly into every function call.
_CHUNK_SIZE = 50
_SHUFFLE_SEED = 42
_CHUNK_MAX_TOKENS = 1024
_MERGE_MAX_TOKENS = 4096
_SYNTHESIS_MAX_TOKENS = 5000
_MAX_CHUNKS_PER_MERGE_CALL = 40
_REF_TIME = datetime(2025, 1, 1, tzinfo=UTC)


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


def _chunks_for(reviews: list[dict]) -> list[list[dict]]:
    return stratified_chunk_reviews(
        reviews,
        chunk_size=_CHUNK_SIZE,
        reference_time=_REF_TIME,
        seed=_SHUFFLE_SEED,
    )


# ---------------------------------------------------------------------------
# Signature enforcement — misusing the API must fail loudly.
# ---------------------------------------------------------------------------


def test_build_chunk_requests_requires_all_knobs() -> None:
    with pytest.raises(TypeError):
        build_chunk_requests(  # type: ignore[call-arg]
            appid=440,
            game_name="TF2",
            reviews=[],
            cached_hashes=set(),
        )


def test_run_chunk_phase_requires_all_knobs() -> None:
    with pytest.raises(TypeError):
        run_chunk_phase(  # type: ignore[call-arg]
            appid=440,
            game_name="TF2",
            reviews=[],
            backend=_FakeBackend([]),
            chunk_repo=MagicMock(),
        )


def test_run_merge_phase_requires_merge_knobs() -> None:
    with pytest.raises(TypeError):
        run_merge_phase(  # type: ignore[call-arg]
            appid=440,
            game_name="TF2",
            chunk_summaries=[_empty_summary("a")],
            chunk_ids=[1],
            backend=_FakeBackend([]),
            merge_repo=MagicMock(),
        )


def test_run_merge_phase_rejects_non_positive_bound() -> None:
    merge_repo = MagicMock()
    merge_repo.find_latest_by_source_ids.return_value = None
    with pytest.raises(ValueError, match="max_chunks_per_merge_call"):
        run_merge_phase(
            appid=440,
            game_name="TF2",
            chunk_summaries=[_empty_summary("a"), _empty_summary("b")],
            chunk_ids=[1, 2],
            backend=_FakeBackend([]),
            merge_repo=merge_repo,
            max_chunks_per_merge_call=0,
            merge_max_tokens=_MERGE_MAX_TOKENS,
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_build_chunk_requests_skips_cached() -> None:
    reviews = [_review(f"r{i}") for i in range(120)]
    chunks = _chunks_for(reviews)
    cached = {compute_chunk_hash(chunks[0]), compute_chunk_hash(chunks[1])}

    _chunks_out, pending, meta = build_chunk_requests(
        appid=440,
        game_name="TF2",
        reviews=reviews,
        cached_hashes=cached,
        chunk_size=_CHUNK_SIZE,
        reference_time=_REF_TIME,
        shuffle_seed=_SHUFFLE_SEED,
        chunk_max_tokens=_CHUNK_MAX_TOKENS,
    )
    assert len(pending) == len(chunks) - 2
    assert len(meta) == len(pending)
    assert pending[0].record_id.startswith("440-chunk-")
    assert pending[0].task == "chunking"
    # max_tokens flows through explicitly — not a hardcoded 1024.
    assert pending[0].max_tokens == _CHUNK_MAX_TOKENS


def test_build_chunk_requests_uses_explicit_max_tokens() -> None:
    reviews = [_review(f"r{i}") for i in range(10)]
    _c, pending, _m = build_chunk_requests(
        appid=440,
        game_name="TF2",
        reviews=reviews,
        cached_hashes=set(),
        chunk_size=_CHUNK_SIZE,
        reference_time=_REF_TIME,
        shuffle_seed=_SHUFFLE_SEED,
        chunk_max_tokens=2048,
    )
    assert pending[0].max_tokens == 2048


def test_promote_single_chunk_carries_source_id() -> None:
    s = _empty_summary("x")
    promoted = _promote_single_chunk(s, source_chunk_id=77)
    assert isinstance(promoted, MergedSummary)
    assert promoted.merge_level == 0
    assert promoted.chunks_merged == 1
    assert promoted.source_chunk_ids == [77]
    assert len(promoted.topics) == 1


# ---------------------------------------------------------------------------
# Phase orchestration
# ---------------------------------------------------------------------------


def _call_run_chunk_phase(
    *, appid: int, reviews: list[dict], backend: _FakeBackend, chunk_repo: MagicMock
) -> tuple[list[RichChunkSummary], list[int]]:
    return run_chunk_phase(
        appid=appid,
        game_name="TF2",
        reviews=reviews,
        backend=backend,
        chunk_repo=chunk_repo,
        chunk_size=_CHUNK_SIZE,
        reference_time=_REF_TIME,
        shuffle_seed=_SHUFFLE_SEED,
        chunk_max_tokens=_CHUNK_MAX_TOKENS,
    )


def test_run_chunk_phase_inserts_and_returns_in_order() -> None:
    reviews = [_review(f"r{i}") for i in range(120)]
    chunk_repo = MagicMock()
    chunk_repo.find_by_appid.return_value = []  # nothing cached

    chunks = _chunks_for(reviews)
    n = len(chunks)
    backend = _FakeBackend([_empty_summary(f"c{i}") for i in range(n)])

    ids = iter(range(100, 100 + n))
    chunk_repo.insert.side_effect = lambda *a, **k: next(ids)

    summaries, chunk_ids = _call_run_chunk_phase(
        appid=440, reviews=reviews, backend=backend, chunk_repo=chunk_repo
    )
    assert len(summaries) == n
    assert len(chunk_ids) == n
    assert chunk_ids == list(range(100, 100 + n))
    assert len(backend.received) == n
    assert all(r.task == "chunking" for r in backend.received)
    assert chunk_repo.insert.call_count == n


def test_run_chunk_phase_uses_cache_and_skips_backend() -> None:
    reviews = [_review(f"r{i}") for i in range(60)]
    chunks = _chunks_for(reviews)

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
    backend = _FakeBackend([])

    summaries, chunk_ids = _call_run_chunk_phase(
        appid=440, reviews=reviews, backend=backend, chunk_repo=chunk_repo
    )
    assert len(summaries) == len(chunks)
    assert chunk_ids == [10, 11]
    assert backend.received == []
    assert chunk_repo.insert.call_count == 0


def _call_run_merge_phase(
    *,
    backend: _FakeBackend,
    merge_repo: MagicMock,
    chunk_summaries: list[RichChunkSummary],
    chunk_ids: list[int],
) -> tuple[MergedSummary, int | None]:
    return run_merge_phase(
        appid=440,
        game_name="TF2",
        chunk_summaries=chunk_summaries,
        chunk_ids=chunk_ids,
        backend=backend,
        merge_repo=merge_repo,
        max_chunks_per_merge_call=_MAX_CHUNKS_PER_MERGE_CALL,
        merge_max_tokens=_MERGE_MAX_TOKENS,
    )


def test_run_merge_phase_short_circuits_single_chunk_but_persists() -> None:
    backend = _FakeBackend([])
    merge_repo = MagicMock()
    merge_repo.find_latest_by_source_ids.return_value = None
    merge_repo.insert.return_value = 55

    merged, merged_id = _call_run_merge_phase(
        backend=backend,
        merge_repo=merge_repo,
        chunk_summaries=[_empty_summary("solo")],
        chunk_ids=[99],
    )
    assert isinstance(merged, MergedSummary)
    assert merged.merge_level == 0
    assert merged.source_chunk_ids == [99]
    assert merged_id == 55
    assert backend.received == []
    assert merge_repo.insert.call_count == 1
    call = merge_repo.insert.call_args
    assert call.args[3] == [99]
    assert call.kwargs["model_id"] == "python-promotion"


def test_run_merge_phase_single_chunk_reuses_promotion_cache() -> None:
    backend = _FakeBackend([])
    existing = MergedSummary(
        topics=[],
        competitor_refs=[],
        notable_quotes=[],
        total_stats=RichBatchStats(),
        merge_level=0,
        chunks_merged=1,
        source_chunk_ids=[99],
    )
    merge_repo = MagicMock()
    merge_repo.find_latest_by_source_ids.return_value = {
        "id": 55,
        "summary_json": existing.model_dump(mode="json"),
    }

    merged, merged_id = _call_run_merge_phase(
        backend=backend,
        merge_repo=merge_repo,
        chunk_summaries=[_empty_summary("solo")],
        chunk_ids=[99],
    )
    assert merged_id == 55
    assert merged.source_chunk_ids == [99]
    assert backend.received == []
    assert merge_repo.insert.call_count == 0


def test_run_merge_phase_uses_cached_merge_row() -> None:
    backend = _FakeBackend([])
    cached_merged = MergedSummary(
        topics=[],
        competitor_refs=[],
        notable_quotes=[],
        total_stats=RichBatchStats(),
        merge_level=1,
        chunks_merged=3,
        source_chunk_ids=[1, 2, 3],
    )
    merge_repo = MagicMock()
    merge_repo.find_latest_by_source_ids.return_value = {
        "id": 42,
        "summary_json": cached_merged.model_dump(mode="json"),
    }

    merged, merged_id = _call_run_merge_phase(
        backend=backend,
        merge_repo=merge_repo,
        chunk_summaries=[_empty_summary(f"c{i}") for i in range(3)],
        chunk_ids=[1, 2, 3],
    )
    assert isinstance(merged, MergedSummary)
    assert merged.chunks_merged == 3
    assert merged_id == 42
    assert backend.received == []
    assert merge_repo.insert.call_count == 0


def _fake_merge_repo_for(insert_ids: list[int]) -> MagicMock:
    repo = MagicMock()
    repo.find_latest_by_source_ids.return_value = None
    state: dict = {"last": None, "by_id": {}, "ids": iter(insert_ids)}

    def _insert(
        appid: int,
        level: int,
        summary: MergedSummary,
        source_ids: list[int],
        chunks_merged: int,
        **_: object,
    ) -> int:
        row_id = next(state["ids"])
        row = {"id": row_id, "summary_json": summary.model_dump(mode="json")}
        state["by_id"][row_id] = row
        state["last"] = row
        return row_id

    repo.insert.side_effect = _insert
    repo.find_latest_by_appid.side_effect = lambda _appid: state["last"]
    return repo


def test_run_merge_phase_single_level_fits_in_one_call() -> None:
    merged_from_llm = MergedSummary(
        topics=[],
        competitor_refs=[],
        notable_quotes=[],
        total_stats=RichBatchStats(),
        merge_level=0,
        chunks_merged=999,
        source_chunk_ids=[],
    )
    backend = _FakeBackend([merged_from_llm])
    merge_repo = _fake_merge_repo_for([7])

    chunk_ids = [10, 20, 30, 40]
    merged, merged_id = _call_run_merge_phase(
        backend=backend,
        merge_repo=merge_repo,
        chunk_summaries=[_empty_summary(f"c{i}") for i in range(4)],
        chunk_ids=chunk_ids,
    )
    assert merged_id == 7
    assert merged.merge_level == 1
    assert merged.chunks_merged == 4
    assert merged.source_chunk_ids == sorted(chunk_ids)
    assert len(backend.received) == 1
    assert backend.received[0].task == "merging"
    # merge_max_tokens flows through explicitly.
    assert backend.received[0].max_tokens == _MERGE_MAX_TOKENS


def test_run_merge_phase_recurses_when_chunk_count_exceeds_per_call_bound() -> None:
    """Large chunk count: hierarchical merge threads source_chunk_ids
    through every level. The bound is passed in EXPLICITLY — not read
    from a module-level constant."""
    # Force hierarchy with a tight bound rather than relying on an
    # imported constant. This makes the test robust against config changes.
    tight_bound = 4
    n = tight_bound + 3  # forces 2 groups at L1, 1 at L2
    chunk_ids = list(range(1000, 1000 + n))

    llm_responses = [
        MergedSummary(
            topics=[],
            competitor_refs=[],
            notable_quotes=[],
            total_stats=RichBatchStats(),
            merge_level=0,
            chunks_merged=0,
            source_chunk_ids=[],
        )
        for _ in range(3)
    ]
    backend = _FakeBackend(llm_responses)
    merge_repo = _fake_merge_repo_for([101, 102, 103])

    root, root_id = run_merge_phase(
        appid=440,
        game_name="TF2",
        chunk_summaries=[_empty_summary(f"c{i}") for i in range(n)],
        chunk_ids=chunk_ids,
        backend=backend,
        merge_repo=merge_repo,
        max_chunks_per_merge_call=tight_bound,
        merge_max_tokens=_MERGE_MAX_TOKENS,
    )
    assert len(backend.received) == 3
    assert root.source_chunk_ids == sorted(chunk_ids)
    assert root.chunks_merged == n
    assert root.merge_level == 2
    assert root_id == 103
    for call in merge_repo.insert.call_args_list:
        src_ids = call.args[3]
        assert len(src_ids) > 0
        assert all(isinstance(i, int) for i in src_ids)
