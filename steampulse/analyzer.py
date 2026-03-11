"""Two-pass LLM analysis: Haiku for chunk summarization, Sonnet for synthesis."""

import json
import os

import anthropic

HAIKU_MODEL_DEFAULT = "claude-3-5-haiku-20241022"
SONNET_MODEL_DEFAULT = "claude-3-5-sonnet-20241022"


def _haiku_model() -> str:
    return os.getenv("HAIKU_MODEL", HAIKU_MODEL_DEFAULT)


def _sonnet_model() -> str:
    return os.getenv("SONNET_MODEL", SONNET_MODEL_DEFAULT)

CHUNK_SIZE = 50

CHUNK_SYSTEM_PROMPT = (
    "You are a signal extractor for a game review analytics pipeline. Your ONLY job is to "
    "pull raw, structured signals from a batch of Steam reviews — not to synthesize or "
    "editorialize. A later model will synthesize your output.\n\n"
    "Accuracy rules:\n"
    "- Only extract signals that are explicitly stated or clearly implied in the reviews.\n"
    "- Do not invent, generalize, or embellish.\n"
    "- Quotes must be word-for-word from the reviews.\n"
    "- Counts must be exact from this batch.\n"
    "Return ONLY valid JSON. No prose."
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
    "- player_wishlist = features that DON'T EXIST. Fixes to broken things = gameplay_friction.\n\n"
    "TONE:\n"
    "- Be specific. 'Bots present in 7 of 10 batches' beats 'bots are a problem.'\n"
    "- Be honest about severity. Use 'critical', 'significant', or 'minor' deliberately.\n"
    "- Do not soften bad news. Developers need to know when they have a serious problem.\n"
    "- Do not pad weak sections with filler. An empty list is better than vague noise.\n"
    "- Avoid corporate language: no 'leverage', 'synergy', or 'pain points'."
)


def _get_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key)


def _chunk_reviews(reviews: list[dict], chunk_size: int = CHUNK_SIZE) -> list[list[dict]]:
    return [reviews[i : i + chunk_size] for i in range(0, len(reviews), chunk_size)]


def _compute_sentiment_score(chunk_summaries: list[dict]) -> float:
    total_positive = sum(c.get("batch_stats", {}).get("positive_count", 0) for c in chunk_summaries)
    total = sum(
        c.get("batch_stats", {}).get("positive_count", 0) + c.get("batch_stats", {}).get("negative_count", 0)
        for c in chunk_summaries
    )
    return round(total_positive / total, 3) if total > 0 else 0.5


def _compute_hidden_gem_score(total_reviews: int, sentiment_score: float) -> float:
    if total_reviews > 50_000:
        return 0.0
    review_scarcity = max(0.0, 1.0 - (total_reviews / 10_000))
    quality_signal = max(0.0, sentiment_score - 0.65) / 0.35
    return round(review_scarcity * quality_signal, 2)


def _sentiment_label(score: float) -> str:
    if score >= 0.95:
        return "Overwhelmingly Positive"
    elif score >= 0.80:
        return "Very Positive"
    elif score >= 0.65:
        return "Positive"
    elif score >= 0.45:
        return "Mixed"
    elif score >= 0.30:
        return "Negative"
    elif score >= 0.15:
        return "Very Negative"
    return "Overwhelmingly Negative"


def _summarize_chunk(client: anthropic.Anthropic, chunk: list[dict], chunk_index: int, total_chunks: int) -> dict:
    """Pass 1: extract raw signals from a batch of reviews using Haiku with prompt caching."""
    reviews_text = "\n\n".join(
        f"[{'POSITIVE' if r['voted_up'] else 'NEGATIVE'}, "
        f"{r['playtime_at_review'] // 60}h playtime]: {r['review_text'][:800]}"
        for r in chunk
    )

    response = client.messages.create(
        model=_haiku_model(),
        max_tokens=1024,
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
                    f"(batch {chunk_index + 1} of {total_chunks}).\n\n"
                    f"{reviews_text}\n\n"
                    "Extract these signals. Each key is defined precisely:\n\n"
                    '- "design_praise": Specific DESIGN ELEMENTS players praise (mechanics, art, '
                    "audio, controls, progression). EXCLUDE: community praise, price, nostalgia.\n\n"
                    '- "gameplay_friction": Specific IN-GAME friction points (balance, pacing, '
                    "missing UI, difficulty spikes). EXCLUDE: pricing, developer neglect, "
                    "community behaviour, platform issues.\n\n"
                    '- "wishlist_items": NET-NEW features players wish existed. EXCLUDE: anything '
                    "that already exists but is broken — those go in gameplay_friction.\n\n"
                    '- "dropout_moments": Specific MOMENTS or STAGES when players say they stopped '
                    "playing or considered quitting. Include timing language if present "
                    '("after 2 hours", "in the tutorial", "at the third boss").\n\n'
                    '- "competitor_refs": Named games mentioned. Format each as '
                    '{"game": "name", "sentiment": "positive|negative|neutral", "context": "one phrase"}. '
                    "ONLY include if a specific game title is named.\n\n"
                    '- "notable_quotes": 0-2 verbatim quotes, vivid and representative, under 40 words each.\n\n'
                    '- "batch_stats": {"positive_count": N, "negative_count": N, "avg_playtime_hours": N}\n\n'
                    "Return ONLY this JSON:\n"
                    '{"design_praise": [], "gameplay_friction": [], "wishlist_items": [], '
                    '"dropout_moments": [], "competitor_refs": [], "notable_quotes": [], '
                    '"batch_stats": {"positive_count": 0, "negative_count": 0, "avg_playtime_hours": 0}}'
                ),
            }
        ],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "design_praise": [], "gameplay_friction": [], "wishlist_items": [],
            "dropout_moments": [], "competitor_refs": [], "notable_quotes": [],
            "batch_stats": {"positive_count": 0, "negative_count": 0, "avg_playtime_hours": 0},
        }


def _synthesize(
    client: anthropic.Anthropic,
    chunk_summaries: list[dict],
    game_name: str,
    total_reviews: int,
    sentiment_score: float,
    hidden_gem_score: float,
) -> dict:
    """Pass 2: synthesize all chunk signals into a final structured report using Sonnet."""
    summaries_text = json.dumps(chunk_summaries, indent=2)
    overall_sentiment = _sentiment_label(sentiment_score)

    response = client.messages.create(
        model=_sonnet_model(),
        max_tokens=3500,
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
                    f"Pre-calculated hidden_gem_score: {hidden_gem_score}\n\n"
                    f"CHUNK SUMMARIES (raw signals from Pass 1):\n{summaries_text}\n\n"
                    "Synthesize a complete analysis report. Return ONLY valid JSON.\n"
                    "Read each section definition carefully — they have strict exclusion rules.\n\n"
                    "{\n"
                    f'  "game_name": "{game_name}",\n'
                    f'  "total_reviews_analyzed": {total_reviews},\n'
                    f'  "overall_sentiment": "{overall_sentiment}",\n'
                    f'  "sentiment_score": {sentiment_score},\n'
                    '  "sentiment_trend": "improving|stable|declining",\n'
                    '  "sentiment_trend_note": "One sentence explaining WHY — not a restatement of the trend value.",\n'
                    '  "one_liner": "Max 25 words. Vivid and honest. For a gamer deciding whether to buy.",\n'
                    '  "audience_profile": {\n'
                    '    "ideal_player": "One-sentence persona of who will love this game",\n'
                    '    "casual_friendliness": "low|medium|high",\n'
                    '    "archetypes": ["2-4 player type labels from reviews"],\n'
                    '    "not_for": ["2-3 specific player types who will regret buying — identity-based, not moment-based"]\n'
                    "  },\n"
                    '  "design_strengths": [\n'
                    '    "Specific design decisions that are working. 4-8 items."\n'
                    '    "EXCLUDE: community praise, price, nostalgia, external factors dev does not control."\n'
                    "  ],\n"
                    '  "gameplay_friction": [\n'
                    '    "In-game UX and design problems. 3-7 items. Player-experience language."\n'
                    '    "EXCLUDE: pricing, developer neglect, community behaviour, platform issues."\n'
                    "  ],\n"
                    '  "player_wishlist": [\n'
                    '    "NET-NEW features that do not exist yet. 3-6 items."\n'
                    '    "EXCLUDE: fixes to broken things — those belong in gameplay_friction."\n'
                    "  ],\n"
                    '  "churn_triggers": [\n'
                    '    "Specific MOMENTS in the player journey that cause dropout. 2-4 items."\n'
                    '    "Must include timing language: \'within first 10 minutes\', \'around hour 3\'."\n'
                    '    "EXCLUDE: the underlying design problem itself — just describe WHEN and WHAT triggers departure."\n'
                    "  ],\n"
                    '  "dev_priorities": [\n'
                    '    {"action": "Imperative sentence — what to build/fix", "why_it_matters": "Business impact in plain English", "frequency": "~X% of negative reviews", "effort": "low|medium|high"}\n'
                    '    "3-5 items RANKED by impact × frequency. This section is DECISIONS, not re-descriptions of problems."\n'
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
                    "prescribes the fix. If you have the same sentence in two sections, delete the "
                    "duplicate and keep it only where the definition fits best."
                ),
            }
        ],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "game_name": game_name,
            "total_reviews_analyzed": total_reviews,
            "overall_sentiment": overall_sentiment,
            "sentiment_score": sentiment_score,
            "sentiment_trend": "stable",
            "sentiment_trend_note": "Analysis could not be parsed.",
            "one_liner": "Analysis could not be parsed.",
            "audience_profile": {"ideal_player": "", "casual_friendliness": "medium", "archetypes": [], "not_for": []},
            "design_strengths": [],
            "gameplay_friction": [],
            "player_wishlist": [],
            "churn_triggers": [],
            "dev_priorities": [],
            "competitive_context": [],
            "genre_context": "",
            "hidden_gem_score": hidden_gem_score,
        }


async def analyze_reviews(
    reviews: list[dict],
    game_name: str,
    appid: int | None = None,
) -> dict:
    """
    Full two-pass LLM analysis pipeline.
    Pass 1: extract raw signals per chunk via Haiku (cheap, parallel).
    Pass 2: synthesize all chunk signals into a structured report via Sonnet.
    sentiment_score and hidden_gem_score are computed in Python — not LLM-guessed.
    """
    import asyncio

    if not reviews:
        raise ValueError("No reviews to analyze")

    client = _get_client()
    chunks = _chunk_reviews(reviews)
    total_chunks = len(chunks)

    # Pass 1 — run chunk summarizations in a thread pool (SDK is sync)
    loop = asyncio.get_event_loop()
    chunk_summaries = []
    for i, chunk in enumerate(chunks):
        summary = await loop.run_in_executor(
            None, _summarize_chunk, client, chunk, i, total_chunks
        )
        chunk_summaries.append(summary)

    # Compute numeric scores in Python before calling Sonnet
    sentiment_score = _compute_sentiment_score(chunk_summaries)
    hidden_gem_score = _compute_hidden_gem_score(len(reviews), sentiment_score)

    # Pass 2 — synthesize
    result = await loop.run_in_executor(
        None, _synthesize, client, chunk_summaries, game_name, len(reviews),
        sentiment_score, hidden_gem_score,
    )

    if appid is not None:
        result["appid"] = appid

    return result
