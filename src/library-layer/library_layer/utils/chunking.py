"""Stratified chunking + deterministic chunk hashing for the three-phase analyzer.

Reviews are split into chunks of `CHUNK_SIZE` with two constraints:

1. Sentiment ratio — each chunk mirrors the game's overall positive/negative
   ratio so no chunk is 100% one-sided (which would bias extraction).
2. Helpful-vote priority — reviews with higher `votes_helpful` are placed
   first within each pool. Reviews posted within 90 days of the NEWEST
   review in the dataset get a 1.5x multiplier applied to their sort key
   only (not the stored vote count) so recent signal is weighted slightly
   higher.

The "now" reference for the 90-day recency window is derived from the
dataset itself (max posted_at), NOT from `datetime.now()`. This keeps the
chunk ordering — and therefore `chunk_hash` values and Phase-1 cache hits —
reproducible over time for an unchanged review set.

The hash is deterministic over the set of `steam_review_id` values. Every
review MUST carry a steam_review_id; missing ids raise ValueError rather
than silently collapsing to a shared placeholder and causing cache collisions.
"""

import hashlib
import math
import random
from datetime import UTC, datetime, timedelta

CHUNK_SIZE = 50


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


def _dataset_reference_time(reviews: list[dict]) -> datetime:
    """Derive the 'now' reference from the newest review in the dataset.

    This keeps chunk ordering reproducible: rerunning the same review set
    yields the same chunks and the same `chunk_hash` values, regardless of
    wall-clock time. Falls back to epoch only if no review carries a
    posted_at (in which case the 1.5x recency multiplier is moot anyway).
    """
    latest: datetime | None = None
    for r in reviews:
        posted = _posted_at(r)
        if posted is None:
            continue
        if latest is None or posted > latest:
            latest = posted
    return latest if latest is not None else datetime(1970, 1, 1, tzinfo=UTC)


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
    """Split reviews into sentiment-stratified chunks.

    Partition invariant: every input review appears in exactly one output
    chunk. The input list is not mutated. Empty input returns [].
    `seed` controls the in-chunk shuffle so ordering is deterministic for
    tests but not positional across runs.
    """
    if not reviews:
        return []

    now = _dataset_reference_time(reviews)

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
        take_pos = positive[pi : pi + want_pos]
        pi += len(take_pos)
        take_neg = negative[ni : ni + want_neg]
        ni += len(take_neg)
        chunks[idx].extend(take_pos)
        chunks[idx].extend(take_neg)

    # Drain any remaining reviews (rounding fill) into the last chunk.
    leftover = positive[pi:] + negative[ni:]
    if leftover:
        chunks[-1].extend(leftover)

    rng = random.Random(seed)
    for chunk in chunks:
        rng.shuffle(chunk)

    return [c for c in chunks if c]


def compute_chunk_hash(reviews: list[dict]) -> str:
    """Deterministic 16-char hex hash keyed on the set of steam_review_ids.

    Same reviews in any order = same hash. Adding or removing a review
    changes the hash. `steam_review_id` is REQUIRED for every review —
    missing ids raise ValueError rather than silently colliding under a
    shared empty-string placeholder.
    """
    review_ids: list[str] = []
    for r in reviews:
        rid = r.get("steam_review_id")
        if not rid:
            raise ValueError(
                "compute_chunk_hash: review is missing steam_review_id "
                "(every review must carry a stable id for cache keying)"
            )
        review_ids.append(str(rid))
    review_ids.sort()
    digest = hashlib.sha256("|".join(review_ids).encode("utf-8")).hexdigest()
    return digest[:16]
