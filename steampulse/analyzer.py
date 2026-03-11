"""Two-pass LLM analysis: Haiku for chunk summarization, Sonnet for synthesis."""

import json
import os
from typing import Optional

import anthropic

HAIKU_MODEL_DEFAULT = "claude-3-5-haiku-20241022"
SONNET_MODEL_DEFAULT = "claude-3-5-sonnet-20241022"


def _haiku_model() -> str:
    return os.getenv("HAIKU_MODEL", HAIKU_MODEL_DEFAULT)


def _sonnet_model() -> str:
    return os.getenv("SONNET_MODEL", SONNET_MODEL_DEFAULT)

CHUNK_SIZE = 50

SYNTHESIS_SYSTEM_PROMPT = (
    "You are a game analytics expert helping indie game developers understand their "
    "Steam reviews. Your analysis must be specific, actionable, and honest — not generic. "
    "Developers need to know what to actually fix, not vague summaries. Focus on patterns "
    "that appear in multiple reviews, not outliers."
)

CHUNK_SYSTEM_PROMPT = (
    "You are a game review analyst. Extract structured insights from a batch of Steam reviews. "
    "Be concise and specific. Return only valid JSON."
)


def _get_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key)


def _chunk_reviews(reviews: list[dict], chunk_size: int = CHUNK_SIZE) -> list[list[dict]]:
    return [reviews[i : i + chunk_size] for i in range(0, len(reviews), chunk_size)]


def _summarize_chunk(client: anthropic.Anthropic, chunk: list[dict], chunk_index: int) -> dict:
    """Pass 1: summarize a batch of reviews using Haiku with prompt caching."""
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
                    f"Analyze this batch of {len(chunk)} Steam reviews (batch {chunk_index + 1}).\n\n"
                    f"{reviews_text}\n\n"
                    "Return JSON with these exact keys:\n"
                    '{"complaints": ["..."], "praises": ["..."], "feature_requests": ["..."]}'
                ),
            }
        ],
    )

    raw = response.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"complaints": [], "praises": [], "feature_requests": []}


def _synthesize(
    client: anthropic.Anthropic,
    chunk_summaries: list[dict],
    game_name: str,
    total_reviews: int,
) -> dict:
    """Pass 2: synthesize all chunk summaries into a final structured report using Sonnet."""
    summaries_text = json.dumps(chunk_summaries, indent=2)

    response = client.messages.create(
        model=_sonnet_model(),
        max_tokens=2048,
        system=SYNTHESIS_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Game: {game_name}\n"
                    f"Total reviews analyzed: {total_reviews}\n\n"
                    f"Chunk summaries from {len(chunk_summaries)} batches:\n{summaries_text}\n\n"
                    "Synthesize into a final report. Return ONLY valid JSON with these exact keys:\n"
                    "{\n"
                    '  "game_name": "string",\n'
                    '  "total_reviews_analyzed": 347,\n'
                    '  "overall_sentiment": "Mixed|Positive|Negative|Very Positive|Very Negative|Overwhelmingly Positive",\n'
                    '  "sentiment_score": 0.52,\n'
                    '  "top_praises": ["art style", "core loop", "music"],\n'
                    '  "top_complaints": ["difficulty spike", "no save", "performance"],\n'
                    '  "feature_requests": ["difficulty settings", "controller remapping"],\n'
                    '  "refund_risk_signals": ["61% of refunders cite difficulty within first 30min"],\n'
                    '  "competitive_mentions": ["Hades", "Dead Cells"],\n'
                    '  "dev_action_items": [\n'
                    '    "Add difficulty option — in 23% of negative reviews",\n'
                    '    "Add manual save — in 18% of negative reviews"\n'
                    "  ],\n"
                    '  "one_liner": "Players love the art but are bouncing at hour 3 due to difficulty spike."\n'
                    "}"
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
            "overall_sentiment": "Unknown",
            "sentiment_score": 0.5,
            "top_praises": [],
            "top_complaints": [],
            "feature_requests": [],
            "refund_risk_signals": [],
            "competitive_mentions": [],
            "dev_action_items": [],
            "one_liner": "Analysis could not be parsed.",
        }


async def analyze_reviews(
    reviews: list[dict],
    game_name: str,
    appid: Optional[int] = None,
) -> dict:
    """
    Full two-pass LLM analysis pipeline.
    Pass 1: chunk summarization via Haiku (cheap).
    Pass 2: final synthesis via Sonnet.
    """
    import asyncio

    if not reviews:
        raise ValueError("No reviews to analyze")

    client = _get_client()
    chunks = _chunk_reviews(reviews)

    # Pass 1 — run chunk summarizations in a thread pool (SDK is sync)
    loop = asyncio.get_event_loop()
    chunk_summaries = []
    for i, chunk in enumerate(chunks):
        summary = await loop.run_in_executor(
            None, _summarize_chunk, client, chunk, i
        )
        chunk_summaries.append(summary)

    # Pass 2 — synthesize
    result = await loop.run_in_executor(
        None, _synthesize, client, chunk_summaries, game_name, len(reviews)
    )

    if appid is not None:
        result["appid"] = appid

    return result
