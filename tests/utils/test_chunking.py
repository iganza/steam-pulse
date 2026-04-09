"""Tests for stratified_chunk_reviews + compute_chunk_hash."""

import pytest
from library_layer.utils.chunking import (
    CHUNK_SIZE,
    compute_chunk_hash,
    stratified_chunk_reviews,
)


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
    assert stratified_chunk_reviews([]) == []


def test_single_chunk_when_under_chunk_size() -> None:
    reviews = [_review(f"r{i}", voted_up=i % 2 == 0) for i in range(10)]
    chunks = stratified_chunk_reviews(reviews, chunk_size=50)
    assert len(chunks) == 1
    assert len(chunks[0]) == 10


def test_sentiment_ratio_is_preserved_across_chunks() -> None:
    # 80% positive, 20% negative
    pos = [_review(f"p{i}", voted_up=True) for i in range(80)]
    neg = [_review(f"n{i}", voted_up=False) for i in range(20)]
    chunks = stratified_chunk_reviews(pos + neg, chunk_size=50)
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


def test_chunk_size_constant_is_50() -> None:
    assert CHUNK_SIZE == 50


def test_compute_chunk_hash_raises_on_missing_steam_review_id() -> None:
    # Every review must carry a steam_review_id — missing ids would cause
    # hash collisions and therefore wrong cache hits.
    with pytest.raises(ValueError, match="steam_review_id"):
        compute_chunk_hash([{"voted_up": True}])


def test_stratified_chunking_is_a_partition() -> None:
    # Partition invariant: every input review appears in exactly one chunk.
    reviews = [_review(f"r{i}", voted_up=i % 3 != 0) for i in range(127)]
    chunks = stratified_chunk_reviews(reviews, chunk_size=50)
    seen_ids: list[str] = []
    for c in chunks:
        seen_ids.extend(r["steam_review_id"] for r in c)
    assert sorted(seen_ids) == sorted(r["steam_review_id"] for r in reviews)
    assert len(seen_ids) == len(set(seen_ids))  # no duplicates


def test_chunk_hash_is_reproducible_across_invocations() -> None:
    # Because the 90-day recency window uses max(posted_at) from the dataset,
    # running the same review set twice yields identical chunk hashes even
    # if wall-clock time passes between runs.
    reviews = [
        _review(
            f"r{i}",
            voted_up=i % 2 == 0,
            posted_at="2024-01-01T00:00:00+00:00",
            votes_helpful=i,
        )
        for i in range(80)
    ]
    c1 = stratified_chunk_reviews(reviews, chunk_size=50)
    c2 = stratified_chunk_reviews(reviews, chunk_size=50)
    assert [compute_chunk_hash(c) for c in c1] == [compute_chunk_hash(c) for c in c2]
