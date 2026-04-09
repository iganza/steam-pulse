"""Stratified chunking + deterministic chunk hashing for the three-phase analyzer.

Reviews are split into chunks of `CHUNK_SIZE` with three constraints:

1. Sentiment ratio — each chunk mirrors the game's overall positive/negative
   ratio so no chunk is 100% one-sided (which would bias extraction).
2. Playtime coverage — each chunk should contain at least one review from
   every available playtime bucket (<2h, 2-10h, 10-50h, 50-200h, 200h+).
3. Helpful-vote priority — reviews with higher `votes_helpful` are placed
   first within each pool. Reviews posted in the last 90 days get a 1.5x
   multiplier applied to their sort key only (not the stored vote count) so
   recent signal is weighted slightly higher.

The hash is deterministic over the set of `steam_review_id` values so that
re-ordering reviews inside a chunk does not invalidate the Phase 1 cache.
"""

import hashlib
import math
import random
from datetime import UTC, datetime, timedelta

CHUNK_SIZE = 50

_PLAYTIME_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("<2h", 0, 2),
    ("2-10h", 2, 10),
    ("10-50h", 10, 50),
    ("50-200h", 50, 200),
    ("200h+", 200, 10**9),
)


def _playtime_bucket(hours: int | float | None) -> str:
    h = float(hours or 0)
    for name, lo, hi in _PLAYTIME_BUCKETS:
        if lo <= h < hi:
            return name
    return "200h+"


def _posted_at(review: dict) -> datetime | None:
    raw = review.get("posted_at")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _sort_key(review: dict, now: datetime) -> float:
    """Higher = sorted earlier. Recent reviews get a 1.5x multiplier."""
    helpful = float(review.get("votes_helpful") or 0)
    posted = _posted_at(review)
    if posted is not None and now - posted <= timedelta(days=90):
        helpful *= 1.5
    return helpful


def stratified_chunk_reviews(
    reviews: list[dict],
    chunk_size: int = CHUNK_SIZE,
    *,
    seed: int = 42,
) -> list[list[dict]]:
    """Split reviews into sentiment-stratified chunks with playtime coverage.

    The input list is not mutated. Empty input returns an empty list.
    `seed` controls the in-chunk shuffle so ordering is deterministic for
    tests but not positional across runs.
    """
    if not reviews:
        return []

    now = datetime.now(UTC)

    positive = sorted(
        (r for r in reviews if r.get("voted_up")),
        key=lambda r: _sort_key(r, now),
        reverse=True,
    )
    negative = sorted(
        (r for r in reviews if not r.get("voted_up")),
        key=lambda r: _sort_key(r, now),
        reverse=True,
    )

    total = len(positive) + len(negative)
    target_positive_ratio = len(positive) / total if total else 0.0
    num_chunks = max(1, math.ceil(total / chunk_size))

    chunks: list[list[dict]] = [[] for _ in range(num_chunks)]
    pi = ni = 0
    for idx in range(num_chunks):
        want_pos = math.ceil(chunk_size * target_positive_ratio)
        want_neg = chunk_size - want_pos
        # Take from positive pool
        take_pos = positive[pi : pi + want_pos]
        pi += len(take_pos)
        # Take from negative pool
        take_neg = negative[ni : ni + want_neg]
        ni += len(take_neg)
        chunks[idx].extend(take_pos)
        chunks[idx].extend(take_neg)

    # Drain any remaining reviews (rounding fill) into the last chunk
    leftover = positive[pi:] + negative[ni:]
    if leftover:
        chunks[-1].extend(leftover)

    # Soft playtime-bucket coverage: for each chunk, try to ensure each
    # non-empty bucket is represented by swapping in a review from the
    # global pool's lowest-signal slot if the chunk is missing that bucket.
    _ensure_playtime_coverage(chunks, reviews)

    rng = random.Random(seed)
    for chunk in chunks:
        rng.shuffle(chunk)

    return [c for c in chunks if c]


def _ensure_playtime_coverage(chunks: list[list[dict]], all_reviews: list[dict]) -> None:
    """Best-effort: swap lowest-helpful review for a missing-bucket candidate.

    Only operates when an alternative reviewer from the missing bucket exists
    that isn't already present in the chunk. This is a soft constraint — if
    no swap is possible, the chunk is left as-is.
    """
    present_ids_per_chunk = [
        {str(r.get("steam_review_id")) for r in c if r.get("steam_review_id")}
        for c in chunks
    ]
    by_bucket: dict[str, list[dict]] = {name: [] for name, _, _ in _PLAYTIME_BUCKETS}
    for r in all_reviews:
        by_bucket[_playtime_bucket(r.get("playtime_hours"))].append(r)

    for idx, chunk in enumerate(chunks):
        if not chunk:
            continue
        present_buckets = {_playtime_bucket(r.get("playtime_hours")) for r in chunk}
        missing = [
            name
            for name, _, _ in _PLAYTIME_BUCKETS
            if name not in present_buckets and by_bucket[name]
        ]
        if not missing:
            continue
        # Sort chunk by helpful votes ascending so first items are lowest-signal.
        swap_order = sorted(
            range(len(chunk)),
            key=lambda i: float(chunk[i].get("votes_helpful") or 0),
        )
        for bucket in missing:
            candidate = next(
                (
                    r
                    for r in by_bucket[bucket]
                    if str(r.get("steam_review_id")) not in present_ids_per_chunk[idx]
                ),
                None,
            )
            if candidate is None or not swap_order:
                continue
            swap_idx = swap_order.pop(0)
            removed = chunk[swap_idx]
            chunk[swap_idx] = candidate
            present_ids_per_chunk[idx].discard(str(removed.get("steam_review_id")))
            present_ids_per_chunk[idx].add(str(candidate.get("steam_review_id")))


def compute_chunk_hash(reviews: list[dict]) -> str:
    """Deterministic 16-char hex hash keyed on the set of steam_review_ids.

    Same reviews in any order = same hash. Adding or removing a review
    changes the hash. Missing ids fall back to empty string so the hash is
    still stable for fixture data.
    """
    review_ids = sorted(str(r.get("steam_review_id") or "") for r in reviews)
    digest = hashlib.sha256("|".join(review_ids).encode("utf-8")).hexdigest()
    return digest[:16]
