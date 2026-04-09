"""Three-phase LLM analysis pipeline (chunk → merge → synthesize).

Phase 1 (LLM_MODEL__CHUNKING):  stratified 50-review chunks → RichChunkSummary (TopicSignals)
Phase 2 (LLM_MODEL__MERGING):   hierarchical merge → MergedSummary
Phase 3 (LLM_MODEL__SUMMARIZER): MergedSummary + context → GameReport

Each phase is idempotent and persisted in Postgres:
- chunk_summaries keyed on (appid, chunk_hash, prompt_version)
- merged_summaries cache-checked via find_latest_by_source_ids

Both real-time (ConverseBackend) and batch (BatchBackend) paths share these
helpers — editing a prompt here propagates to both modes. Plain sync `def`
throughout; the only parallelism is a thread pool inside ConverseBackend.run().
"""

import json
import time

from aws_lambda_powertools import Logger
from library_layer.config import SteamPulseConfig
from library_layer.events import AnalysisRequest
from library_layer.llm.backend import LLMBackend, LLMRequest
from library_layer.models.analyzer_models import (
    GameReport,
    MergedSummary,
    RichChunkSummary,
)
from library_layer.models.metadata import GameMetadataContext
from library_layer.models.temporal import GameTemporalContext
from library_layer.repositories.chunk_summary_repo import ChunkSummaryRepository
from library_layer.repositories.merged_summary_repo import MergedSummaryRepository
from library_layer.repositories.report_repo import ReportRepository
from library_layer.utils.chunking import (
    CHUNK_SIZE as STRATIFIED_CHUNK_SIZE,
)
from library_layer.utils.chunking import (
    compute_chunk_hash,
    stratified_chunk_reviews,
)
from library_layer.utils.scores import (
    compute_hidden_gem_score as _compute_hidden_gem_score,
)
from library_layer.utils.scores import (
    compute_sentiment_trend as _compute_sentiment_trend,
)

logger = Logger()
_config = SteamPulseConfig()


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
- "Refunded after 2 hours" → refund_signals ONLY (not churn_triggers)
- player_wishlist = features that DON'T EXIST; fixes to broken things = gameplay_friction
- "Store page says X but reviews disagree" → store_page_alignment ONLY (not gameplay_friction)
- "Reviewers love X but store page doesn't mention it" → store_page_alignment ONLY (not design_strengths)
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


def _build_synthesis_user_message(
    aggregated_signals: dict,
    game_name: str,
    total_reviews: int,
    hidden_gem_score: float,
    sentiment_trend: str,
    sentiment_trend_note: str,
    steam_positive_pct: int | float | None = None,
    steam_review_score_desc: str | None = None,
    temporal: GameTemporalContext | None = None,
    metadata: GameMetadataContext | None = None,
) -> str:
    signals_json = json.dumps(aggregated_signals, indent=2)
    steam_sentiment_line = ""
    if steam_positive_pct is not None or steam_review_score_desc is not None:
        pct_str = f"{int(steam_positive_pct)}%" if steam_positive_pct is not None else "unknown"
        desc_str = steam_review_score_desc or "unknown"
        steam_sentiment_line = (
            f"\n  Steam sentiment (canonical, do NOT recompute): {pct_str} positive ({desc_str})"
        )

    temporal_lines = ""
    if temporal is not None:
        ea_line = "No"
        if temporal.has_early_access:
            fraction_str = (
                f"{temporal.ea_fraction:.0%}" if temporal.ea_fraction is not None else "unknown"
            )
            delta_str = (
                f"{temporal.ea_sentiment_delta:+.1f}pp"
                if temporal.ea_sentiment_delta is not None
                else "unknown"
            )
            ea_line = (
                f"Yes — {fraction_str} of reviews from EA period, sentiment delta: {delta_str}"
            )
        vel_lifetime = (
            f"{temporal.review_velocity_lifetime:.1f}"
            if temporal.review_velocity_lifetime is not None
            else "N/A"
        )
        temporal_lines = f"""
  Released: {temporal.release_date} ({temporal.days_since_release} days ago, {temporal.release_age_bucket})
  Review velocity: {vel_lifetime} reviews/day lifetime, {temporal.review_velocity_last_30d} last 30 days ({temporal.velocity_trend})
  Launch trajectory: {temporal.launch_trajectory}
  Early Access: {ea_line}
  Evergreen: {"Yes" if temporal.is_evergreen else "No"}"""

    metadata_lines = ""
    if metadata is not None:
        if metadata.is_free:
            price_str = "Free"
        elif metadata.price_usd is not None:
            price_str = f"${metadata.price_usd}"
        else:
            price_str = "N/A"
        metacritic_str = (
            str(metadata.metacritic_score) if metadata.metacritic_score is not None else "N/A"
        )
        metadata_lines = f"""
  Price: {price_str}
  Platforms: {", ".join(metadata.platforms)}
  Steam Deck: {metadata.deck_status}
  Genres: {", ".join(metadata.genres)}
  Tags: {", ".join(metadata.tags)}
  Achievements: {metadata.achievements_total}
  Metacritic: {metacritic_str}"""

    store_description_block = ""
    store_page_alignment_section = ""
    store_check_items = ""
    if metadata is not None and metadata.about_the_game is not None:
        store_description_block = f"""
<store_description>
  <short>{metadata.short_desc or "Not available"}</short>
  <full>{metadata.about_the_game}</full>
</store_description>
"""
        store_page_alignment_section = """  <section name="store_page_alignment" type="object">
    Compare the store description above against what reviewers actually experienced.
    promises_delivered: up to 4 claims the store page makes that reviews confirm (array)
    promises_broken: up to 3 claims the store page makes that reviews contradict (array)
    hidden_strengths: up to 3 things reviewers love that the store page doesn't mention (array)
    audience_match: aligned|partial_mismatch|significant_mismatch
    audience_match_note: 1-2 sentences — WHO the description targets vs WHO actually plays (string)
  </section>
"""
        store_check_items = """5. store_page_alignment claims trace to BOTH the store description AND aggregated signals
6. No store_page_alignment item duplicates a design_strengths or gameplay_friction item
"""

    return f"""\
<game_context>
  Game: {game_name}
  Total reviews analyzed: {total_reviews}{steam_sentiment_line}
  Pre-computed hidden_gem_score: {hidden_gem_score}
  Pre-computed sentiment_trend: {sentiment_trend} ({sentiment_trend_note}){temporal_lines}{metadata_lines}
</game_context>
{store_description_block}
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
  <section name="refund_signals" type="object">
    refund_language_frequency: none|rare|moderate|frequent
    primary_refund_drivers: 1-3 reasons (array)
    risk_level: low|medium|high
    NOTE: this describes refund LANGUAGE found in reviews, not a refund prediction.
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
    confidence: low|medium|high — your confidence given the sample
    sample_size: integer — count of reviews mentioning playtime/content depth
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
{store_page_alignment_section}</section_definitions>

<self_check>
Before returning, verify:
1. No issue appears with the same framing in two sections
2. Every claim traces to a signal in aggregated_signals
3. dev_priorities are ranked by impact x frequency, not just listed
4. Literal enum values match exactly (e.g. "thriving" not "Thriving")
{store_check_items}</self_check>

<output_format>
Return the complete GameReport JSON. Do NOT include any sentiment_score or
overall_sentiment fields — Steam owns the sentiment number, this report is
narrative only. Include pre-computed values exactly as given:
  "hidden_gem_score": {hidden_gem_score},
  "sentiment_trend": "{sentiment_trend}",
  "sentiment_trend_note": "{sentiment_trend_note}"
</output_format>\
"""


# ===========================================================================
# Three-phase pipeline (chunk → merge → synthesize)
#
# New entry point: `analyze_game(request, *, backend, repos...)`.
# Both real-time (ConverseBackend) and batch (BatchBackend, via thin Step
# Functions Lambdas) call the SAME phase helpers here — prompts, chunking,
# merge hierarchy, synthesis, Python overrides, persistence.
# ===========================================================================


# Prompt version constants — bump any of these to invalidate cached rows at
# that phase. `chunk_summaries` unique key includes chunk prompt version;
# merge cache lookup includes merge prompt version; synthesis prompt version
# feeds `PIPELINE_VERSION` so a bump forces a synthesis re-run without
# invalidating earlier phases.
CHUNK_PROMPT_VERSION = "chunk-v2.0"
MERGE_PROMPT_VERSION = "merge-v1.0"
SYNTHESIS_PROMPT_VERSION = "synthesis-v3.0"
PIPELINE_VERSION = f"3.0/{CHUNK_PROMPT_VERSION}/{MERGE_PROMPT_VERSION}/{SYNTHESIS_PROMPT_VERSION}"


CHUNK_SYSTEM_PROMPT_V2 = """\
You extract structured topic signals from Steam game reviews for an analytics pipeline.
A later model merges and synthesizes your output — your ONLY job is accurate extraction.

<rules>
- Extract TOPICS, not flat signal strings. Each topic is a named subject
  (e.g. "base building", "matchmaking latency") with a category, sentiment,
  mention count, confidence, and representative quotes.
- Multiple reviews about the same subject = ONE topic with a higher mention_count.
- Quotes must be word-for-word from reviews. Include the steam_review_id.
- Counts in batch_stats must be exact for this batch.
- Do not invent, generalize, or embellish.
- confidence rule: "high" if mention_count >= 5 OR avg_helpful_votes >= 50,
  "medium" if mention_count >= 2, "low" otherwise.
</rules>

<signal_weighting>
- Reviews with more helpful votes = broad community agreement, stronger signal.
- Reviews with 50h+ playtime = informed player, weight friction/wishlist higher.
- Free-key reviews may be biased — note but don't weight equally.
- Early Access reviews reflect prior game state — tag in summary text.
</signal_weighting>

<category_definitions>
  design_praise: Specific DESIGN elements praised — mechanics, art, audio, controls,
    progression. EXCLUDE: community praise, price, nostalgia.
  gameplay_friction: In-game UX/design friction — balance, pacing, missing UI,
    difficulty spikes. EXCLUDE: pricing, community, platform issues, TECHNICAL BUGS.
  wishlist_items: NET-NEW features players want. EXCLUDE: fixes to broken things.
  dropout_moments: Moments/stages where players stopped or considered quitting.
    Must include timing in summary.
  technical_issues: Crashes, FPS drops, bugs, save corruption, compatibility,
    loading times. EXCLUDE: game design problems.
  refund_signals: Explicit refund language only. Include context in summary.
  community_health: Player community / multiplayer ecosystem signals.
    EXCLUDE: single-player design.
  monetization_sentiment: Feelings about DLC, microtransactions, battle passes.
    EXCLUDE: base game price.
  content_depth: Game length, replayability, content volume. Include playtime context.
</category_definitions>

Return ONLY valid JSON matching the RichChunkSummary schema. No prose, no preamble.\
"""


MERGE_SYSTEM_PROMPT = """\
You consolidate structured topic signals from multiple review analysis chunks
into a single unified summary.

<rules>
- MERGE topics about the same subject into ONE topic. Sum mention_counts.
  Reconcile sentiment weighted by mention_count.
- NEVER invent new topics, quotes, or information not in the input chunks.
- Keep the BEST quotes: prioritize by votes_helpful DESC, then playtime DESC.
  Max 3 quotes per topic, max 5 notable_quotes total.
- When merging sentiment: if 80%+ of mentions share the same sentiment, use that.
  If mixed, use "mixed".
- Confidence: recompute from merged mention_count (high >= 5, medium >= 2, low < 2).
- Merge total_stats by summing counts, weighted average for playtime,
  min/max for dates.
- competitor_refs: deduplicate by game name, keep the most informative context.
</rules>

<topic_dedup_rules>
- "matchmaking is slow" + "matchmaking takes too long" = ONE topic "matchmaking latency"
- "great art style" + "beautiful graphics" = ONE topic "visual design"
- "needs more maps" + "wants new content" = TWO topics (different specificity)
- When in doubt, keep separate. False merges lose information.
</topic_dedup_rules>

Return ONLY valid JSON matching the MergedSummary schema. No prose, no preamble.\
"""


def _build_chunk_user_message_v2(
    chunk: list[dict],
    game_name: str,
    chunk_index: int,
    total_chunks: int,
) -> str:
    reviews_text = "\n\n".join(
        f"[id:{r.get('steam_review_id') or 'unknown'}, "
        f"{'POSITIVE' if r['voted_up'] else 'NEGATIVE'}, "
        f"{r.get('playtime_hours') or 0}h played, "
        f"{r.get('votes_helpful') or 0} helpful, "
        f"{'Early Access' if r.get('written_during_early_access') else 'Post-launch'}, "
        f"{'Free Key' if r.get('received_for_free') else 'Paid'}, "
        f"{r['posted_at'][:10] if r.get('posted_at') else 'unknown date'}]: "
        f"{(r.get('review_text') or '')[:800]}"
        for r in chunk
    )

    dates = [r["posted_at"][:10] for r in chunk if r.get("posted_at")]
    date_range = f"({min(dates)} to {max(dates)})" if dates else "(dates unknown)"

    return f"""\
<task>
Extract structured topic signals from {len(chunk)} Steam reviews for "{game_name}"
(batch {chunk_index + 1} of {total_chunks}, covering {date_range}).
</task>

<reviews>
{reviews_text}
</reviews>

<output_format>
Return a RichChunkSummary JSON with:
  topics: array of TopicSignal objects, each with:
    topic (string), category (one of the category_definitions),
    sentiment ("positive"|"negative"|"mixed"), mention_count (integer >= 1),
    confidence ("low"|"medium"|"high"), summary (1-2 sentences),
    quotes (up to 3 ReviewQuotes with text, steam_review_id, voted_up,
            playtime_hours, votes_helpful),
    avg_playtime_hours, avg_helpful_votes
  competitor_refs: array of {{game, sentiment, context}}
  notable_quotes: up to 3 standalone verbatim quotes
  batch_stats: {{positive_count, negative_count, avg_playtime_hours,
                 high_playtime_count, early_access_count, free_key_count,
                 date_range_start, date_range_end}}
</output_format>\
"""


def _build_merge_user_message(
    summaries: list[RichChunkSummary],
    game_name: str,
) -> str:
    """Build the single-call merge prompt over all chunk summaries.

    With MAX_REVIEWS=2000 and CHUNK_SIZE=50, a single merge call sees at
    most ~40 RichChunkSummary objects (~60K tokens), well within Sonnet's
    200K context window. We deliberately avoid hierarchical merge to keep
    `source_chunk_ids` tracking simple and to eliminate the risk of running
    synthesis against a partial root.
    """
    payload = [s.model_dump(mode="json") for s in summaries]
    total_reviews = sum(
        s.batch_stats.positive_count + s.batch_stats.negative_count for s in summaries
    )
    return f"""\
<task>
Merge {len(summaries)} chunk summaries for "{game_name}" into a single
MergedSummary. Total reviews covered: {total_reviews}.
</task>

<input_summaries>
{json.dumps(payload, indent=2)}
</input_summaries>

<output_format>
Return a single MergedSummary JSON with the deduplicated topics, merged
total_stats, the best quotes, and the consolidated competitor_refs.
`merge_level` and `chunks_merged` are populated server-side — you may
leave them at their defaults.
</output_format>\
"""


def _build_synthesis_user_message_v3(
    merged: MergedSummary,
    game_name: str,
    total_reviews: int,
    hidden_gem_score: float,
    sentiment_trend: str,
    sentiment_trend_note: str,
    steam_positive_pct: int | float | None,
    steam_review_score_desc: str | None,
    temporal: GameTemporalContext | None,
    metadata: GameMetadataContext | None,
) -> str:
    # Reuse the existing contextual block builders from the legacy path so
    # the synthesis prompt stays consistent while swapping the signal payload
    # from a flat dict to the structured MergedSummary.
    legacy_signals = {
        "topics": [t.model_dump(mode="json") for t in merged.topics],
        "competitor_refs": [c.model_dump(mode="json") for c in merged.competitor_refs],
        "notable_quotes": [q.model_dump(mode="json") for q in merged.notable_quotes],
        "total_stats": merged.total_stats.model_dump(mode="json"),
        "chunks_merged": merged.chunks_merged,
    }
    return _build_synthesis_user_message(
        legacy_signals,
        game_name,
        total_reviews,
        hidden_gem_score,
        sentiment_trend,
        sentiment_trend_note,
        steam_positive_pct=steam_positive_pct,
        steam_review_score_desc=steam_review_score_desc,
        temporal=temporal,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Pure request builders — reused by both ConverseBackend (realtime) and
# BatchBackend (batch prepare Lambdas). These do NOT hit the DB or the LLM.
# ---------------------------------------------------------------------------


def build_chunk_requests(
    *,
    appid: int,
    game_name: str,
    reviews: list[dict],
    cached_hashes: set[str],
) -> tuple[list[list[dict]], list[LLMRequest], list[tuple[int, str, int]]]:
    """Compute chunks and build LLMRequests for those not in `cached_hashes`.

    Returns:
        chunks: the full stratified chunk list (length = total_chunks)
        pending: LLMRequests for chunks whose hash is not cached
        pending_meta: parallel list of (chunk_index, chunk_hash, chunk_size)
    """
    chunks = stratified_chunk_reviews(reviews, STRATIFIED_CHUNK_SIZE)
    total = len(chunks)
    pending: list[LLMRequest] = []
    pending_meta: list[tuple[int, str, int]] = []
    for i, chunk in enumerate(chunks):
        h = compute_chunk_hash(chunk)
        if h in cached_hashes:
            continue
        pending.append(
            LLMRequest(
                record_id=f"{appid}-chunk-{i}",
                task="chunking",
                system=CHUNK_SYSTEM_PROMPT_V2,
                user=_build_chunk_user_message_v2(chunk, game_name, i, total),
                max_tokens=1024,
                response_model=RichChunkSummary,
            )
        )
        pending_meta.append((i, h, len(chunk)))
    return chunks, pending, pending_meta


def build_merge_request(
    *,
    appid: int,
    game_name: str,
    summaries: list[RichChunkSummary],
) -> LLMRequest:
    """Build the single merge LLMRequest for a game's chunk summaries."""
    return LLMRequest(
        record_id=f"{appid}-merge",
        task="merging",
        system=MERGE_SYSTEM_PROMPT,
        user=_build_merge_user_message(summaries, game_name),
        max_tokens=4096,
        response_model=MergedSummary,
    )


def build_synthesis_request(
    *,
    appid: int,
    game_name: str,
    merged: MergedSummary,
    total_reviews: int,
    hidden_gem_score: float,
    sentiment_trend: str,
    sentiment_trend_note: str,
    steam_positive_pct: int | float | None,
    steam_review_score_desc: str | None,
    temporal: GameTemporalContext | None,
    metadata: GameMetadataContext | None,
) -> LLMRequest:
    return LLMRequest(
        record_id=f"{appid}-synthesis",
        task="summarizer",
        system=SYNTHESIS_SYSTEM_PROMPT,
        user=_build_synthesis_user_message_v3(
            merged,
            game_name,
            total_reviews,
            hidden_gem_score,
            sentiment_trend,
            sentiment_trend_note,
            steam_positive_pct,
            steam_review_score_desc,
            temporal,
            metadata,
        ),
        max_tokens=5000,
        response_model=GameReport,
    )


# ---------------------------------------------------------------------------
# Phase helpers — invoked identically from realtime and batch paths.
# ---------------------------------------------------------------------------


def _promote_single_chunk(chunk: RichChunkSummary, *, source_chunk_id: int) -> MergedSummary:
    """Skip the merge LLM call when there's only one chunk."""
    return MergedSummary(
        topics=list(chunk.topics),
        competitor_refs=list(chunk.competitor_refs),
        notable_quotes=list(chunk.notable_quotes)[:5],
        total_stats=chunk.batch_stats.model_copy(),
        merge_level=0,
        chunks_merged=1,
        source_chunk_ids=[source_chunk_id],
    )


def run_chunk_phase(
    *,
    appid: int,
    game_name: str,
    reviews: list[dict],
    backend: LLMBackend,
    chunk_repo: ChunkSummaryRepository,
) -> tuple[list[RichChunkSummary], list[int]]:
    """Phase 1: chunk + LLM summarise, with idempotent persistence.

    Returns (summaries_in_chunk_order, chunk_row_ids_in_order).
    """
    # Pre-load cache hits so we only send the DB-missing chunks to the backend.
    existing = {
        row["chunk_hash"]: row for row in chunk_repo.find_by_appid(appid, CHUNK_PROMPT_VERSION)
    }
    chunks, pending, pending_meta = build_chunk_requests(
        appid=appid,
        game_name=game_name,
        reviews=reviews,
        cached_hashes=set(existing.keys()),
    )
    logger.info(
        "chunk_phase_start",
        extra={
            "appid": appid,
            "total_chunks": len(chunks),
            "cached": len(chunks) - len(pending),
            "pending": len(pending),
        },
    )

    fresh = backend.run(pending) if pending else []
    if len(fresh) != len(pending):
        raise RuntimeError(
            f"backend.run returned {len(fresh)} responses for {len(pending)} requests"
        )

    # Interleave cached + fresh back into chunk_index order.
    summaries_by_index: dict[int, RichChunkSummary] = {}
    ids_by_index: dict[int, int] = {}
    model_id = _config.model_for("chunking")

    # Insert fresh rows first so ids exist for return.
    fresh_iter = iter(zip(pending_meta, fresh, strict=True))
    for (chunk_index, chunk_hash, chunk_size), summary in fresh_iter:
        if not isinstance(summary, RichChunkSummary):
            raise TypeError(f"backend returned {type(summary).__name__} for a chunking request")
        row_id = chunk_repo.insert(
            appid,
            chunk_index,
            chunk_hash,
            chunk_size,
            summary,
            model_id=model_id,
            prompt_version=CHUNK_PROMPT_VERSION,
        )
        summaries_by_index[chunk_index] = summary
        ids_by_index[chunk_index] = row_id

    # Backfill cached rows using the chunk_index they were stored with.
    for i, chunk in enumerate(chunks):
        if i in summaries_by_index:
            continue
        h = compute_chunk_hash(chunk)
        row = existing.get(h)
        if row is None:
            raise RuntimeError(f"cache expected for chunk {i} (hash={h}) but missing")
        summaries_by_index[i] = RichChunkSummary.model_validate(row["summary_json"])
        ids_by_index[i] = int(row["id"])

    ordered_summaries = [summaries_by_index[i] for i in range(len(chunks))]
    ordered_ids = [ids_by_index[i] for i in range(len(chunks))]
    return ordered_summaries, ordered_ids


def run_merge_phase(
    *,
    appid: int,
    game_name: str,
    chunk_summaries: list[RichChunkSummary],
    chunk_ids: list[int],
    backend: LLMBackend,
    merge_repo: MergedSummaryRepository,
) -> tuple[MergedSummary, int | None]:
    """Phase 2: single-call merge with cache-check on the full input set.

    Returns `(merged_summary, merged_row_id)`. For the single-chunk
    promotion case the row id is `None` (no LLM call, nothing persisted).
    For the full-set cache-hit path the existing row id is returned.

    Single-level merge is correct for SteamPulse because MAX_REVIEWS=2000
    divided by CHUNK_SIZE=50 yields at most ~40 chunk summaries per game
    (~60K tokens), well within Sonnet's 200K context window. This removes
    the need for a hierarchical loop and — critically — the attendant
    source-id bookkeeping problems it caused in both the realtime and
    batch paths.
    """
    if not chunk_summaries:
        raise ValueError("run_merge_phase called with zero chunks")

    if len(chunk_summaries) == 1:
        merged = _promote_single_chunk(chunk_summaries[0], source_chunk_id=chunk_ids[0])
        logger.info(
            "merge_phase_single_chunk_promoted",
            extra={"appid": appid, "source_chunk_id": chunk_ids[0]},
        )
        return merged, None

    # Try whole-set cache hit before doing any LLM work.
    cached = merge_repo.find_latest_by_source_ids(appid, chunk_ids, MERGE_PROMPT_VERSION)
    if cached is not None:
        logger.info(
            "merge_phase_cache_hit",
            extra={"appid": appid, "merge_id": cached["id"]},
        )
        return MergedSummary.model_validate(cached["summary_json"]), int(cached["id"])

    request = build_merge_request(appid=appid, game_name=game_name, summaries=chunk_summaries)
    [response] = backend.run([request])
    if not isinstance(response, MergedSummary):
        raise TypeError(f"backend returned {type(response).__name__} for a merging request")

    # Server-computed bookkeeping — never trust the LLM for these.
    response.merge_level = 1
    response.chunks_merged = len(chunk_summaries)
    response.source_chunk_ids = sorted(chunk_ids)

    model_id = _config.model_for("merging")
    merged_id = merge_repo.insert(
        appid,
        1,
        response,
        chunk_ids,
        len(chunk_summaries),
        model_id=model_id,
        prompt_version=MERGE_PROMPT_VERSION,
    )
    logger.info(
        "merge_phase_complete",
        extra={"appid": appid, "merge_id": merged_id, "chunks_merged": len(chunk_summaries)},
    )
    return response, merged_id


def run_synthesis_phase(
    *,
    appid: int,
    game_name: str,
    merged: MergedSummary,
    total_reviews: int,
    reviews: list[dict],
    steam_positive_pct: int | float | None,
    steam_review_count: int | None,
    steam_review_score_desc: str | None,
    temporal: GameTemporalContext | None,
    metadata: GameMetadataContext | None,
    backend: LLMBackend,
) -> GameReport:
    """Phase 3: synthesise MergedSummary → GameReport with Python overrides."""
    hidden_gem_score = _compute_hidden_gem_score(steam_positive_pct, steam_review_count)
    trend = _compute_sentiment_trend(reviews)

    request = build_synthesis_request(
        appid=appid,
        game_name=game_name,
        merged=merged,
        total_reviews=total_reviews,
        hidden_gem_score=hidden_gem_score,
        sentiment_trend=trend["trend"],
        sentiment_trend_note=trend["note"],
        steam_positive_pct=steam_positive_pct,
        steam_review_score_desc=steam_review_score_desc,
        temporal=temporal,
        metadata=metadata,
    )
    [response] = backend.run([request])
    if not isinstance(response, GameReport):
        raise TypeError(f"backend returned {type(response).__name__} for a synthesis request")

    # Defensive overrides — Steam owns sentiment magnitude, Python owns derived scores.
    response.hidden_gem_score = hidden_gem_score
    response.sentiment_trend = trend["trend"]  # type: ignore[assignment]
    response.sentiment_trend_note = trend["note"]
    response.sentiment_trend_reliable = trend["reliable"]
    response.sentiment_trend_sample_size = trend["sample_size"]
    response.appid = appid
    return response


def analyze_game(
    request: AnalysisRequest,
    *,
    backend: LLMBackend,
    chunk_repo: ChunkSummaryRepository,
    merge_repo: MergedSummaryRepository,
    report_repo: ReportRepository,
    reviews: list[dict],
    game_name: str,
    temporal: GameTemporalContext | None = None,
    metadata: GameMetadataContext | None = None,
    steam_positive_pct: int | float | None = None,
    steam_review_count: int | None = None,
    steam_review_score_desc: str | None = None,
) -> GameReport:
    """The single entry point for the three-phase pipeline.

    Identical call shape for realtime and batch modes — the ONLY thing that
    differs is the `backend` instance. Callers (the realtime handler and
    the batch Prepare Lambdas) are responsible for loading the Game row,
    review list, temporal/metadata contexts, and the backend.
    """
    if not reviews:
        raise ValueError(f"no reviews to analyze for appid={request.appid}")

    logger.append_keys(appid=request.appid, mode=request.mode)
    t_start = time.monotonic()

    chunk_summaries, chunk_ids = run_chunk_phase(
        appid=request.appid,
        game_name=game_name,
        reviews=reviews,
        backend=backend,
        chunk_repo=chunk_repo,
    )
    merged, merged_summary_id = run_merge_phase(
        appid=request.appid,
        game_name=game_name,
        chunk_summaries=chunk_summaries,
        chunk_ids=chunk_ids,
        backend=backend,
        merge_repo=merge_repo,
    )
    report = run_synthesis_phase(
        appid=request.appid,
        game_name=game_name,
        merged=merged,
        total_reviews=len(reviews),
        reviews=reviews,
        steam_positive_pct=steam_positive_pct,
        steam_review_count=steam_review_count,
        steam_review_score_desc=steam_review_score_desc,
        temporal=temporal,
        metadata=metadata,
        backend=backend,
    )

    # Persist the final report with pipeline bookkeeping. These columns
    # (added in migration 0036) let the handler/UI short-circuit a cold
    # re-analysis and give operators visibility into which prompt/phase
    # produced each report.
    report_payload = report.model_dump()
    report_payload["pipeline_version"] = PIPELINE_VERSION
    report_payload["chunk_count"] = len(chunk_summaries)
    report_payload["merged_summary_id"] = merged_summary_id
    report_repo.upsert(report_payload)

    elapsed_ms = round((time.monotonic() - t_start) * 1000)
    logger.info(
        "analyze_game_complete",
        extra={
            "appid": request.appid,
            "mode": request.mode,
            "chunks": len(chunk_summaries),
            "latency_ms": elapsed_ms,
            "pipeline_version": PIPELINE_VERSION,
        },
    )
    return report
