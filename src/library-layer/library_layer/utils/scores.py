"""Scoring utilities shared by the real-time and batch analysis paths.

All three score functions operate on plain Python structures (no Bedrock, no instructor).
Import these in analyzer.py (real-time path) and in batch_analysis/prepare_pass2.py.
"""

from datetime import UTC, datetime, timedelta

from library_layer.models.analyzer_models import ChunkSummary


def compute_sentiment_score(chunk_summaries: list[ChunkSummary]) -> float:
    total_positive = sum(c.batch_stats.positive_count for c in chunk_summaries)
    total = sum(
        c.batch_stats.positive_count + c.batch_stats.negative_count for c in chunk_summaries
    )
    return round(total_positive / total, 3) if total > 0 else 0.5


def compute_hidden_gem_score(total_reviews: int, sentiment_score: float) -> float:
    if total_reviews > 50_000:
        return 0.0
    review_scarcity = max(0.0, 1.0 - (total_reviews / 10_000))
    quality_signal = max(0.0, sentiment_score - 0.65) / 0.35
    return round(review_scarcity * quality_signal, 2)


def compute_sentiment_trend(reviews: list[dict]) -> tuple[str, str]:
    """Compare positive_pct of last 90 days vs. prior 90 days.

    Returns (trend_label, trend_note).
    """
    now = datetime.now(UTC)
    cutoff_recent = now - timedelta(days=90)
    cutoff_prior = now - timedelta(days=180)

    recent_str = cutoff_recent.strftime("%Y-%m-%d")
    prior_str = cutoff_prior.strftime("%Y-%m-%d")

    recent = [
        r for r in reviews
        if r.get("posted_at") and r["posted_at"][:10] >= recent_str
    ]
    prior = [
        r for r in reviews
        if r.get("posted_at") and prior_str <= r["posted_at"][:10] < recent_str
    ]

    if len(recent) < 10 or len(prior) < 10:
        return "stable", "Insufficient recent review volume to determine trend."

    recent_pct = sum(1 for r in recent if r["voted_up"]) / len(recent)
    prior_pct = sum(1 for r in prior if r["voted_up"]) / len(prior)
    delta = recent_pct - prior_pct

    if delta > 0.05:
        return (
            "improving",
            f"Sentiment rose from {prior_pct:.0%} to {recent_pct:.0%} positive "
            f"over the last 90 days ({len(recent)} reviews vs {len(prior)} prior).",
        )
    if delta < -0.05:
        return (
            "declining",
            f"Sentiment dropped from {prior_pct:.0%} to {recent_pct:.0%} positive "
            f"over the last 90 days ({len(recent)} reviews vs {len(prior)} prior).",
        )
    return (
        "stable",
        f"Sentiment steady at ~{recent_pct:.0%} positive "
        f"over the last 180 days ({len(recent) + len(prior)} reviews).",
    )


def sentiment_label(score: float) -> str:
    if score >= 0.95:
        return "Overwhelmingly Positive"
    if score >= 0.80:
        return "Very Positive"
    if score >= 0.65:
        return "Mostly Positive"
    if score >= 0.45:
        return "Mixed"
    if score >= 0.30:
        return "Mostly Negative"
    if score >= 0.15:
        return "Very Negative"
    return "Overwhelmingly Negative"
