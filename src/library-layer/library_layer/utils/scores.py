"""Scoring utilities shared by the real-time and batch analysis paths.

All functions operate on plain Python structures (no Bedrock, no instructor).
Import from analyzer.py (real-time path) and batch_analysis/prepare_pass2.py.

Steam's `positive_pct` is the canonical sentiment number — these helpers never
recompute it from sampled review batches. The only sentiment-derived helper here
is `compute_sentiment_trend`, which compares two adjacent windows of voted_up
flags from the local review sample to label trajectory (improving/stable/declining).
"""

from datetime import UTC, date, datetime, timedelta
from typing import TypedDict


class SentimentTrend(TypedDict):
    trend: str  # "improving" | "stable" | "declining"
    note: str
    sample_size: int  # total reviews across both windows
    reliable: bool  # True when each window has >= 50 reviews


def compute_hidden_gem_score(positive_pct: int | float | None, review_count: int | None) -> float:
    """Hidden gem score: high quality + low discoverability.

    Returns 0.0 to 1.0 where 1.0 = strong hidden gem candidate.

    Formula:
        scarcity = 1 - (review_count / 10000)   # 0 at 10k+, 1 at 0
        quality  = (positive_pct - 80) / 20     # 0 at 80%, 1 at 100%
        score    = scarcity * quality

    Thresholds:
        - Review cap: 10,000 (games above this are "well-known", not hidden)
        - Quality baseline: 80% positive (lower quality games aren't gems)

    Both inputs are Steam-sourced — no dependency on AI analysis.
    """
    if positive_pct is None or review_count is None:
        return 0.0
    pct = float(positive_pct)
    if review_count >= 10_000:
        return 0.0
    if pct < 80:
        return 0.0
    scarcity = 1.0 - (review_count / 10_000)
    quality = (pct - 80) / 20
    return round(scarcity * quality, 2)


def compute_sentiment_trend(reviews: list[dict]) -> SentimentTrend:
    """Compare positive_pct of last 90 days vs. prior 90 days.

    Returns a dict with trend label, narrative note, sample_size and a `reliable`
    flag (True when EACH window has at least 50 reviews — anything less and the
    label is informational only).
    """
    now = datetime.now(UTC)
    cutoff_recent = now - timedelta(days=90)
    cutoff_prior = now - timedelta(days=180)

    recent_str = cutoff_recent.strftime("%Y-%m-%d")
    prior_str = cutoff_prior.strftime("%Y-%m-%d")

    def _date_str(r: dict) -> str | None:
        v = r.get("posted_at")
        if isinstance(v, datetime | date):
            return v.strftime("%Y-%m-%d")
        if isinstance(v, str):
            return v[:10]
        return None

    recent = [r for r in reviews if (_date_str(r) or "") >= recent_str and _date_str(r)]
    prior = [r for r in reviews if prior_str <= (_date_str(r) or "") < recent_str and _date_str(r)]

    sample_size = len(recent) + len(prior)
    reliable = len(recent) >= 50 and len(prior) >= 50

    if len(recent) < 10 or len(prior) < 10:
        return SentimentTrend(
            trend="stable",
            note="Insufficient recent review volume to determine trend.",
            sample_size=sample_size,
            reliable=False,
        )

    recent_pct = sum(1 for r in recent if r["voted_up"]) / len(recent)
    prior_pct = sum(1 for r in prior if r["voted_up"]) / len(prior)
    delta = recent_pct - prior_pct

    if delta > 0.05:
        return SentimentTrend(
            trend="improving",
            note=(
                f"Sentiment rose from {prior_pct:.0%} to {recent_pct:.0%} positive "
                f"over the last 90 days ({len(recent)} reviews vs {len(prior)} prior)."
            ),
            sample_size=sample_size,
            reliable=reliable,
        )
    if delta < -0.05:
        return SentimentTrend(
            trend="declining",
            note=(
                f"Sentiment dropped from {prior_pct:.0%} to {recent_pct:.0%} positive "
                f"over the last 90 days ({len(recent)} reviews vs {len(prior)} prior)."
            ),
            sample_size=sample_size,
            reliable=reliable,
        )
    return SentimentTrend(
        trend="stable",
        note=(
            f"Sentiment steady at ~{recent_pct:.0%} positive "
            f"over the last 180 days ({len(recent) + len(prior)} reviews)."
        ),
        sample_size=sample_size,
        reliable=reliable,
    )
