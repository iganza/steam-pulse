# SteamPulse Analyzer Upgrade — Richer Signals, Better Prompts

## Goal

Upgrade the two-pass LLM analysis pipeline to extract significantly more
value from review data. Three categories of changes:

1. **Feed the LLM more data** — pass all review metadata (not just 3 fields)
2. **Compute metrics in Python** — don't let the LLM guess what we can calculate
3. **Add new report sections** — 5 new intelligence categories that devs need

## Files to Modify

- `src/library-layer/library_layer/services/analysis_service.py` — review data prep
- `src/library-layer/library_layer/analyzer.py` — prompts + pipeline
- `src/library-layer/library_layer/analyzer_models.py` — Pydantic models
- `tests/services/test_analyzer.py` — unit tests (if exists, else create)
- `tests/test_analyzer_models.py` — model validation tests

## Current State (read these files first)

The analyzer has two passes:
- **Pass 1 (Haiku):** `_summarize_chunk()` — extracts raw signals from 50-review batches
- **Pass 2 (Sonnet):** `_synthesize()` — combines all chunk signals into final report
- `analyze_reviews()` orchestrates: chunk → parallel Pass 1 → compute scores → Pass 2

Currently, `analysis_service.py` (line 51-56) only feeds 3 fields to the LLM:
```python
{"voted_up": r.voted_up, "review_text": r.body, "playtime_at_review": (r.playtime_hours or 0) * 60}
```

But the `reviews` table has: `votes_helpful`, `votes_funny`, `posted_at`,
`written_during_early_access`, `received_for_free`, `language` — all unused.

---

## Change 1: Pass Full Review Metadata

### analysis_service.py

Update the review-to-dict mapping (line 51-58) to include all fields:

```python
reviews_for_llm = [
    {
        "voted_up": r.voted_up,
        "review_text": r.body or "",
        "playtime_hours": r.playtime_hours or 0,
        "votes_helpful": r.votes_helpful or 0,
        "votes_funny": r.votes_funny or 0,
        "posted_at": r.posted_at.isoformat() if r.posted_at else None,
        "written_during_early_access": r.written_during_early_access or False,
        "received_for_free": r.received_for_free or False,
    }
    for r in db_reviews
    if r.body
]
```

Also: **sort reviews by posted_at ascending** before passing to the analyzer.
This means earlier chunks contain older reviews and later chunks contain newer
ones — giving Sonnet chronological signal.

```python
reviews_for_llm.sort(key=lambda r: r["posted_at"] or "")
```

Remove the `playtime_at_review` key (it was minutes; use `playtime_hours` directly).

### analyzer.py — _summarize_chunk

Update the review formatting (line 108-112) to include all metadata:

```python
reviews_text = "\n\n".join(
    f"[{'POSITIVE' if r['voted_up'] else 'NEGATIVE'}, "
    f"{r['playtime_hours']}h played, "
    f"{r['votes_helpful']} helpful votes, "
    f"{'Early Access' if r['written_during_early_access'] else 'Post-launch'}, "
    f"{'Free Key' if r['received_for_free'] else 'Paid'}, "
    f"{r['posted_at'][:10] if r['posted_at'] else 'unknown date'}]: "
    f"{r['review_text'][:800]}"
    for r in chunk
)
```

Example formatted review:
```
[POSITIVE, 450h played, 1523 helpful votes, Post-launch, Paid, 2024-06-15]: This game changed how I think about...
[NEGATIVE, 2h played, 0 helpful votes, Post-launch, Free Key, 2025-01-03]: Crashes on startup every time...
```

---

## Change 2: Compute sentiment_trend in Python

Currently `sentiment_trend` is LLM-guessed with no temporal data. Compute it
from actual review timestamps instead.

### analyzer.py — new function

```python
def _compute_sentiment_trend(reviews: list[dict]) -> tuple[str, str]:
    """Compute sentiment trend from review timestamps.
    
    Compares positive_pct of last 90 days vs. prior 90 days.
    Returns (trend_label, trend_note).
    """
    from datetime import datetime, timedelta, timezone
    
    now = datetime.now(timezone.utc)
    cutoff_recent = now - timedelta(days=90)
    cutoff_prior = now - timedelta(days=180)
    
    recent = [r for r in reviews if r.get("posted_at") and r["posted_at"][:10] >= cutoff_recent.strftime("%Y-%m-%d")]
    prior = [r for r in reviews if r.get("posted_at") and cutoff_prior.strftime("%Y-%m-%d") <= r["posted_at"][:10] < cutoff_recent.strftime("%Y-%m-%d")]
    
    if len(recent) < 10 or len(prior) < 10:
        return "stable", "Insufficient recent review volume to determine trend."
    
    recent_pct = sum(1 for r in recent if r["voted_up"]) / len(recent)
    prior_pct = sum(1 for r in prior if r["voted_up"]) / len(prior)
    delta = recent_pct - prior_pct
    
    if delta > 0.05:
        trend = "improving"
        note = (f"Sentiment rose from {prior_pct:.0%} to {recent_pct:.0%} positive "
                f"over the last 90 days ({len(recent)} reviews vs {len(prior)} prior).")
    elif delta < -0.05:
        trend = "declining"
        note = (f"Sentiment dropped from {prior_pct:.0%} to {recent_pct:.0%} positive "
                f"over the last 90 days ({len(recent)} reviews vs {len(prior)} prior).")
    else:
        trend = "stable"
        note = (f"Sentiment steady at ~{recent_pct:.0%} positive "
                f"over the last 180 days ({len(recent) + len(prior)} reviews).")
    
    return trend, note
```

### analyzer.py — analyze_reviews

Call this function and pass results to synthesize. Then override the LLM values
in the result (same pattern as sentiment_score):

```python
sentiment_trend, sentiment_trend_note = _compute_sentiment_trend(reviews)
# ... pass to _synthesize ...
result.sentiment_trend = sentiment_trend
result.sentiment_trend_note = sentiment_trend_note
```

Also pass the computed trend to Sonnet so it can reference it:
```
Pre-calculated sentiment_trend: {sentiment_trend} ({sentiment_trend_note})
```

---

## Change 3: Enhanced Chunk Prompt (Pass 1)

Update the user message in `_summarize_chunk` to extract 5 new signal types.
Keep all existing signals. Add these after the existing `"batch_stats"` definition:

```
- "technical_issues": Specific TECHNICAL problems: crashes, FPS drops, bugs,
  save corruption, compatibility issues, loading times. EXCLUDE: game design
  problems (those go in gameplay_friction). Examples: "crashes to desktop every
  30 minutes", "FPS drops to 10 in large battles", "save file corrupted after
  20 hours".

- "refund_signals": Exact phrases indicating refund intent or completed refunds.
  Copy verbatim: "refunded", "got my money back", "waste of money", "returned
  this", "steam refund", "want my money back". Include the context sentence.
  Only include if EXPLICIT refund language is present.

- "community_health": Signals about the player community and multiplayer
  ecosystem. "dead servers", "toxic chat", "great Discord", "no one plays
  anymore", "cheaters everywhere", "helpful community". EXCLUDE: single-player
  game design issues.

- "monetization_sentiment": Player feelings about pricing, DLC, microtransactions,
  battle passes, loot boxes, pay-to-win. "overpriced DLC", "great value for the
  price", "pay-to-win garbage", "fair monetization". EXCLUDE: the base game
  price (we have that as structured data).

- "content_depth": Player descriptions of game length, replayability, and content
  volume. "beat it in 4 hours", "200 hours and still finding new things",
  "felt short", "endless replayability", "not enough content for the price".
  Include the reviewer's playtime for context.
```

Update the JSON template at the bottom of the chunk prompt to include these:

```json
{
  "design_praise": [], "gameplay_friction": [], "wishlist_items": [],
  "dropout_moments": [], "competitor_refs": [], "notable_quotes": [],
  "technical_issues": [], "refund_signals": [], "community_health": [],
  "monetization_sentiment": [], "content_depth": [],
  "batch_stats": {
    "positive_count": 0, "negative_count": 0, "avg_playtime_hours": 0,
    "high_playtime_count": 0, "early_access_count": 0, "free_key_count": 0
  }
}
```

Also update the `batch_stats` definition in the prompt:
```
- "batch_stats": {"positive_count": N, "negative_count": N,
  "avg_playtime_hours": N, "high_playtime_count": N (reviews with >50h played),
  "early_access_count": N, "free_key_count": N}
```

**Add a weighting instruction** to the chunk system prompt (append to
CHUNK_SYSTEM_PROMPT):

```
Signal weighting:
- Reviews with more helpful votes carry stronger signal. A complaint from a review
  with 500 helpful votes represents broad community agreement, not just one person's opinion.
- Reviews with high playtime (50h+) come from invested players — their friction points
  and wishlist items are more informed.
- Free-key reviews may be biased; note them but don't weight them equally.
- Early Access reviews reflect a prior state of the game; tag signals from them as [EA] when extracting.
```

---

## Change 4: Enhanced Chunk Model (Pydantic)

### analyzer_models.py — ChunkSummary

Add new fields:

```python
class BatchStats(BaseModel):
    positive_count: int = 0
    negative_count: int = 0
    avg_playtime_hours: float = 0.0
    high_playtime_count: int = 0       # Reviews with >50h played
    early_access_count: int = 0
    free_key_count: int = 0

class ChunkSummary(BaseModel):
    design_praise: list[str] = []
    gameplay_friction: list[str] = []
    wishlist_items: list[str] = []
    dropout_moments: list[str] = []
    competitor_refs: list[CompetitorRef] = []
    notable_quotes: list[str] = []
    technical_issues: list[str] = []        # NEW
    refund_signals: list[str] = []          # NEW
    community_health: list[str] = []        # NEW
    monetization_sentiment: list[str] = []  # NEW
    content_depth: list[str] = []           # NEW
    batch_stats: BatchStats = Field(default_factory=BatchStats)
```

---

## Change 5: Enhanced Synthesis Prompt (Pass 2)

### analyzer.py — _synthesize

Add the new sections to the synthesis user message. Insert these after
`"churn_triggers"` and before `"dev_priorities"`:

```
  "technical_issues": [
    "Specific technical problems: crashes, performance, bugs, compatibility. 3-6 items."
    "Format: 'Issue — severity — affected % of negative reviews'."
    "If no technical issues were reported, use an empty array."
  ],
  "refund_risk_assessment": {
    "refund_language_frequency": "none|rare|moderate|frequent",
    "primary_refund_drivers": ["1-3 reasons players cited for refunding"],
    "risk_level": "low|medium|high"
  },
  "community_health": {
    "overall": "thriving|active|declining|dead|not_applicable",
    "signals": ["2-4 specific community signals from reviews"],
    "multiplayer_population": "healthy|shrinking|critical|not_applicable"
  },
  "monetization_sentiment": {
    "overall": "fair|mixed|predatory|not_applicable",
    "signals": ["1-3 specific monetization opinions from reviews"],
    "dlc_sentiment": "positive|mixed|negative|not_applicable"
  },
  "content_depth": {
    "perceived_length": "short|medium|long|endless",
    "replayability": "low|medium|high",
    "value_perception": "poor|fair|good|excellent",
    "signals": ["2-3 specific player descriptions of content volume"]
  },
```

Update the anti-duplication rules in the system prompt to include the new
sections:
```
- 'Game crashes every 30 minutes' → technical_issues ONLY (not gameplay_friction).
- 'DLC is overpriced' → monetization_sentiment ONLY (not gameplay_friction).
- 'Dead multiplayer lobbies' → community_health ONLY (not churn_triggers).
- 'Refunded after 2 hours' → refund_risk_assessment ONLY (not churn_triggers).
```

---

## Change 6: Enhanced Report Model (Pydantic)

### analyzer_models.py — GameReport

Add new models and fields:

```python
class RefundRisk(BaseModel):
    refund_language_frequency: Literal["none", "rare", "moderate", "frequent"]
    primary_refund_drivers: list[str] = Field(default_factory=list, max_length=3)
    risk_level: Literal["low", "medium", "high"]

class CommunityHealth(BaseModel):
    overall: Literal["thriving", "active", "declining", "dead", "not_applicable"]
    signals: list[str] = Field(default_factory=list, max_length=4)
    multiplayer_population: Literal["healthy", "shrinking", "critical", "not_applicable"]

class MonetizationSentiment(BaseModel):
    overall: Literal["fair", "mixed", "predatory", "not_applicable"]
    signals: list[str] = Field(default_factory=list, max_length=3)
    dlc_sentiment: Literal["positive", "mixed", "negative", "not_applicable"]

class ContentDepth(BaseModel):
    perceived_length: Literal["short", "medium", "long", "endless"]
    replayability: Literal["low", "medium", "high"]
    value_perception: Literal["poor", "fair", "good", "excellent"]
    signals: list[str] = Field(default_factory=list, max_length=3)

class GameReport(BaseModel):
    game_name: str
    total_reviews_analyzed: int
    overall_sentiment: Literal[
        "Overwhelmingly Positive", "Very Positive", "Mostly Positive",
        "Mixed", "Mostly Negative", "Very Negative", "Overwhelmingly Negative",
    ]
    sentiment_score: float = Field(ge=0.0, le=1.0)
    sentiment_trend: Literal["improving", "stable", "declining"]
    sentiment_trend_note: str
    one_liner: str
    audience_profile: AudienceProfile
    design_strengths: list[str] = Field(min_length=2, max_length=8)       # CHANGED: min 4→2
    gameplay_friction: list[str] = Field(min_length=1, max_length=7)      # CHANGED: min 3→1
    player_wishlist: list[str] = Field(min_length=1, max_length=6)        # CHANGED: min 3→1
    churn_triggers: list[str] = Field(min_length=1, max_length=4)         # CHANGED: min 2→1
    technical_issues: list[str] = Field(default_factory=list, max_length=6)  # NEW
    refund_risk: RefundRisk                                                   # NEW
    community_health: CommunityHealth                                         # NEW
    monetization_sentiment: MonetizationSentiment                             # NEW
    content_depth: ContentDepth                                               # NEW
    dev_priorities: list[DevPriority]
    competitive_context: list[CompetitiveRef] = []
    genre_context: str
    hidden_gem_score: float = Field(ge=0.0, le=1.0, default=0.0)
    appid: int | None = None
```

**Note on min_length changes:** The original `min_length=4` for design_strengths
forced the LLM to pad weak sections with filler on games that genuinely had
fewer strengths. Lowering to 2 gives the LLM permission to be honest. Same
reasoning for friction (3→1), wishlist (3→1), churn_triggers (2→1). The LLM
will still produce more items when the data supports it.

---

## Change 7: Update max_tokens for Sonnet

The report is now larger with 5 new sections. Increase `max_tokens` in
`_synthesize()` from 3500 to **5000**.

---

## Change 8: Add Date Range to Chunk Headers

When calling `_summarize_chunk`, compute and include the date range of
reviews in that chunk:

```python
dates = [r["posted_at"][:10] for r in chunk if r.get("posted_at")]
date_range = f"({min(dates)} to {max(dates)})" if dates else "(dates unknown)"
```

Include in the user message:
```
f"Analyze this batch of {len(chunk)} Steam reviews "
f"(batch {chunk_index + 1} of {total_chunks}, {date_range}).\n\n"
```

This gives Haiku temporal context without adding complexity.

---

## Testing

### Test: Review Data Preparation

In the test for `analysis_service.py`, verify that:
- All 8 review fields are present in the dict passed to the analyzer
- Reviews are sorted by `posted_at` ascending
- Reviews with empty `body` are filtered out

```python
def test_reviews_include_all_metadata(game_repo, review_repo, ...):
    """Analyzer receives votes_helpful, posted_at, EA flag, etc."""
    # Seed game + reviews with all fields populated
    # Mock analyzer to capture the reviews arg
    # Assert reviews_for_llm[0] has keys: voted_up, review_text,
    #   playtime_hours, votes_helpful, votes_funny, posted_at,
    #   written_during_early_access, received_for_free

def test_reviews_sorted_chronologically(game_repo, review_repo, ...):
    """Reviews passed to analyzer are sorted by posted_at ascending."""
    # Seed reviews with out-of-order dates
    # Mock analyzer, capture reviews arg
    # Assert reviews_for_llm[0]["posted_at"] < reviews_for_llm[-1]["posted_at"]
```

### Test: Sentiment Trend Computation

```python
def test_sentiment_trend_improving():
    """Recent reviews more positive → 'improving'."""
    reviews = (
        [{"voted_up": i < 5, "posted_at": "2025-10-01T00:00:00"} for i in range(10)]  # 50% prior
        + [{"voted_up": True, "posted_at": "2026-02-01T00:00:00"} for _ in range(10)]  # 100% recent
    )
    trend, note = _compute_sentiment_trend(reviews)
    assert trend == "improving"

def test_sentiment_trend_declining():
    """Recent reviews less positive → 'declining'."""
    reviews = (
        [{"voted_up": True, "posted_at": "2025-10-01T00:00:00"} for _ in range(10)]
        + [{"voted_up": i < 3, "posted_at": "2026-02-01T00:00:00"} for i in range(10)]
    )
    trend, note = _compute_sentiment_trend(reviews)
    assert trend == "declining"

def test_sentiment_trend_stable():
    """Similar sentiment → 'stable'."""
    reviews = (
        [{"voted_up": True, "posted_at": "2025-10-01T00:00:00"} for _ in range(10)]
        + [{"voted_up": True, "posted_at": "2026-02-01T00:00:00"} for _ in range(10)]
    )
    trend, note = _compute_sentiment_trend(reviews)
    assert trend == "stable"

def test_sentiment_trend_insufficient_data():
    """Too few reviews → 'stable' with note about insufficient data."""
    reviews = [{"voted_up": True, "posted_at": "2026-02-01T00:00:00"} for _ in range(5)]
    trend, note = _compute_sentiment_trend(reviews)
    assert trend == "stable"
    assert "insufficient" in note.lower()
```

### Test: Pydantic Model Validation

```python
def test_chunk_summary_new_fields():
    """ChunkSummary accepts all new signal types."""
    summary = ChunkSummary(
        technical_issues=["FPS drops in large battles"],
        refund_signals=["refunded after 2 hours"],
        community_health=["Discord community is active"],
        monetization_sentiment=["DLC is overpriced"],
        content_depth=["Beat the game in 6 hours"],
    )
    assert len(summary.technical_issues) == 1

def test_game_report_new_sections():
    """GameReport includes all new structured sections."""
    report = GameReport(
        game_name="Test",
        total_reviews_analyzed=100,
        overall_sentiment="Mixed",
        sentiment_score=0.5,
        sentiment_trend="stable",
        sentiment_trend_note="Stable.",
        one_liner="A decent game.",
        audience_profile=AudienceProfile(
            ideal_player="Casual player",
            casual_friendliness="medium",
            archetypes=["Explorer", "Builder"],
            not_for=["Speedrunners", "PvP fans"],
        ),
        design_strengths=["Good art", "Solid music"],
        gameplay_friction=["Laggy UI"],
        player_wishlist=["Co-op mode"],
        churn_triggers=["Tutorial is confusing"],
        technical_issues=["Crashes on Mac"],
        refund_risk=RefundRisk(
            refund_language_frequency="rare",
            primary_refund_drivers=["crashes"],
            risk_level="low",
        ),
        community_health=CommunityHealth(
            overall="active",
            signals=["Helpful Discord"],
            multiplayer_population="not_applicable",
        ),
        monetization_sentiment=MonetizationSentiment(
            overall="fair",
            signals=["Fair price"],
            dlc_sentiment="not_applicable",
        ),
        content_depth=ContentDepth(
            perceived_length="medium",
            replayability="medium",
            value_perception="good",
            signals=["20 hours of content"],
        ),
        dev_priorities=[],
        competitive_context=[],
        genre_context="A solid entry in the genre.",
    )
    assert report.refund_risk.risk_level == "low"

def test_game_report_lowered_minimums():
    """design_strengths min_length=2 allows fewer items for honest reports."""
    # Should NOT raise validation error with only 2 strengths
    report = GameReport(
        # ... (full constructor with design_strengths=["One", "Two"])
        design_strengths=["One", "Two"],
        gameplay_friction=["One issue"],
        player_wishlist=["One wish"],
        churn_triggers=["One trigger"],
        # ... rest of required fields
    )
    assert len(report.design_strengths) == 2
```

### Test: Batch Stats Enhanced

```python
def test_batch_stats_new_fields():
    """BatchStats includes high_playtime_count, early_access_count, free_key_count."""
    stats = BatchStats(
        positive_count=30,
        negative_count=20,
        avg_playtime_hours=15.5,
        high_playtime_count=8,
        early_access_count=3,
        free_key_count=2,
    )
    assert stats.high_playtime_count == 8
    assert stats.early_access_count == 3
```

### Run all tests

```bash
poetry run pytest tests/ -v
```

All existing tests must continue to pass. The `min_length` reduction on
GameReport fields means existing test data with 4+ items will still validate.

---

## Migration Note

The `report_json` JSONB column in the database stores the full GameReport
dict. Old reports (generated before this change) will NOT have the new
sections. The frontend must handle missing keys gracefully:

```typescript
// Frontend should use optional chaining
const refundRisk = report?.refund_risk?.risk_level ?? "unknown";
const techIssues = report?.technical_issues ?? [];
```

No database migration needed — JSONB is schema-flexible. New reports will
have the new sections; old reports won't, and that's fine.

---

## Summary of All Changes

| File | Change |
|------|--------|
| `analysis_service.py` | Pass 8 review fields (was 3), sort by posted_at |
| `analyzer.py` CHUNK_SYSTEM_PROMPT | Add weighting instructions for helpful votes, playtime, free keys |
| `analyzer.py` _summarize_chunk | Format all metadata per review, include date range in chunk header |
| `analyzer.py` _synthesize | Add 5 new sections to synthesis prompt, pass computed trend, raise max_tokens to 5000 |
| `analyzer.py` new function | `_compute_sentiment_trend()` — Python-computed from timestamps |
| `analyzer.py` analyze_reviews | Call `_compute_sentiment_trend`, override LLM values |
| `analyzer_models.py` BatchStats | Add `high_playtime_count`, `early_access_count`, `free_key_count` |
| `analyzer_models.py` ChunkSummary | Add 5 new list fields |
| `analyzer_models.py` GameReport | Add 5 new sections (RefundRisk, CommunityHealth, MonetizationSentiment, ContentDepth, technical_issues), lower min_length constraints |
| Tests | Sentiment trend computation, model validation, review data preparation |
