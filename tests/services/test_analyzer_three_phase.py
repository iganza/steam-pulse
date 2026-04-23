"""Three-phase analyzer tests using an in-memory FakeBackend.

Every call into the pipeline passes explicit tuning knobs — no function
under test carries defaults. Misusing the API (e.g. calling without
`chunk_size`) must raise TypeError.
"""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from library_layer.analyzer import (
    AnalyzerSettings,
    _build_synthesis_user_message,
    build_chunk_requests,
    parse_chunk_record_id,
    promote_single_chunk,
    run_chunk_phase,
    run_merge_phase,
)
from library_layer.config import SteamPulseConfig
from library_layer.llm.backend import LLMRequest, LLMUsage
from library_layer.models.analyzer_models import (
    MergedSummary,
    RichBatchStats,
    RichChunkSummary,
    TopicSignal,
)
from library_layer.models.metadata import GameMetadataContext
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


def _fake_usage() -> LLMUsage:
    return LLMUsage(input_tokens=100, output_tokens=50, latency_ms=10)


class _FakeBackend:
    """Records requests; returns canned responses in order."""

    mode = "realtime"

    def __init__(self, responses: list) -> None:
        self.received: list[LLMRequest] = []
        self._responses = list(responses)

    def run(self, requests: list[LLMRequest], *, on_result: object = None) -> list:
        self.received.extend(requests)
        out = self._responses[: len(requests)]
        self._responses = self._responses[len(requests) :]
        if on_result is not None:
            for i, r in enumerate(out):
                on_result(i, r, _fake_usage())
        return out


def _chunks_for(reviews: list[dict]) -> list[list[dict]]:
    return stratified_chunk_reviews(
        reviews,
        chunk_size=_CHUNK_SIZE,
        reference_time=_REF_TIME,
        seed=_SHUFFLE_SEED,
    )


# ---------------------------------------------------------------------------
# Config wiring — catches cold-start crashes like a typo in from_config().
# ---------------------------------------------------------------------------


def test_analyzer_settings_from_config_reads_every_field() -> None:
    """Regression test: this exercises the exact code path that runs at
    Lambda cold-start. A typo in an attribute name (e.g. lowercase
    `config.ANALYSIS_max_chunks_per_merge_call`) would crash here."""
    config = SteamPulseConfig()
    settings = AnalyzerSettings.from_config(config)
    assert settings.chunk_size == config.ANALYSIS_CHUNK_SIZE
    assert settings.max_chunks_per_merge_call == config.ANALYSIS_MAX_CHUNKS_PER_MERGE_CALL
    assert settings.chunk_max_tokens == config.ANALYSIS_CHUNK_MAX_TOKENS
    assert settings.merge_max_tokens == config.ANALYSIS_MERGE_MAX_TOKENS
    assert settings.synthesis_max_tokens == config.ANALYSIS_SYNTHESIS_MAX_TOKENS
    assert settings.shuffle_seed == config.ANALYSIS_CHUNK_SHUFFLE_SEED


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
            chunk_summaries=[_empty_summary(f"c{i}") for i in range(5)],
            chunk_ids=[1, 2, 3, 4, 5],
            backend=_FakeBackend([]),
            merge_repo=merge_repo,
            max_chunks_per_merge_call=0,
            merge_max_tokens=_MERGE_MAX_TOKENS,
            merge_temperature=None,
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
        chunk_temperature=None,
    )
    assert len(pending) == len(chunks) - 2
    assert len(meta) == len(pending)
    assert pending[0].record_id.startswith("440-chunk-")
    assert pending[0].task == "chunking"
    # max_tokens flows through explicitly — not a hardcoded 1024.
    assert pending[0].max_tokens == _CHUNK_MAX_TOKENS


def test_build_chunk_requests_encodes_hash_in_record_id() -> None:
    """prepare→collect desync guard: the batch path's collect Lambda recovers
    chunk_index / chunk_size / chunk_hash from record_id alone, without
    re-chunking live DB reviews (which may have shifted during a multi-hour
    Bedrock Batch job). Every request's record_id must round-trip through
    parse_chunk_record_id to the same metadata that would be persisted in
    chunk_summaries."""
    reviews = [_review(f"r{i}") for i in range(60)]
    _chunks_out, pending, meta = build_chunk_requests(
        appid=440,
        game_name="TF2",
        reviews=reviews,
        cached_hashes=set(),
        chunk_size=_CHUNK_SIZE,
        reference_time=_REF_TIME,
        shuffle_seed=_SHUFFLE_SEED,
        chunk_max_tokens=_CHUNK_MAX_TOKENS,
        chunk_temperature=None,
    )
    assert len(pending) == len(meta)
    for request, (expected_index, expected_hash, expected_size) in zip(pending, meta, strict=True):
        parsed = parse_chunk_record_id(request.record_id)
        assert parsed is not None, f"parse failed for {request.record_id}"
        appid, chunk_index, chunk_size, chunk_hash = parsed
        assert appid == 440
        assert chunk_index == expected_index
        assert chunk_size == expected_size
        assert chunk_hash == expected_hash


def test_parse_chunk_record_id_rejects_garbage() -> None:
    # Malformed ids must log and return None, never raise.
    assert parse_chunk_record_id("not-a-record-id") is None
    assert parse_chunk_record_id("440-chunk-abc-def-ghi") is None  # non-int fields
    assert parse_chunk_record_id("") is None


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
        chunk_temperature=None,
    )
    assert pending[0].max_tokens == 2048


def test_promote_single_chunk_carries_source_id() -> None:
    s = _empty_summary("x")
    promoted = promote_single_chunk(s, source_chunk_id=77)
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
        chunk_temperature=None,
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


def test_run_chunk_phase_persists_incrementally_on_partial_failure() -> None:
    """If the backend raises partway through the fan-out, all chunks that
    succeeded BEFORE the failure must already be persisted — so a re-run
    picks them up as cache hits instead of paying for them again."""
    reviews = [_review(f"r{i}") for i in range(120)]
    chunk_repo = MagicMock()
    chunk_repo.find_by_appid.return_value = []
    n = len(_chunks_for(reviews))
    assert n >= 3  # the test only makes sense with ≥3 chunks

    class _FailingBackend:
        mode = "realtime"

        def __init__(self) -> None:
            self.received: list[LLMRequest] = []

        def run(self, requests: list[LLMRequest], *, on_result: object = None) -> list:
            self.received.extend(requests)
            # Simulate the first two succeeding, then chunk 2 raising.
            on_result(0, _empty_summary("c0"), _fake_usage())
            on_result(1, _empty_summary("c1"), _fake_usage())
            raise RuntimeError("simulated llm failure on chunk 2")

    ids = iter(range(500, 500 + n))
    chunk_repo.insert.side_effect = lambda *a, **k: next(ids)
    backend = _FailingBackend()

    with pytest.raises(RuntimeError, match="simulated llm failure"):
        _call_run_chunk_phase(appid=440, reviews=reviews, backend=backend, chunk_repo=chunk_repo)

    # Chunks 0 and 1 persisted BEFORE the exception — the whole point of
    # the streaming callback is that their work isn't thrown away.
    assert chunk_repo.insert.call_count == 2


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
        merge_temperature=None,
    )


def test_run_merge_phase_rejects_below_minimum_chunks() -> None:
    """Floor: fewer than MIN_CHUNKS_FOR_MERGE chunks raises cleanly,
    before any LLM call or DB write."""
    from library_layer.analyzer import MIN_CHUNKS_FOR_MERGE

    backend = _FakeBackend([])
    merge_repo = MagicMock()
    short_count = MIN_CHUNKS_FOR_MERGE - 1
    with pytest.raises(ValueError, match=f"at least {MIN_CHUNKS_FOR_MERGE} chunks"):
        run_merge_phase(
            appid=440,
            game_name="TF2",
            chunk_summaries=[_empty_summary(f"c{i}") for i in range(short_count)],
            chunk_ids=list(range(short_count)),
            backend=backend,
            merge_repo=merge_repo,
            max_chunks_per_merge_call=_MAX_CHUNKS_PER_MERGE_CALL,
            merge_max_tokens=_MERGE_MAX_TOKENS,
            merge_temperature=None,
        )
    assert backend.received == []
    merge_repo.insert.assert_not_called()


def test_run_merge_phase_uses_cached_merge_row() -> None:
    backend = _FakeBackend([])
    cached_merged = MergedSummary(
        topics=[],
        competitor_refs=[],
        notable_quotes=[],
        total_stats=RichBatchStats(),
        merge_level=1,
        chunks_merged=5,
        source_chunk_ids=[1, 2, 3, 4, 5],
    )
    merge_repo = MagicMock()
    merge_repo.find_latest_by_source_ids.return_value = {
        "id": 42,
        "summary_json": cached_merged.model_dump(mode="json"),
    }

    merged, merged_id = _call_run_merge_phase(
        backend=backend,
        merge_repo=merge_repo,
        chunk_summaries=[_empty_summary(f"c{i}") for i in range(5)],
        chunk_ids=[1, 2, 3, 4, 5],
    )
    assert isinstance(merged, MergedSummary)
    assert merged.chunks_merged == 5
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
    repo.find_by_id.side_effect = lambda row_id: state["by_id"].get(row_id)
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

    chunk_ids = [10, 20, 30, 40, 50]
    merged, merged_id = _call_run_merge_phase(
        backend=backend,
        merge_repo=merge_repo,
        chunk_summaries=[_empty_summary(f"c{i}") for i in range(5)],
        chunk_ids=chunk_ids,
    )
    assert merged_id == 7
    assert merged.merge_level == 1
    assert merged.chunks_merged == 5
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
        merge_temperature=None,
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


def test_run_merge_phase_root_lookup_is_race_free() -> None:
    """E1 regression: concurrent re-analysis for the same appid can
    insert a merge row between our last insert and the root re-read.
    `run_merge_phase` must look up the row it inserted by primary key
    — NOT via `find_latest_by_appid`, which would return the racing
    row and flip the post-loop check into a spurious RuntimeError.
    """
    merged_from_llm = MergedSummary(
        topics=[],
        competitor_refs=[],
        notable_quotes=[],
        total_stats=RichBatchStats(),
        merge_level=0,
        chunks_merged=0,
        source_chunk_ids=[],
    )
    backend = _FakeBackend([merged_from_llm])
    merge_repo = _fake_merge_repo_for([7])

    # Simulate a concurrent re-analysis landing a row with a HIGHER id
    # after our insert but before the verification read. If the code
    # used find_latest_by_appid this would win the ORDER BY and the
    # assertion would blow up.
    original_insert = merge_repo.insert.side_effect

    def _insert_then_race(*args: object, **kwargs: object) -> int:
        row_id = original_insert(*args, **kwargs)
        # Racing writer stamps a newer row with a different id.
        return row_id

    merge_repo.insert.side_effect = _insert_then_race
    # find_by_id must resolve OUR id, not the racer's. The racer only
    # exists as a ghost entry that would've been returned by a
    # find_latest_by_appid path — asserting find_by_id is called with
    # our id is the contract.
    merged, merged_id = _call_run_merge_phase(
        backend=backend,
        merge_repo=merge_repo,
        chunk_summaries=[_empty_summary(f"c{i}") for i in range(5)],
        chunk_ids=[10, 20, 30, 40, 50],
    )
    assert merged_id == 7
    assert isinstance(merged, MergedSummary)
    merge_repo.find_by_id.assert_called_with(7)
    merge_repo.find_latest_by_appid.assert_not_called()


# ---------------------------------------------------------------------------
# Synthesis prompt metadata regression harness
# ---------------------------------------------------------------------------


def _synth_kwargs(**over: object) -> dict:
    base: dict = {
        "aggregated_signals": {"topics": [], "competitor_refs": [], "notable_quotes": []},
        "game_name": "Team Fortress 2",
        "total_reviews": 100,
        "hidden_gem_score": 0.42,
        "sentiment_trend": "stable",
        "sentiment_trend_note": "flat",
        "steam_positive_pct": 85,
        "steam_review_score_desc": "Very Positive",
        "temporal": None,
        "metadata": None,
    }
    base.update(over)
    return base


def test_build_synthesis_user_message_renders_metadata_when_present() -> None:
    """Regression harness for the silent `metadata=None` bug: when a
    populated GameMetadataContext is passed, the prompt MUST render
    the store_description block, the store_page_alignment section,
    and the price/genre/tag context lines."""
    metadata = GameMetadataContext(
        short_desc="A hat-based war crime simulator",
        about_the_game="TF2 is a class-based shooter about competitive hat acquisition.",
        price_usd=None,
        is_free=True,
        tags=["FPS", "Multiplayer"],
        genres=["Action"],
        platforms=["Windows", "Mac"],
        deck_status="Verified",
        achievements_total=520,
        metacritic_score=92,
    )
    prompt = _build_synthesis_user_message(**_synth_kwargs(metadata=metadata))
    assert "<store_description>" in prompt
    assert "store_page_alignment" in prompt
    assert "Free" in prompt  # is_free rendering
    assert "Action" in prompt  # genre
    assert "FPS" in prompt  # tag
    assert "Verified" in prompt  # deck_status


def test_build_synthesis_user_message_omits_metadata_when_none() -> None:
    """Negative side of the regression: with metadata=None the store
    description block and the store_page_alignment section MUST be
    absent. This documents the prompt's conditional branches."""
    prompt = _build_synthesis_user_message(**_synth_kwargs(metadata=None))
    assert "<store_description>" not in prompt
    assert "store_page_alignment" not in prompt


# ---------------------------------------------------------------------------
# Sonnet json-in-string coercion
# ---------------------------------------------------------------------------


def test_rich_chunk_summary_coerces_stringified_topics() -> None:
    """Sonnet occasionally serializes nested arrays as JSON strings inside
    tool_use blocks. The mode='before' validator should parse them so we
    don't fail validation on an otherwise-valid response."""
    topics_json = json.dumps(
        [
            {
                "topic": "parry system",
                "category": "gameplay_friction",
                "sentiment": "negative",
                "mention_count": 3,
                "confidence": "medium",
                "summary": "players find parry timing unforgiving",
                "quotes": [],
                "avg_playtime_hours": 0.0,
                "avg_helpful_votes": 0.0,
            }
        ]
    )
    payload = {
        "topics": topics_json,  # intentionally a string
        "competitor_refs": [],
        "notable_quotes": [],
        "batch_stats": {"positive_count": 1, "negative_count": 0},
    }
    summary = RichChunkSummary.model_validate(payload)
    assert len(summary.topics) == 1
    assert summary.topics[0].topic == "parry system"
