# Instructor Integration for SteamPulse Analyzer

## Goal

Replace the fragile manual JSON parsing in `analyzer.py` with
[Instructor](https://python.useinstructor.com/) + Pydantic models. This makes
LLM output **validated at generation time**, adds **automatic retry on bad
output**, and gives us a typed schema we can rely on in tests.

---

## Background: Current State

**File:** `src/lambda-functions/lambda_functions/analysis/analyzer.py`

Two-pass pipeline:
- **Pass 1 (Haiku):** 50-review chunks → `_summarize_chunk()` → JSON with 7 fields
- **Pass 2 (Sonnet):** all chunk summaries → `_synthesize()` → final report JSON with 15 fields

Current JSON parsing is fragile:
```python
raw = response.content[0].text.strip()
if raw.startswith("```"):
    raw = raw.split("```")[1]
    if raw.startswith("json"):
        raw = raw[4:]
try:
    return json.loads(raw)
except json.JSONDecodeError:
    return DEFAULT_EMPTY_STRUCTURE  # silently swallows failures
```

No validation. Any field can be missing or wrong type. Silently returns empty
data on parse failure.

---

## Important: Bedrock vs Standard Anthropic

The codebase uses `AnthropicBedrock()` (AWS Bedrock). **Instructor supports
Bedrock** via `instructor.from_anthropic()` with the `anthropic.AnthropicBedrock()`
client — the patch works the same way.

Verify: `instructor.from_anthropic(anthropic.AnthropicBedrock())` should work
with instructor >= 1.0. If there are Bedrock-specific issues, fall back to
wrapping the raw response with `instructor.process_response()`.

---

## What to Build

### 1. Add `instructor` dependency

In `pyproject.toml`, add to main dependencies:
```toml
instructor = ">=1.0.0"
```

Run `poetry lock && poetry install`.

### 2. Define Pydantic models for both passes

Create a new file:
**`src/lambda-functions/lambda_functions/analysis/models.py`**

**Pass 1 — ChunkSummary:**
```python
class CompetitorRef(BaseModel):
    game: str
    sentiment: Literal["positive", "negative", "neutral"]
    context: str

class BatchStats(BaseModel):
    positive_count: int = 0
    negative_count: int = 0
    avg_playtime_hours: float = 0.0

class ChunkSummary(BaseModel):
    design_praise: list[str] = []
    gameplay_friction: list[str] = []
    wishlist_items: list[str] = []
    dropout_moments: list[str] = []
    competitor_refs: list[CompetitorRef] = []
    notable_quotes: list[str] = []
    batch_stats: BatchStats = Field(default_factory=BatchStats)
```

**Pass 2 — GameReport:**
```python
class AudienceProfile(BaseModel):
    ideal_player: str
    casual_friendliness: Literal["low", "medium", "high"]
    archetypes: list[str] = Field(min_length=2, max_length=4)
    not_for: list[str] = Field(min_length=2, max_length=3)

class DevPriority(BaseModel):
    action: str
    why_it_matters: str
    frequency: str
    effort: Literal["low", "medium", "high"]

class CompetitiveRef(BaseModel):
    game: str
    comparison_sentiment: Literal["positive", "negative", "neutral"]
    note: str

class GameReport(BaseModel):
    game_name: str
    total_reviews_analyzed: int
    overall_sentiment: Literal[
        "Overwhelmingly Positive", "Very Positive", "Mostly Positive",
        "Mixed", "Mostly Negative", "Very Negative", "Overwhelmingly Negative"
    ]
    sentiment_score: float = Field(ge=0.0, le=1.0)
    sentiment_trend: Literal["improving", "stable", "declining"]
    sentiment_trend_note: str
    one_liner: str
    audience_profile: AudienceProfile
    design_strengths: list[str] = Field(min_length=4, max_length=8)
    gameplay_friction: list[str] = Field(min_length=3, max_length=7)
    player_wishlist: list[str] = Field(min_length=3, max_length=6)
    churn_triggers: list[str] = Field(min_length=2, max_length=4)
    dev_priorities: list[DevPriority]
    competitive_context: list[CompetitiveRef] = []
    genre_context: str
    hidden_gem_score: float = Field(ge=0.0, le=1.0, default=0.0)
    appid: int | None = None
```

### 3. Patch the Anthropic client with Instructor

In `analyzer.py`, replace `_get_client()`:
```python
import instructor

def _get_instructor_client() -> instructor.Instructor:
    return instructor.from_anthropic(anthropic.AnthropicBedrock())
```

### 4. Refactor `_summarize_chunk()` to use Instructor

Replace the `client.messages.create()` call + manual JSON parsing:
```python
client = _get_instructor_client()
summary, _ = client.messages.create_with_completion(
    model=_haiku_model(),
    max_tokens=1024,
    response_model=ChunkSummary,
    system=[{"type": "text", "text": CHUNK_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
    messages=[{"role": "user", "content": prompt}],
    max_retries=2,
)
return summary
```

The return type changes from `dict` to `ChunkSummary`. Update all call sites
accordingly. The downstream aggregation in `analyze_reviews()` accesses
`chunk.design_praise`, `chunk.batch_stats.positive_count`, etc. — update those
attribute accesses from dict `["key"]` to dot notation.

### 5. Refactor `_synthesize()` to use Instructor

Same pattern, using `GameReport` as the response model. The function should
return a `GameReport` instance. Convert to dict at the boundary (before storing
to DB) using `report.model_dump()`.

Preserve the `sentiment_score` and `hidden_gem_score` override logic:
- After Instructor returns the `GameReport`, **override** `sentiment_score` and
  `hidden_gem_score` with the Python-computed values (they are more reliable
  than LLM-computed). The current `_compute_sentiment_score()` and
  `_compute_hidden_gem_score()` functions should remain and their output wins.

### 6. Preserve prompt caching

Instructor wraps the client but passes through kwargs to `messages.create`. The
`system` list with `cache_control` should still work. Verify the cache headers
are preserved in the patched calls.

---

## Tests to Write

Create **`tests/services/test_analyzer.py`** (new file).

### Unit tests (no LLM calls — mock the Instructor client)

Mock `analyzer._get_instructor_client()` to return a mock that returns
controlled `ChunkSummary` / `GameReport` Pydantic objects.

**Pydantic model tests (no mocks needed):**
1. `test_chunk_summary_defaults` — `ChunkSummary()` has empty lists, `BatchStats` defaults to 0
2. `test_chunk_summary_rejects_invalid_sentiment` — `CompetitorRef(sentiment="unknown")` raises `ValidationError`
3. `test_game_report_rejects_sentiment_score_out_of_range` — `GameReport(sentiment_score=1.5)` raises `ValidationError`
4. `test_game_report_rejects_invalid_overall_sentiment` — non-literal value raises `ValidationError`
5. `test_game_report_enforces_list_lengths` — `design_strengths` with < 4 items raises `ValidationError`
6. `test_audience_profile_casual_friendliness_literal` — only "low"/"medium"/"high" accepted
7. `test_dev_priority_effort_literal` — only "low"/"medium"/"high" accepted

**Scoring helper tests (pure Python, no LLM):**
8. `test_compute_sentiment_score_all_positive` — 10 positive → 1.0
9. `test_compute_sentiment_score_mixed` — 5 positive, 5 negative → ~0.5
10. `test_compute_sentiment_score_empty` — no chunks → 0.0
11. `test_compute_hidden_gem_score_low_reviews` — low review count boosts score
12. `test_sentiment_label_boundaries` — test each threshold boundary (0.95→Overwhelmingly Positive, etc.)
13. `test_chunk_reviews_exact_size` — 50 reviews → 1 chunk; 51 reviews → 2 chunks
14. `test_chunk_reviews_empty` — no reviews → empty list

**Integration test with mocked Instructor client:**
15. `test_analyze_reviews_returns_dict` — mock both `_summarize_chunk` and `_synthesize`, verify `analyze_reviews()` returns a dict with all expected keys
16. `test_analyze_reviews_adds_appid` — verify `appid` is set in returned dict
17. `test_analyze_reviews_empty_reviews` — zero reviews returns valid minimal report

### Update existing tests

In `tests/repositories/test_report_repo.py`, the `_report()` fixture uses a
minimal dict. After this change, consider expanding the fixture to include all
15 fields matching `GameReport.model_dump()` — but do NOT break the existing
tests.

---

## Constraints

- Do NOT change the prompts (CHUNK_SYSTEM_PROMPT, SYNTHESIS_SYSTEM_PROMPT) — only change how responses are parsed
- Do NOT change the `analyze_reviews()` function signature — callers must not need updating
- The final output of `analyze_reviews()` must remain a `dict` (use `model_dump()`) — the DB stores JSON
- Preserve prompt caching (`cache_control: ephemeral`) on both system prompts
- Run `poetry run pytest tests/ -q` after changes — all tests must pass
- Run `poetry run mypy src/ --ignore-missing-imports` and fix any new type errors introduced
