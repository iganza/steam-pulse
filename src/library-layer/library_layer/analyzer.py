"""Two-pass LLM analysis pipeline.

Pass 1 (LLM_MODEL__CHUNKING):   process 50-review chunks → extract themes and signals.
Pass 2 (LLM_MODEL__SUMMARIZER): synthesize all chunk summaries → structured GameReport.

Models are configured via the LLM_MODEL task map in .env.staging / .env.production.
"""

import json
import time
from datetime import UTC, datetime, timedelta

import anthropic
import instructor
from aws_lambda_powertools import Logger
from library_layer.config import SteamPulseConfig
from library_layer.models.analyzer_models import ChunkSummary, GameReport

logger = Logger()
_config = SteamPulseConfig()


def _get_instructor_client() -> instructor.Instructor:
    return instructor.from_anthropic(anthropic.AnthropicBedrock())


CHUNK_SYSTEM_PROMPT = (
    "You are a signal extractor for a game review analytics pipeline. Your ONLY job is to "
    "pull raw, structured signals from a batch of Steam reviews — not to synthesize or "
    "editorialize. A later model will synthesize your output.\n\n"
    "Accuracy rules:\n"
    "- Only extract signals that are explicitly stated or clearly implied in the reviews.\n"
    "- Do not invent, generalize, or embellish.\n"
    "- Quotes must be word-for-word from the reviews.\n"
    "- Counts must be exact from this batch.\n"
    "Return ONLY valid JSON. No prose.\n\n"
    "Signal weighting:\n"
    "- Reviews with more helpful votes carry stronger signal. A complaint from a review "
    "with 500 helpful votes represents broad community agreement, not just one person's opinion.\n"
    "- Reviews with high playtime (50h+) come from invested players — their friction points "
    "and wishlist items are more informed.\n"
    "- Free-key reviews may be biased; note them but don't weight them equally.\n"
    "- Early Access reviews reflect a prior state of the game; tag signals from them as [EA] when extracting."
)

SYNTHESIS_SYSTEM_PROMPT = (
    "You are a senior product analyst at a game analytics company. Your clients are indie game "
    "developers who paid for this report because they need to make real decisions about their "
    "next sprint or whether to pivot their game's direction. They need clarity, honesty, and "
    "prioritization — not validation or vague encouragement.\n\n"
    "Your output must serve two audiences:\n"
    "1. DEVELOPERS (primary): Business decisions, what to fix, what to protect, what the risk is.\n"
    "2. GAMERS (secondary): 'Should I buy this?' — the one_liner answers this completely.\n\n"
    "CRITICAL ANTI-DUPLICATION RULES:\n"
    "- Each section answers EXACTLY ONE question. Read each section definition carefully.\n"
    "- If you find yourself writing the same issue in two sections, STOP. Put it only in the "
    "section whose definition best fits.\n"
    "- 'Bots are ruining the game' → gameplay_friction ONLY.\n"
    "- 'New players encounter bots in their first match' → churn_triggers ONLY.\n"
    "- 'Deploy anti-cheat' → dev_priorities ONLY.\n"
    "- player_wishlist = features that DON'T EXIST. Fixes to broken things = gameplay_friction.\n"
    "- 'Game crashes every 30 minutes' → technical_issues ONLY (not gameplay_friction).\n"
    "- 'DLC is overpriced' → monetization_sentiment ONLY (not gameplay_friction).\n"
    "- 'Dead multiplayer lobbies' → community_health ONLY (not churn_triggers).\n"
    "- 'Refunded after 2 hours' → refund_risk ONLY (not churn_triggers).\n\n"
    "TONE:\n"
    "- Be specific. 'Bots present in 7 of 10 batches' beats 'bots are a problem.'\n"
    "- Be honest about severity. Use 'critical', 'significant', or 'minor' deliberately.\n"
    "- Do not soften bad news. Developers need to know when they have a serious problem.\n"
    "- Do not pad weak sections with filler. An empty list is better than vague noise.\n"
    "- Avoid corporate language: no 'leverage', 'synergy', or 'pain points'."
)

CHUNK_SIZE = 50


def _chunk_reviews(reviews: list[dict], chunk_size: int = CHUNK_SIZE) -> list[list[dict]]:
    return [reviews[i : i + chunk_size] for i in range(0, len(reviews), chunk_size)]


def _compute_sentiment_score(chunk_summaries: list[ChunkSummary]) -> float:
    total_positive = sum(c.batch_stats.positive_count for c in chunk_summaries)
    total = sum(
        c.batch_stats.positive_count + c.batch_stats.negative_count for c in chunk_summaries
    )
    return round(total_positive / total, 3) if total > 0 else 0.5


def _compute_hidden_gem_score(total_reviews: int, sentiment_score: float) -> float:
    if total_reviews > 50_000:
        return 0.0
    review_scarcity = max(0.0, 1.0 - (total_reviews / 10_000))
    quality_signal = max(0.0, sentiment_score - 0.65) / 0.35
    return round(review_scarcity * quality_signal, 2)


def _compute_sentiment_trend(reviews: list[dict]) -> tuple[str, str]:
    """Compute sentiment trend from review timestamps.

    Compares positive_pct of last 90 days vs. prior 90 days.
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
    elif delta < -0.05:
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


def _sentiment_label(score: float) -> str:
    if score >= 0.95:
        return "Overwhelmingly Positive"
    elif score >= 0.80:
        return "Very Positive"
    elif score >= 0.65:
        return "Mostly Positive"
    elif score >= 0.45:
        return "Mixed"
    elif score >= 0.30:
        return "Mostly Negative"
    elif score >= 0.15:
        return "Very Negative"
    return "Overwhelmingly Negative"


def _summarize_chunk(
    client: instructor.Instructor,
    chunk: list[dict],
    chunk_index: int,
    total_chunks: int,
) -> ChunkSummary:
    """Pass 1: extract raw signals from a batch of reviews (LLM_MODEL__CHUNKING, prompt caching enabled)."""
    reviews_text = "\n\n".join(
        f"[{'POSITIVE' if r['voted_up'] else 'NEGATIVE'}, "
        f"{r['playtime_hours']}h played, "
        f"{r['votes_helpful']} helpful votes, "
        f"{'Early Access' if r['written_during_early_access'] else 'Post-launch'}, "
        f"{'Free Key' if r['received_for_free'] else 'Paid'}, "
        f"{r['posted_at'][:10] if r.get('posted_at') else 'unknown date'}]: "
        f"{r['review_text'][:800]}"
        for r in chunk
    )

    dates = [r["posted_at"][:10] for r in chunk if r.get("posted_at")]
    date_range = f"({min(dates)} to {max(dates)})" if dates else "(dates unknown)"

    logger.info("chunk_start", extra={
        "chunk": chunk_index + 1,
        "total_chunks": total_chunks,
        "reviews": len(chunk),
        "model": _config.model_for("chunking"),
    })
    t0 = time.monotonic()
    summary, _ = client.messages.create_with_completion(
        model=_config.model_for("chunking"),
        max_tokens=1024,
        response_model=ChunkSummary,
        max_retries=2,
        system=[
            {
                "type": "text",
                "text": CHUNK_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Analyze this batch of {len(chunk)} Steam reviews "
                    f"(batch {chunk_index + 1} of {total_chunks}, {date_range}).\n\n"
                    f"{reviews_text}\n\n"
                    "Extract these signals. Each key is defined precisely:\n\n"
                    '- "design_praise": Specific DESIGN ELEMENTS players praise (mechanics, art, '
                    "audio, controls, progression). EXCLUDE: community praise, price, nostalgia.\n\n"
                    '- "gameplay_friction": Specific IN-GAME friction points (balance, pacing, '
                    "missing UI, difficulty spikes). EXCLUDE: pricing, developer neglect, "
                    "community behaviour, platform issues, TECHNICAL BUGS (those go in technical_issues).\n\n"
                    '- "wishlist_items": NET-NEW features players wish existed. EXCLUDE: anything '
                    "that already exists but is broken — those go in gameplay_friction.\n\n"
                    '- "dropout_moments": Specific MOMENTS or STAGES when players say they stopped '
                    "playing or considered quitting. Include timing language if present "
                    '("after 2 hours", "in the tutorial", "at the third boss").\n\n'
                    '- "competitor_refs": Named games mentioned. Format each as '
                    '{"game": "name", "sentiment": "positive|negative|neutral", "context": "one phrase"}. '
                    "ONLY include if a specific game title is named.\n\n"
                    '- "notable_quotes": 0-2 verbatim quotes, vivid and representative, under 40 words each.\n\n'
                    '- "technical_issues": Specific TECHNICAL problems: crashes, FPS drops, bugs, '
                    "save corruption, compatibility issues, loading times. EXCLUDE: game design "
                    'problems (those go in gameplay_friction). Examples: "crashes to desktop every '
                    '30 minutes", "FPS drops to 10 in large battles", "save file corrupted after 20 hours".\n\n'
                    '- "refund_signals": Exact phrases indicating refund intent or completed refunds. '
                    'Copy verbatim: "refunded", "got my money back", "waste of money", "returned this", '
                    '"steam refund", "want my money back". Include the context sentence. '
                    "Only include if EXPLICIT refund language is present.\n\n"
                    '- "community_health": Signals about the player community and multiplayer ecosystem. '
                    '"dead servers", "toxic chat", "great Discord", "no one plays anymore", '
                    '"cheaters everywhere", "helpful community". EXCLUDE: single-player game design issues.\n\n'
                    '- "monetization_sentiment": Player feelings about pricing, DLC, microtransactions, '
                    'battle passes, loot boxes, pay-to-win. "overpriced DLC", "great value for the price", '
                    '"pay-to-win garbage", "fair monetization". EXCLUDE: the base game price.\n\n'
                    '- "content_depth": Player descriptions of game length, replayability, and content '
                    'volume. "beat it in 4 hours", "200 hours and still finding new things", "felt short", '
                    '"endless replayability", "not enough content for the price". '
                    "Include the reviewer's playtime for context.\n\n"
                    '- "batch_stats": {"positive_count": N, "negative_count": N, "avg_playtime_hours": N, '
                    '"high_playtime_count": N (reviews with >50h played), "early_access_count": N, "free_key_count": N}\n\n'
                    "Return ONLY this JSON:\n"
                    '{"design_praise": [], "gameplay_friction": [], "wishlist_items": [], '
                    '"dropout_moments": [], "competitor_refs": [], "notable_quotes": [], '
                    '"technical_issues": [], "refund_signals": [], "community_health": [], '
                    '"monetization_sentiment": [], "content_depth": [], '
                    '"batch_stats": {"positive_count": 0, "negative_count": 0, "avg_playtime_hours": 0, '
                    '"high_playtime_count": 0, "early_access_count": 0, "free_key_count": 0}}'
                ),
            }
        ],
    )
    elapsed_ms = round((time.monotonic() - t0) * 1000)
    logger.info("chunk_done", extra={"chunk": chunk_index + 1, "latency_ms": elapsed_ms})
    return summary


def _synthesize(
    client: instructor.Instructor,
    chunk_summaries: list[ChunkSummary],
    game_name: str,
    total_reviews: int,
    sentiment_score: float,
    hidden_gem_score: float,
    sentiment_trend: str,
    sentiment_trend_note: str,
) -> GameReport:
    """Pass 2: synthesize all chunk signals into a final structured report (LLM_MODEL__SUMMARIZER)."""
    summaries_text = json.dumps([s.model_dump() for s in chunk_summaries], indent=2)
    overall_sentiment = _sentiment_label(sentiment_score)

    logger.info("synthesis_start", extra={
        "chunks": len(chunk_summaries),
        "total_reviews": total_reviews,
        "model": _config.model_for("summarizer"),
        "sentiment_score": sentiment_score,
    })
    t0 = time.monotonic()
    report, _ = client.messages.create_with_completion(
        model=_config.model_for("summarizer"),
        max_tokens=5000,
        response_model=GameReport,
        max_retries=2,
        system=[
            {
                "type": "text",
                "text": SYNTHESIS_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Game: {game_name}\n"
                    f"Total reviews analyzed: {total_reviews}\n"
                    f"Chunks processed: {len(chunk_summaries)}\n"
                    f"Pre-calculated sentiment_score: {sentiment_score} "
                    f"(overall_sentiment: {overall_sentiment})\n"
                    f"Pre-calculated hidden_gem_score: {hidden_gem_score}\n"
                    f"Pre-calculated sentiment_trend: {sentiment_trend} ({sentiment_trend_note})\n\n"
                    f"CHUNK SUMMARIES (raw signals from Pass 1):\n{summaries_text}\n\n"
                    "Synthesize a complete analysis report. Return ONLY valid JSON.\n"
                    "Read each section definition carefully — they have strict exclusion rules.\n\n"
                    "{\n"
                    f'  "game_name": "{game_name}",\n'
                    f'  "total_reviews_analyzed": {total_reviews},\n'
                    f'  "overall_sentiment": "{overall_sentiment}",\n'
                    f'  "sentiment_score": {sentiment_score},\n'
                    f'  "sentiment_trend": "{sentiment_trend}",\n'
                    f'  "sentiment_trend_note": "{sentiment_trend_note}",\n'
                    '  "one_liner": "Max 25 words. Vivid and honest. For a gamer deciding whether to buy.",\n'
                    '  "audience_profile": {\n'
                    '    "ideal_player": "One-sentence persona of who will love this game",\n'
                    '    "casual_friendliness": "low|medium|high",\n'
                    '    "archetypes": ["2-4 player type labels from reviews"],\n'
                    '    "not_for": ["2-3 specific player types who will regret buying — identity-based, not moment-based"]\n'
                    "  },\n"
                    '  "design_strengths": [\n'
                    '    "Specific design decisions that are working. 2-8 items."\n'
                    '    "EXCLUDE: community praise, price, nostalgia, external factors dev does not control."\n'
                    "  ],\n"
                    '  "gameplay_friction": [\n'
                    '    "In-game UX and design problems. 1-7 items. Player-experience language."\n'
                    '    "EXCLUDE: pricing, developer neglect, community behaviour, platform issues, TECHNICAL BUGS."\n'
                    "  ],\n"
                    '  "player_wishlist": [\n'
                    '    "NET-NEW features that do not exist yet. 1-6 items."\n'
                    '    "EXCLUDE: fixes to broken things — those belong in gameplay_friction."\n'
                    "  ],\n"
                    '  "churn_triggers": [\n'
                    '    "Specific MOMENTS in the player journey that cause dropout. 1-4 items."\n'
                    "    \"Must include timing language: 'within first 10 minutes', 'around hour 3'.\"\n"
                    '    "EXCLUDE: the underlying design problem itself — just describe WHEN and WHAT triggers departure."\n'
                    "  ],\n"
                    '  "technical_issues": [\n'
                    '    "Specific technical problems: crashes, performance, bugs, compatibility. 0-6 items."\n'
                    "    \"Format: 'Issue — severity — affected % of negative reviews'.\"\n"
                    '    "If no technical issues were reported, use an empty array."\n'
                    "  ],\n"
                    '  "refund_risk": {\n'
                    '    "refund_language_frequency": "none|rare|moderate|frequent",\n'
                    '    "primary_refund_drivers": ["1-3 reasons players cited for refunding"],\n'
                    '    "risk_level": "low|medium|high"\n'
                    "  },\n"
                    '  "community_health": {\n'
                    '    "overall": "thriving|active|declining|dead|not_applicable",\n'
                    '    "signals": ["2-4 specific community signals from reviews"],\n'
                    '    "multiplayer_population": "healthy|shrinking|critical|not_applicable"\n'
                    "  },\n"
                    '  "monetization_sentiment": {\n'
                    '    "overall": "fair|mixed|predatory|not_applicable",\n'
                    '    "signals": ["1-3 specific monetization opinions from reviews"],\n'
                    '    "dlc_sentiment": "positive|mixed|negative|not_applicable"\n'
                    "  },\n"
                    '  "content_depth": {\n'
                    '    "perceived_length": "short|medium|long|endless",\n'
                    '    "replayability": "low|medium|high",\n'
                    '    "value_perception": "poor|fair|good|excellent",\n'
                    '    "signals": ["2-3 specific player descriptions of content volume"]\n'
                    "  },\n"
                    '  "dev_priorities": [\n'
                    '    {"action": "Imperative sentence — what to build/fix", "why_it_matters": "Business impact in plain English", "frequency": "~X% of negative reviews", "effort": "low|medium|high"}\n'
                    '    "3-5 items RANKED by impact x frequency. This section is DECISIONS, not re-descriptions of problems."\n'
                    "  ],\n"
                    '  "competitive_context": [\n'
                    '    {"game": "exact name", "comparison_sentiment": "positive|negative|neutral", "note": "one phrase"}\n'
                    '    "ONLY named competitors from reviews. Empty array if none mentioned."\n'
                    "  ],\n"
                    '  "genre_context": "1-2 sentences benchmarking against genre norms. No named competitors here.",\n'
                    f'  "hidden_gem_score": {hidden_gem_score}\n'
                    "}\n\n"
                    "BEFORE RETURNING: Self-check for duplication. For each issue you've written, "
                    "verify it appears with a DIFFERENT FRAMING in each section — friction describes "
                    "the flaw, churn_triggers describes when it causes departure, dev_priorities "
                    "prescribes the fix, technical_issues covers crashes/bugs, community_health covers "
                    "multiplayer ecosystem, monetization_sentiment covers pricing/DLC. "
                    "If you have the same sentence in two sections, delete the "
                    "duplicate and keep it only where the definition fits best."
                ),
            }
        ],
    )
    elapsed_ms = round((time.monotonic() - t0) * 1000)
    logger.info("synthesis_done", extra={"sentiment": overall_sentiment, "latency_ms": elapsed_ms})
    return report


async def analyze_reviews(
    reviews: list[dict],
    game_name: str,
    appid: int | None = None,
) -> dict:
    """
    Full two-pass LLM analysis pipeline.
    Pass 1: extract raw signals per chunk (LLM_MODEL__CHUNKING, cheap, parallel).
    Pass 2: synthesize all chunk signals into a structured report (LLM_MODEL__SUMMARIZER).
    sentiment_score, hidden_gem_score, and sentiment_trend are computed in Python — not LLM-guessed.
    """
    import asyncio

    if not reviews:
        raise ValueError("No reviews to analyze")

    client = _get_instructor_client()
    chunks = _chunk_reviews(reviews)
    total_chunks = len(chunks)
    t_start = time.monotonic()
    logger.info("analysis_start", extra={"appid": appid, "reviews": len(reviews), "chunks": total_chunks})

    # Pass 1 — run chunk summarizations in a thread pool (SDK is sync)
    loop = asyncio.get_event_loop()
    chunk_summaries: list[ChunkSummary] = []
    for i, chunk in enumerate(chunks):
        summary = await loop.run_in_executor(None, _summarize_chunk, client, chunk, i, total_chunks)
        chunk_summaries.append(summary)

    # Compute numeric scores and trend in Python before calling Sonnet
    sentiment_score = _compute_sentiment_score(chunk_summaries)
    hidden_gem_score = _compute_hidden_gem_score(len(reviews), sentiment_score)
    sentiment_trend, sentiment_trend_note = _compute_sentiment_trend(reviews)

    # Pass 2 — synthesize
    result: GameReport = await loop.run_in_executor(
        None,
        _synthesize,
        client,
        chunk_summaries,
        game_name,
        len(reviews),
        sentiment_score,
        hidden_gem_score,
        sentiment_trend,
        sentiment_trend_note,
    )

    # Override with Python-computed values — more reliable than LLM-guessed values
    result.sentiment_score = sentiment_score
    result.hidden_gem_score = hidden_gem_score
    result.sentiment_trend = sentiment_trend
    result.sentiment_trend_note = sentiment_trend_note

    if appid is not None:
        result.appid = appid

    elapsed_ms = round((time.monotonic() - t_start) * 1000)
    logger.info("analysis_complete", extra={
        "appid": appid,
        "sentiment": result.overall_sentiment,
        "score": result.sentiment_score,
        "latency_ms": elapsed_ms,
    })

    return result.model_dump()
