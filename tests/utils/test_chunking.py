"""Tests for stratified_chunk_reviews + compute_chunk_hash.

Every test passes `chunk_size`, `reference_time`, and `seed` explicitly —
the chunking module no longer carries defaults for any of them.
"""

from datetime import UTC, datetime

import pytest
from library_layer.utils.chunking import (
    compute_chunk_hash,
    dataset_reference_time,
    stratified_chunk_reviews,
)

# Fixed test anchors — passed explicitly to every chunking call.
_REF_TIME = datetime(2025, 1, 1, tzinfo=UTC)
_SEED = 42
_CHUNK_SIZE = 50


def _review(
    rid: str,
    *,
    voted_up: bool,
    playtime_hours: int = 5,
    votes_helpful: int = 0,
    posted_at: str | None = None,
) -> dict:
    return {
        "steam_review_id": rid,
        "voted_up": voted_up,
        "playtime_hours": playtime_hours,
        "votes_helpful": votes_helpful,
        "posted_at": posted_at,
    }


def test_empty_reviews_returns_empty_list() -> None:
    assert (
        stratified_chunk_reviews([], chunk_size=_CHUNK_SIZE, reference_time=_REF_TIME, seed=_SEED)
        == []
    )


def test_single_chunk_when_under_chunk_size() -> None:
    reviews = [_review(f"r{i}", voted_up=i % 2 == 0) for i in range(10)]
    chunks = stratified_chunk_reviews(
        reviews, chunk_size=_CHUNK_SIZE, reference_time=_REF_TIME, seed=_SEED
    )
    assert len(chunks) == 1
    assert len(chunks[0]) == 10


def test_sentiment_ratio_is_preserved_across_chunks() -> None:
    # 80% positive, 20% negative
    pos = [_review(f"p{i}", voted_up=True) for i in range(80)]
    neg = [_review(f"n{i}", voted_up=False) for i in range(20)]
    chunks = stratified_chunk_reviews(
        pos + neg, chunk_size=_CHUNK_SIZE, reference_time=_REF_TIME, seed=_SEED
    )
    assert len(chunks) == 2
    # First chunk should be ~80% positive (40/50), within +/- 1
    first_pos = sum(1 for r in chunks[0] if r["voted_up"])
    assert 39 <= first_pos <= 41


def test_chunk_hash_is_order_insensitive() -> None:
    reviews_a = [_review("a", voted_up=True), _review("b", voted_up=False)]
    reviews_b = [_review("b", voted_up=False), _review("a", voted_up=True)]
    assert compute_chunk_hash(reviews_a) == compute_chunk_hash(reviews_b)


def test_chunk_hash_changes_with_content() -> None:
    a = [_review("a", voted_up=True)]
    b = [_review("b", voted_up=True)]
    assert compute_chunk_hash(a) != compute_chunk_hash(b)


def test_chunk_hash_changes_when_review_added() -> None:
    base = [_review("a", voted_up=True)]
    extended = [*base, _review("b", voted_up=False)]
    assert compute_chunk_hash(base) != compute_chunk_hash(extended)


def test_chunk_hash_is_16_chars() -> None:
    h = compute_chunk_hash([_review("x", voted_up=True)])
    assert len(h) == 16


def test_compute_chunk_hash_raises_on_missing_steam_review_id() -> None:
    # Every review must carry a steam_review_id — missing ids would cause
    # hash collisions and therefore wrong cache hits.
    with pytest.raises(ValueError, match="steam_review_id"):
        compute_chunk_hash([{"voted_up": True}])


def test_stratified_chunking_rejects_invalid_chunk_size() -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        stratified_chunk_reviews(
            [_review("a", voted_up=True)],
            chunk_size=0,
            reference_time=_REF_TIME,
            seed=_SEED,
        )


def test_stratified_chunking_is_a_partition() -> None:
    # Partition invariant: every input review appears in exactly one chunk.
    reviews = [_review(f"r{i}", voted_up=i % 3 != 0) for i in range(127)]
    chunks = stratified_chunk_reviews(
        reviews, chunk_size=_CHUNK_SIZE, reference_time=_REF_TIME, seed=_SEED
    )
    seen_ids: list[str] = []
    for c in chunks:
        seen_ids.extend(r["steam_review_id"] for r in c)
    assert sorted(seen_ids) == sorted(r["steam_review_id"] for r in reviews)
    assert len(seen_ids) == len(set(seen_ids))  # no duplicates


def test_chunk_hash_is_reproducible_with_fixed_reference_time() -> None:
    reviews = [
        _review(
            f"r{i}",
            voted_up=i % 2 == 0,
            posted_at="2024-01-01T00:00:00+00:00",
            votes_helpful=i,
        )
        for i in range(80)
    ]
    c1 = stratified_chunk_reviews(
        reviews, chunk_size=_CHUNK_SIZE, reference_time=_REF_TIME, seed=_SEED
    )
    c2 = stratified_chunk_reviews(
        reviews, chunk_size=_CHUNK_SIZE, reference_time=_REF_TIME, seed=_SEED
    )
    assert [compute_chunk_hash(c) for c in c1] == [compute_chunk_hash(c) for c in c2]


def test_dataset_reference_time_returns_max_posted_at() -> None:
    reviews = [
        _review("old", voted_up=True, posted_at="2020-01-01T00:00:00+00:00"),
        _review("new", voted_up=False, posted_at="2025-06-15T12:00:00+00:00"),
        _review("mid", voted_up=True, posted_at="2023-03-10T00:00:00+00:00"),
    ]
    assert dataset_reference_time(reviews) == datetime(2025, 6, 15, 12, 0, tzinfo=UTC)


def test_dataset_reference_time_raises_when_no_posted_at() -> None:
    # No silent epoch fallback — caller must handle this explicitly.
    with pytest.raises(ValueError, match="posted_at"):
        dataset_reference_time([_review("a", voted_up=True), _review("b", voted_up=False)])


def test_stratified_chunk_reviews_requires_all_knobs() -> None:
    # No default values on any parameter — every call must be explicit.
    with pytest.raises(TypeError):
        stratified_chunk_reviews([_review("a", voted_up=True)])  # type: ignore[call-arg]
