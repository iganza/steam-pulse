# Game Metadata Analysis — Store Page Intelligence

## Background

The two-pass LLM analysis pipeline currently processes **only review text**. The
Pass 2 synthesis prompt receives game name, review count, pre-computed scores, and
temporal context — but none of the game's store description, pricing, tags, platform
support, or achievement data. All of this metadata is already stored in the `games`
table and `game_tags`/`game_genres` joins.

Adding game metadata to Pass 2 unlocks a category of insight that is impossible from
reviews alone: **promise vs. reality analysis**. When the LLM can read both the store
description and the aggregated review signals, it can identify:

- **Marketing/reality gaps** — features promised in the description that reviews
  consistently criticize or say are missing
- **Undersold strengths** — things reviewers love that the store page doesn't highlight
  (opportunity for better marketing copy)
- **Audience mismatch** — when the description targets one audience but reviews reveal
  a different actual player base
- **Price-aware value assessment** — "poor value" at $60 is a different signal than
  "poor value" at $5; the LLM currently has no price context
- **Platform-aware technical analysis** — distinguishing "crashes on Linux" (supported
  platform bug) from noise about unsupported platforms

This is a **Pass 2 only** change. Pass 1 chunk extraction stays review-only — game
descriptions don't need per-chunk processing. Token cost increase is ~200–500 tokens
per game on a single synthesis call; negligible.

---

## What already exists (reuse — do NOT rebuild)

All required data is already fetched, stored, and queryable. No new Steam API calls,
no new crawl logic, no new tables.

| Data                                                   | Source                 | Storage                  |
|--------------------------------------------------------|------------------------|--------------------------|
| `short_desc`, `about_the_game`, `detailed_description` | Steam API `appdetails` | `games` table            |
| `price_usd`, `is_free`                                 | Steam API `appdetails` | `games` table            |
| `platforms` (windows/mac/linux)                        | Steam API `appdetails` | `games.platforms` JSONB  |
| `deck_compatibility`                                   | Steam API `appdetails` | `games` table            |
| `achievements_total`                                   | Steam API `appdetails` | `games` table            |
| `metacritic_score`                                     | Steam API `appdetails` | `games` table            |
| Tags (with vote counts)                                | Steam API store tags   | `game_tags` join table   |
| Genres                                                 | Steam API `appdetails` | `game_genres` join table |

| Method                                      | File              | Returns                                                        |
|---------------------------------------------|-------------------|----------------------------------------------------------------|
| `GameRepository.find_by_appid(appid)`       | `game_repo.py:76` | `Game` model with all metadata fields                          |
| `TagRepository.find_tags_for_game(appid)`   | `tag_repo.py:101` | `list[dict]` — `{id, name, slug, votes}` ordered by votes DESC |
| `TagRepository.find_genres_for_game(appid)` | `tag_repo.py:114` | `list[dict]` — `{id, name, slug}`                              |

The batch PreparePass2 handler (`batch_analysis/prepare_pass2.py:126`) already loads
the game object — it just doesn't pass metadata to the synthesis prompt.

The real-time analysis handler (`lambda_functions/analysis/handler.py`) is unused and
slated for deletion per `scripts/prompts/remove-realtime-analysis.md` — do NOT add
new code there.

---

## What to build

### 1. New model: `GameMetadataContext` in `models/metadata.py`

Create `src/library-layer/library_layer/models/metadata.py`:

```python
from decimal import Decimal

from pydantic import BaseModel


class GameMetadataContext(BaseModel):
    """Game metadata injected into Pass 2 synthesis prompt."""

    short_desc: str | None = None
    about_the_game: str | None = None   # HTML-stripped; see build function
    price_usd: Decimal | None = None
    is_free: bool = False
    tags: list[str] = []                # top 10 tag names, ordered by votes
    genres: list[str] = []              # genre names
    platforms: list[str] = []           # e.g. ["Windows", "Mac", "Linux"]
    deck_status: str = "Unknown"        # "Unknown"|"Unsupported"|"Playable"|"Verified"
    achievements_total: int = 0
    metacritic_score: int | None = None
```

Module-level pure function in the same file:

#### `build_metadata_context(game: Game, tags: list[dict], genres: list[dict]) -> GameMetadataContext`

- `short_desc` — `game.short_desc` directly
- `about_the_game` — strip HTML tags from `game.about_the_game` (use `re.sub(r"<[^>]+>", "", text)`;
  no external dependency). Truncate to first 1500 chars to bound token cost.
- `tags` — `[t["name"] for t in tags[:10]]` (top 10 by votes)
- `genres` — `[g["name"] for g in genres]`
- `platforms` — build from `game.platforms` dict:
  `[k.title() for k, v in game.platforms.items() if v]`
- `deck_status` — `game.deck_status` (existing property on `Game` model)
- All other fields mapped directly from `game`

No I/O, no SQL. Takes already-fetched data.

### 2. Extend `SYNTHESIS_SYSTEM_PROMPT` in `analyzer.py`

Add new anti-duplication rules to `<anti_duplication_rules>`:

```xml
- "Store page says X but reviews disagree" → store_page_alignment ONLY (not gameplay_friction)
- "Reviewers love X but store page doesn't mention it" → store_page_alignment ONLY (not design_strengths)
```

These prompt constants survive the real-time removal (`remove-realtime-analysis.md`
explicitly keeps `SYNTHESIS_SYSTEM_PROMPT`), so this change is safe.

### 3. Extend `_build_synthesis_user_message()` in `analyzer.py`

This function also survives the real-time removal — it is imported directly by
`prepare_pass2.py` for building batch JSONL records.

#### Signature change

Add `metadata: GameMetadataContext | None = None` parameter.

#### New `<game_context>` fields

When `metadata is not None`, append after existing temporal lines:

```
  Price: ${metadata.price_usd} {"(Free)" if metadata.is_free else ""}
  Platforms: {", ".join(metadata.platforms)}
  Steam Deck: {metadata.deck_status}
  Genres: {", ".join(metadata.genres)}
  Tags: {", ".join(metadata.tags)}
  Achievements: {metadata.achievements_total}
  Metacritic: {metadata.metacritic_score or "N/A"}
```

#### New `<store_description>` block

Insert between `</game_context>` and `<aggregated_signals>`:

```xml
<store_description>
  <short>{metadata.short_desc or "Not available"}</short>
  <full>{metadata.about_the_game or "Not available"}</full>
</store_description>
```

Separate from `<game_context>` because the description is prose content (potentially
long), not structured metadata. Clear XML boundary helps the LLM treat it as a
distinct input.

#### New section in `<section_definitions>`

```xml
<section name="store_page_alignment" type="object">
  How well the store page description matches player reality.
  Compare the store description against aggregated review signals.
  ONLY include items where there is a clear match or mismatch — do not
  restate the description or list every feature.
  promises_delivered: 2-4 features/claims in the description that reviews confirm (array)
  promises_broken: 0-3 features/claims in the description that reviews contradict or say are missing (array)
  hidden_strengths: 0-3 things reviewers consistently praise that the description does NOT highlight (array)
  audience_match: "aligned"|"partial_mismatch"|"significant_mismatch"
  audience_match_note: 1-2 sentences — WHO the description targets vs WHO actually plays (string)
</section>
```

#### New self-check items

Add to `<self_check>`:

```
5. store_page_alignment claims trace to BOTH the store description AND aggregated signals
6. No store_page_alignment item duplicates a design_strengths or gameplay_friction item
```

#### Graceful degradation

When `metadata is None` or `metadata.about_the_game is None`:
- Omit `<store_description>` block entirely
- Omit `store_page_alignment` from `<section_definitions>`
- The LLM produces a report without the section; `GameReport` field is optional

### 4. New Pydantic model: `StorePageAlignment` in `analyzer_models.py`

```python
class StorePageAlignment(BaseModel):
    promises_delivered: list[str] = Field(default_factory=list, max_length=4)
    promises_broken: list[str] = Field(default_factory=list, max_length=3)
    hidden_strengths: list[str] = Field(default_factory=list, max_length=3)
    audience_match: Literal["aligned", "partial_mismatch", "significant_mismatch"]
    audience_match_note: str
```

**List field validation rule:** Never use `min_length` on list fields in models
produced by the LLM. A `min_length` violation raises a `ValidationError` — in the
batch path, `process_results.py` catches per-game exceptions (line 131) so a single
game would fail rather than the whole batch, but the failure is still unnecessary.
List cardinality guidance belongs in `<section_definitions>` as a prompt hint only.
`max_length` is safe because the LLM can always return fewer items.

Scalar required fields (`audience_match`, `audience_match_note`) are acceptable —
they are simple values the LLM is unlikely to omit, and `store_page_alignment` itself
is optional on `GameReport`, so a fully missing section is always safe.

Add to `GameReport`:

```python
store_page_alignment: StorePageAlignment | None = None
```

Optional because games without a store description skip this section, and to prevent
any `StorePageAlignment` validation failure from cascading into a full analysis failure.

### 5. Wire in the batch PreparePass2 handler

File: `src/lambda-functions/lambda_functions/batch_analysis/prepare_pass2.py`

`prepare_pass2.py` creates `game_repo` and `review_repo` as local variables inside
the handler (lines 106–107), using the module-level `_conn`. Follow the same pattern
for `TagRepository`:

```python
from library_layer.repositories.tag_repo import TagRepository
from library_layer.models.metadata import build_metadata_context

# Inside handler(), alongside existing repo instantiation:
tag_repo = TagRepository(_conn)
```

Then inside the `for appid, chunks in chunks_by_appid.items():` loop, immediately
after loading the game (line 126):

```python
tags = tag_repo.find_tags_for_game(appid)
genres = tag_repo.find_genres_for_game(appid)
metadata = build_metadata_context(game, tags, genres) if game else None
```

Pass `metadata=metadata` to `_build_synthesis_user_message()` at line 143.

**No changes to `process_results.py`** — it parses the LLM response via
`GameReport.model_validate_json(text)` (line 102). Adding an optional field
(`store_page_alignment: StorePageAlignment | None = None`) to `GameReport` is
backwards-compatible: if the LLM omits it, it defaults to `None`. If validation
of `StorePageAlignment` fails for a game, the per-game `except Exception` at
line 131 catches it, logs, and continues to the next game.

### 6. Expose in API response

No change needed. The `store_page_alignment` field is part of `report_json` (JSONB).
When the report is fetched via `GET /api/games/{appid}/report`, it comes back
automatically. Frontend reads it from the report object.

Pro-gating is handled in the frontend — same as `dev_priorities`, `churn_triggers`,
and other pro sections.

### 7. Tests

#### `tests/models/test_metadata.py` — pure function tests

**`build_metadata_context`:**
- Given a `Game` with all fields populated + tags + genres → returns correct
  `GameMetadataContext` with top-10 tags, platform list, HTML-stripped description
- Given a `Game` with `about_the_game=None` → `about_the_game` is `None`
- Given a `Game` with `about_the_game` containing HTML → HTML stripped
- Given a `Game` with `about_the_game` longer than 1500 chars → truncated
- Given a `Game` with empty `platforms` dict → empty platforms list
- Given tags list with 15 entries → only first 10 returned

#### `tests/services/test_analyzer.py` — prompt construction tests

**`_build_synthesis_user_message` with metadata:**
- When `metadata is not None` → output contains `<store_description>` block and
  `store_page_alignment` in `<section_definitions>`
- When `metadata is None` → output does NOT contain `<store_description>` or
  `store_page_alignment` section definition
- When `metadata.about_the_game is None` → `<store_description>` and
  `store_page_alignment` section definition both omitted
- Price, platforms, tags, genres, deck status, achievements, metacritic appear
  in `<game_context>` block when metadata is provided

---

## Constraints

- Pass 1 is NOT modified — chunk extraction stays review-only
- No new tables or migrations — `report_json` is JSONB, schema-flexible
- No new Steam API calls — all metadata already crawled and stored
- `GameMetadataContext` is a Pydantic `BaseModel` — never use `dataclasses`
- `build_metadata_context()` is a pure function — no DB calls, easily testable
- HTML stripping uses stdlib `re` — no new dependency
- `store_page_alignment` is optional on `GameReport` — graceful when description unavailable
- **No `min_length` on any list field** in LLM-produced models — cardinality guidance goes
  in `<section_definitions>` only; `min_length` violations cause unnecessary failures
- Anti-duplication rules prevent signal bleeding between new and existing sections
- Token budget: `about_the_game` capped at 1500 chars (~400 tokens max)
- All new code follows Repository → Service → Handler layer boundary
- Type hints required on all parameters and return types, including `-> None` (Python 3.12)
- Use `str | None` union syntax — never `Optional[str]`
- Use Powertools `Logger` with `extra={}` — never `print()` or stdlib `logging`
- Do NOT add new code to `lambda_functions/analysis/handler.py` — it is deprecated
- All tests must pass: `poetry run pytest -v`
- Lint clean: `poetry run ruff check .` and `poetry run ruff format .`

---

## Files to create / modify

| File | Action |
|---|---|
| `src/library-layer/library_layer/models/metadata.py` | Create — `GameMetadataContext` Pydantic model + `build_metadata_context()` |
| `src/library-layer/library_layer/models/analyzer_models.py` | Add `StorePageAlignment` model + optional field on `GameReport` |
| `src/library-layer/library_layer/analyzer.py` | Extend `_build_synthesis_user_message()` with `metadata` param, `<game_context>` fields, `<store_description>` block, section definition; extend `SYNTHESIS_SYSTEM_PROMPT` anti-duplication rules |
| `src/lambda-functions/lambda_functions/batch_analysis/prepare_pass2.py` | Add `TagRepository`, build metadata context, pass `metadata` to `_build_synthesis_user_message()` |
| `tests/models/test_metadata.py` | Create — pure function tests for `build_metadata_context()` |
| `tests/services/test_analyzer.py` | Add prompt construction tests for metadata injection |

No migration needed. No changes to `process_results.py` (optional field is
backwards-compatible). No frontend changes needed for data flow (frontend reads from
`report_json` JSONB). Frontend display component for `store_page_alignment` is a
separate task.
