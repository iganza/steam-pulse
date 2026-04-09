"""Stratified chunking + deterministic chunk hashing for the three-phase analyzer.

Reviews are split into chunks with two constraints:

1. Sentiment ratio — each chunk mirrors the game's overall positive/negative
   ratio so no chunk is 100% one-sided (which would bias extraction).
2. Helpful-vote priority — reviews with higher `votes_helpful` are placed
   first within each pool. Reviews posted within 90 days of the caller's
   `reference_time` get a 1.5x multiplier on the sort key only.

**No function in this module carries default parameter values.** Every
caller must pass `chunk_size`, `reference_time`, and `seed` explicitly so
behavior cannot drift silently as we change defaults elsewhere. The
canonical defaults live in `SteamPulseConfig` and are propagated from
handlers down through `analyze_game`.

The hash is deterministic over the set of `steam_review_id` values. Every
review MUST carry a `steam_review_id`; missing ids raise `ValueError`
rather than silently collapsing to a shared placeholder and colliding.
"""

import hashlib
import math
import random
from datetime import datetime, timedelta


def _posted_at(review: dict) -> datetime | None:
    raw = review.get("posted_at")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


_NINETY_DAYS = timedelta(days=90)


def _sort_key(review: dict, reference_time: datetime) -> float:
    """Higher = sorted earlier. Reviews posted within the 90 days BEFORE
    `reference_time` get a 1.5x multiplier.

    The lower bound (`delta >= 0`) is important: without it, reviews
    post-dating `reference_time` (from clock skew, a caller that passes
    a wall-clock anchor instead of `dataset_reference_time`, or future
    test fixtures) would also satisfy `reference_time - posted <= 90d`
    because `timedelta` can be negative. We only want the window
    *behind* the anchor.
    """
    helpful = float(review.get("votes_helpful") or 0)
    posted = _posted_at(review)
    if posted is not None:
        delta = reference_time - posted
        if timedelta(0) <= delta <= _NINETY_DAYS:
            helpful *= 1.5
    return helpful


def stratified_chunk_reviews(
    reviews: list[dict],
    *,
    chunk_size: int,
    reference_time: datetime,
    seed: int,
) -> list[list[dict]]:
    """Split reviews into sentiment-stratified chunks.

    Partition invariant: every input review appears in exactly one output
    chunk. The input list is not mutated. Empty input returns [].

    Args:
        reviews: the full review set for a game.
        chunk_size: target chunk size (e.g. from
            `SteamPulseConfig.ANALYSIS_CHUNK_SIZE`).
        reference_time: the "now" anchor for the 90-day recency multiplier.
            Callers typically derive this from the dataset (max posted_at)
            so chunk membership — and therefore `chunk_hash` values — stays
            reproducible across runs, even as wall-clock time passes.
        seed: deterministic in-chunk shuffle seed (e.g. from
            `SteamPulseConfig.ANALYSIS_CHUNK_SHUFFLE_SEED`).
    """
    if not reviews:
        return []
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}")

    positive = sorted(
        (r for r in reviews if r.get("voted_up")),
        key=lambda r: _sort_key(r, reference_time),
        reverse=True,
    )
    negative = sorted(
        (r for r in reviews if not r.get("voted_up")),
        key=lambda r: _sort_key(r, reference_time),
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


def dataset_reference_time(reviews: list[dict]) -> datetime:
    """Derive the recency-window 'now' anchor from the newest review.

    Raises `ValueError` if no review carries a parseable `posted_at` —
    callers must not receive a silent epoch fallback. If you truly want a
    specific anchor (e.g. an analysis-time wall clock), construct it at
    the call site and pass it into `stratified_chunk_reviews` directly.
    """
    latest: datetime | None = None
    for r in reviews:
        posted = _posted_at(r)
        if posted is None:
            continue
        if latest is None or posted > latest:
            latest = posted
    if latest is None:
        raise ValueError(
            "dataset_reference_time: no review carries a parseable `posted_at`; "
            "caller must provide an explicit reference_time"
        )
    return latest


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
