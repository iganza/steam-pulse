"""Two-pass LLM analysis pipeline.

Pass 1 (LLM_MODEL__CHUNKING):   process 50-review chunks → extract signals.
Pass 2 (LLM_MODEL__SUMMARIZER): synthesize all chunk signals → structured GameReport.

Models are configured via the LLM_MODEL task map in .env.staging / .env.production.
"""

import json
import time

import anthropic
import instructor
from aws_lambda_powertools import Logger
from library_layer.config import SteamPulseConfig
from library_layer.models.analyzer_models import ChunkSummary, GameReport
from library_layer.utils.scores import (
    compute_hidden_gem_score as _compute_hidden_gem_score,
)
from library_layer.utils.scores import (
    compute_sentiment_score as _compute_sentiment_score,
)
from library_layer.utils.scores import (
    compute_sentiment_trend as _compute_sentiment_trend,
)
from library_layer.utils.scores import (
    sentiment_label as _sentiment_label,
)

logger = Logger()
_config = SteamPulseConfig()


def _get_instructor_client() -> instructor.Instructor:
    return instructor.from_anthropic(anthropic.AnthropicBedrock())


CHUNK_SYSTEM_PROMPT = """\
You extract structured signals from Steam game reviews for an analytics pipeline.
A later model synthesizes your output — your ONLY job is accurate extraction.

<rules>
- Extract only what is explicitly stated or clearly implied in the reviews.
- Do not invent, generalize, or embellish.
- Quotes in notable_quotes must be word-for-word from reviews.
- Counts in batch_stats must be exact for this batch.
</rules>

<signal_weighting>
- Reviews with more helpful votes = broad community agreement, stronger signal.
- Reviews with 50h+ playtime = informed player, weight friction/wishlist higher.
- Free-key reviews may be biased — note but don't weight equally.
- Early Access reviews reflect prior game state — tag signals as [EA].
</signal_weighting>

Return ONLY valid JSON. No prose, no preamble.\
"""

SYNTHESIS_SYSTEM_PROMPT = """\
You are a senior product analyst writing game intelligence reports.

<audience>
PRIMARY: Indie game developers making sprint/pivot decisions. They need clarity,
honesty, and prioritization — not validation.
SECONDARY: Gamers deciding whether to buy. The one_liner answers this completely.
</audience>

<anti_duplication_rules>
Each section answers EXACTLY ONE question. If an issue appears in two sections, STOP
and keep it only where the definition fits best:
- "Bots ruining the game" → gameplay_friction ONLY
- "New players encounter bots in first match" → churn_triggers ONLY (timing of departure)
- "Deploy anti-cheat" → dev_priorities ONLY (the fix)
- "Game crashes every 30 min" → technical_issues ONLY (not gameplay_friction)
- "DLC is overpriced" → monetization_sentiment ONLY (not gameplay_friction)
- "Dead multiplayer lobbies" → community_health ONLY (not churn_triggers)
- "Refunded after 2 hours" → refund_risk ONLY (not churn_triggers)
- player_wishlist = features that DON'T EXIST; fixes to broken things = gameplay_friction
</anti_duplication_rules>

<tone>
- Be specific: "Bots in 7 of 10 batches" beats "bots are a problem"
- Use severity deliberately: "critical", "significant", "minor"
- Do not soften bad news — developers need honest severity
- Empty array is better than vague filler
- No corporate language: no "leverage", "synergy", "pain points"
</tone>

<accuracy>
Never assume information not present in the aggregated signals.
Do not invent game features, mechanics, or controversies.
Every claim must trace to a signal from the chunk extraction pass.
</accuracy>

Return ONLY valid JSON. No prose, no preamble.\
"""

CHUNK_SIZE = 50


def _chunk_reviews(reviews: list[dict], chunk_size: int = CHUNK_SIZE) -> list[list[dict]]:
    return [reviews[i : i + chunk_size] for i in range(0, len(reviews), chunk_size)]


def _aggregate_chunk_summaries(chunk_summaries: list[ChunkSummary]) -> dict:
    """Flatten all chunk signals into one dict per signal type for Pass 2 synthesis.

    Used by both the real-time path (analyze_reviews) and the batch path (PreparePass2 Lambda).
    """
    chunks = chunk_summaries
    total_reviews = sum(
        cs.batch_stats.positive_count + cs.batch_stats.negative_count for cs in chunks
    )
    weighted_playtime = sum(
        cs.batch_stats.avg_playtime_hours * (cs.batch_stats.positive_count + cs.batch_stats.negative_count)
        for cs in chunks
    )
    return {
        "design_praise": [item for cs in chunks for item in cs.design_praise],
        "gameplay_friction": [item for cs in chunks for item in cs.gameplay_friction],
        "wishlist_items": [item for cs in chunks for item in cs.wishlist_items],
        "dropout_moments": [item for cs in chunks for item in cs.dropout_moments],
        "competitor_refs": [item.model_dump() for cs in chunks for item in cs.competitor_refs],
        "notable_quotes": [item for cs in chunks for item in cs.notable_quotes],
        "technical_issues": [item for cs in chunks for item in cs.technical_issues],
        "refund_signals": [item for cs in chunks for item in cs.refund_signals],
        "community_health": [item for cs in chunks for item in cs.community_health],
        "monetization_sentiment": [item for cs in chunks for item in cs.monetization_sentiment],
        "content_depth": [item for cs in chunks for item in cs.content_depth],
        "total_stats": {
            "positive_count": sum(cs.batch_stats.positive_count for cs in chunks),
            "negative_count": sum(cs.batch_stats.negative_count for cs in chunks),
            "avg_playtime_hours": round(weighted_playtime / max(total_reviews, 1), 1),
            "high_playtime_count": sum(cs.batch_stats.high_playtime_count for cs in chunks),
            "early_access_count": sum(cs.batch_stats.early_access_count for cs in chunks),
            "free_key_count": sum(cs.batch_stats.free_key_count for cs in chunks),
        },
    }


def _build_chunk_user_message(
    chunk: list[dict],
    chunk_index: int,
    total_chunks: int,
    game_name: str = "",
) -> str:
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
    game_label = f' for "{game_name}"' if game_name else ""

    return f"""\
<task>
Extract signals from {len(chunk)} Steam reviews{game_label}
(batch {chunk_index + 1} of {total_chunks}, covering {date_range}).
</task>

<signal_definitions>
  <signal name="design_praise">
    Specific DESIGN elements praised: mechanics, art, audio, controls, progression.
    EXCLUDE: community praise, price, nostalgia.
    Include playtime/helpful-vote context for high-signal reviews.
  </signal>
  <signal name="gameplay_friction">
    In-game UX/design friction: balance, pacing, missing UI, difficulty spikes.
    EXCLUDE: pricing, developer neglect, community, platform issues, TECHNICAL BUGS.
  </signal>
  <signal name="wishlist_items">
    NET-NEW features players want. EXCLUDE: fixes to broken things (→ gameplay_friction).
  </signal>
  <signal name="dropout_moments">
    Moments/stages where players stopped or considered quitting.
    Include timing: "after 2 hours", "in the tutorial", "at the third boss".
  </signal>
  <signal name="competitor_refs">
    Named games mentioned. Format: {{"game": "name", "sentiment": "positive|negative|neutral", "context": "phrase"}}.
    ONLY if a specific game title appears.
  </signal>
  <signal name="notable_quotes">
    0-2 vivid, representative verbatim quotes. Under 40 words each.
  </signal>
  <signal name="technical_issues">
    Crashes, FPS drops, bugs, save corruption, compatibility, loading times.
    EXCLUDE: game design problems (→ gameplay_friction).
  </signal>
  <signal name="refund_signals">
    Verbatim refund language only: "refunded", "got my money back", "waste of money".
    Include the context sentence. Only if EXPLICIT refund language is present.
  </signal>
  <signal name="community_health">
    Player community / multiplayer ecosystem signals: "dead servers", "toxic chat",
    "great Discord", "cheaters everywhere". EXCLUDE: single-player design issues.
  </signal>
  <signal name="monetization_sentiment">
    Feelings about DLC, microtransactions, battle passes, loot boxes, pay-to-win.
    EXCLUDE: base game price.
  </signal>
  <signal name="content_depth">
    Game length, replayability, content volume. Include reviewer's playtime for context.
  </signal>
</signal_definitions>

<examples>
  <example type="good">
    Review: [POSITIVE, 450h, 1523 helpful, Post-launch, Paid, 2024-06-15]: The base building
    is incredible, best crafting system I've played. Dead servers though, nobody online anymore.
    → design_praise: ["Base building and crafting system (450h player, 1523 helpful votes)"]
    → community_health: ["Dead servers — nobody online anymore (450h invested player)"]
    Note: High playtime + helpful votes = strong signal. Two signals, two categories.
  </example>
  <example type="bad">
    Same review →
    → design_praise: ["Good building system"] ← WRONG: paraphrased, lost credibility data
    → gameplay_friction: ["Nobody online"] ← WRONG: multiplayer population → community_health
  </example>
</examples>

<reviews>
{reviews_text}
</reviews>

<output_format>
{{
  "design_praise": ["string — include playtime/helpful context for high-signal reviews"],
  "gameplay_friction": ["string"],
  "wishlist_items": ["string"],
  "dropout_moments": ["string — must include timing"],
  "competitor_refs": [{{"game": "name", "sentiment": "positive|negative|neutral", "context": "phrase"}}],
  "notable_quotes": ["verbatim, max 2"],
  "technical_issues": ["string"],
  "refund_signals": ["string — verbatim language + context"],
  "community_health": ["string"],
  "monetization_sentiment": ["string"],
  "content_depth": ["string — include playtime"],
  "batch_stats": {{
    "positive_count": 0, "negative_count": 0, "avg_playtime_hours": 0.0,
    "high_playtime_count": 0, "early_access_count": 0, "free_key_count": 0
  }}
}}
</output_format>\
"""


def _build_synthesis_user_message(
    aggregated_signals: dict,
    game_name: str,
    total_reviews: int,
    sentiment_score: float,
    hidden_gem_score: float,
    sentiment_trend: str,
    sentiment_trend_note: str,
) -> str:
    overall_sentiment = _sentiment_label(sentiment_score)
    signals_json = json.dumps(aggregated_signals, indent=2)

    return f"""\
<game_context>
  Game: {game_name}
  Total reviews analyzed: {total_reviews}
  Pre-computed sentiment_score: {sentiment_score} ({overall_sentiment})
  Pre-computed hidden_gem_score: {hidden_gem_score}
  Pre-computed sentiment_trend: {sentiment_trend} ({sentiment_trend_note})
</game_context>

<aggregated_signals>
{signals_json}
</aggregated_signals>

<section_definitions>
  <section name="one_liner" type="string" constraint="max 25 words">
    Vivid, honest. For a gamer deciding whether to buy.
  </section>
  <section name="audience_profile" type="object">
    ideal_player: one-sentence persona
    casual_friendliness: low|medium|high
    archetypes: 2-4 player type labels
    not_for: 2-3 player types who will regret buying (identity-based, not moment-based)
  </section>
  <section name="design_strengths" type="array" constraint="2-8 items">
    Design decisions that work. EXCLUDE: community, price, nostalgia, external factors.
  </section>
  <section name="gameplay_friction" type="array" constraint="1-7 items">
    In-game UX/design problems. EXCLUDE: pricing, community, platform, TECHNICAL bugs.
  </section>
  <section name="player_wishlist" type="array" constraint="1-6 items">
    NET-NEW features only. EXCLUDE: fixes to broken things.
  </section>
  <section name="churn_triggers" type="array" constraint="1-4 items">
    Specific MOMENTS causing dropout. Must include timing language.
    EXCLUDE: the underlying design flaw itself — describe WHEN and WHAT triggers departure.
  </section>
  <section name="technical_issues" type="array" constraint="0-6 items">
    Format: "Issue — severity — affected % of negative reviews".
    Empty array if none reported.
  </section>
  <section name="refund_risk" type="object">
    refund_language_frequency: none|rare|moderate|frequent
    primary_refund_drivers: 1-3 reasons (array)
    risk_level: low|medium|high
  </section>
  <section name="community_health" type="object">
    overall: thriving|active|declining|dead|not_applicable
    signals: 2-4 community signals (array)
    multiplayer_population: healthy|shrinking|critical|not_applicable
  </section>
  <section name="monetization_sentiment" type="object">
    overall: fair|mixed|predatory|not_applicable
    signals: 1-3 monetization opinions (array)
    dlc_sentiment: positive|mixed|negative|not_applicable
  </section>
  <section name="content_depth" type="object">
    perceived_length: short|medium|long|endless
    replayability: low|medium|high
    value_perception: poor|fair|good|excellent
    signals: 2-3 content volume descriptions (array)
  </section>
  <section name="dev_priorities" type="array" constraint="3-5 items, RANKED by impact x frequency">
    Each: {{action, why_it_matters, frequency, effort: low|medium|high}}
    This section is DECISIONS, not re-descriptions.
  </section>
  <section name="competitive_context" type="array">
    Each: {{game, comparison_sentiment: positive|negative|neutral, note}}
    ONLY named competitors from signals. Empty if none.
  </section>
  <section name="genre_context" type="string">
    1-2 sentences benchmarking against genre norms. No named competitors here.
  </section>
</section_definitions>

<self_check>
Before returning, verify:
1. No issue appears with the same framing in two sections
2. Every claim traces to a signal in aggregated_signals
3. dev_priorities are ranked by impact x frequency, not just listed
4. Literal enum values match exactly (e.g. "thriving" not "Thriving")
</self_check>

<output_format>
Return the complete GameReport JSON. Include pre-computed values exactly as given:
  "sentiment_score": {sentiment_score},
  "hidden_gem_score": {hidden_gem_score},
  "sentiment_trend": "{sentiment_trend}",
  "sentiment_trend_note": "{sentiment_trend_note}",
  "overall_sentiment": "{overall_sentiment}"
</output_format>\
"""


def _summarize_chunk(
    client: instructor.Instructor,
    chunk: list[dict],
    chunk_index: int,
    total_chunks: int,
    game_name: str = "",
) -> ChunkSummary:
    """Pass 1: extract raw signals from a batch of reviews (LLM_MODEL__CHUNKING, prompt caching enabled)."""
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
                "content": _build_chunk_user_message(chunk, chunk_index, total_chunks, game_name),
            }
        ],
    )
    elapsed_ms = round((time.monotonic() - t0) * 1000)
    logger.info("chunk_done", extra={"chunk": chunk_index + 1, "latency_ms": elapsed_ms})
    return summary


def _synthesize(
    client: instructor.Instructor,
    aggregated_signals: dict,
    game_name: str,
    total_reviews: int,
    sentiment_score: float,
    hidden_gem_score: float,
    sentiment_trend: str,
    sentiment_trend_note: str,
) -> GameReport:
    """Pass 2: synthesize aggregated chunk signals into a final structured report (LLM_MODEL__SUMMARIZER)."""
    logger.info("synthesis_start", extra={
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
                "content": _build_synthesis_user_message(
                    aggregated_signals,
                    game_name,
                    total_reviews,
                    sentiment_score,
                    hidden_gem_score,
                    sentiment_trend,
                    sentiment_trend_note,
                ),
            }
        ],
    )
    elapsed_ms = round((time.monotonic() - t0) * 1000)
    overall_sentiment = _sentiment_label(sentiment_score)
    logger.info("synthesis_done", extra={"sentiment": overall_sentiment, "latency_ms": elapsed_ms})
    return report


def analyze_reviews(
    reviews: list[dict],
    game_name: str,
    appid: int | None = None,
) -> dict:
    """Full two-pass LLM analysis pipeline.

    Pass 1: extract raw signals per chunk (LLM_MODEL__CHUNKING).
    Pass 2: synthesize aggregated chunk signals into a structured report (LLM_MODEL__SUMMARIZER).
    sentiment_score, hidden_gem_score, and sentiment_trend are computed in Python — not LLM-guessed.
    """
    if not reviews:
        raise ValueError("No reviews to analyze")

    client = _get_instructor_client()
    chunks = _chunk_reviews(reviews)
    total_chunks = len(chunks)
    t_start = time.monotonic()
    logger.info("analysis_start", extra={"appid": appid, "reviews": len(reviews), "chunks": total_chunks})

    # Pass 1
    chunk_summaries = [
        _summarize_chunk(client, chunk, i, total_chunks, game_name)
        for i, chunk in enumerate(chunks)
    ]

    # Compute numeric scores and trend in Python before calling Sonnet
    sentiment_score = _compute_sentiment_score(chunk_summaries)
    hidden_gem_score = _compute_hidden_gem_score(len(reviews), sentiment_score)
    sentiment_trend, sentiment_trend_note = _compute_sentiment_trend(reviews)

    # Pass 2
    result: GameReport = _synthesize(
        client,
        _aggregate_chunk_summaries(chunk_summaries),
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
