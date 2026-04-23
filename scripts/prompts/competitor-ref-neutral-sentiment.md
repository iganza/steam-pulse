# Competitor-ref neutral sentiment (widen the enum)

## Context

The previous fix
(`scripts/prompts/completed/chunk-phase-validation-hardening.md`,
merged as `762640c`) stopped `neutral` leaking into
`TopicSignal.sentiment`, but we're still seeing chunk-phase
validation failures on a *different* field:

```
1 validation error for RichChunkSummary
competitor_refs.2.sentiment
  Input should be 'positive', 'negative' or 'mixed'
  [type=literal_error, input_value='neutral', input_type=str]
```

The failing field is `CompetitorRef.sentiment`
(`src/library-layer/library_layer/models/analyzer_models.py:39`) —
used by `RichChunkSummary.competitor_refs` and
`MergedSummary.competitor_refs`. This is a different class from
`CompetitiveRef.comparison_sentiment`
(`analyzer_models.py:201`), which is used later by
`GameReport.competitive_context`.

The last prompt's "never emit neutral" rule in `CHUNK_SYSTEM_PROMPT_V2`
(`analyzer.py:356-358`) is scoped to **topics**:

> sentiment values are strictly "positive", "negative", or "mixed".
> Do NOT emit "neutral". **If a topic has no clear valence** (descriptive
> mentions only), OMIT it — do not pad the list with low-signal topics.

And the user-message output-format block
(`analyzer.py:458-474`) spells the enum out only for the `topics:`
section. For `competitor_refs` it says `array of {game, sentiment,
context}` with no enum and no "never neutral" clause. The model
correctly follows the instructions it was given; it emits `neutral`
on competitor_refs because the prompt never fenced that field off.

## Why option A (further prompt restriction) is the wrong fix

"Neutral" means different things on different fields:

- **Topic sentiment:** a topic with no valence is descriptive noise.
  Dropping neutral topics is correct — what's left after removal IS
  the signal.
- **Competitor-ref sentiment:** a reviewer saying *"it's like Hades"*
  with no positional valence IS the signal. It identifies the
  competitive set. Coercing to `mixed` is a category error (mixed ==
  ambivalent, not un-valent). Forcing to `positive`/`negative` is a
  lie. Dropping the ref loses real market-positioning data the rest
  of the pipeline wants.

So restricting the prompt further creates semantic debt — it keeps
the schema artificially narrow and forces the model to either lie
or drop signal. The schema should match the actual semantic space
of the field.

## What to do

### 1. Widen `CompetitorRef.sentiment`

In `src/library-layer/library_layer/models/analyzer_models.py:39`:

```python
class CompetitorRef(BaseModel):
    game: str
    sentiment: Literal["positive", "negative", "mixed", "neutral"]
    context: str
```

### 2. Widen `CompetitiveRef.comparison_sentiment`

In `src/library-layer/library_layer/models/analyzer_models.py:201`:

```python
class CompetitiveRef(BaseModel):
    game: str
    comparison_sentiment: Literal["positive", "negative", "mixed", "neutral"]
    note: str
```

This must be widened in lockstep. `competitor_refs` flows from
chunk → merge → synthesis; `CompetitiveRef` is the synthesis-phase
output class. If we widen only `CompetitorRef`, the synthesis model
would have to coerce the neutral signal back into one of three
values, which is exactly the information loss we're avoiding.

### 3. Update the chunk prompt — `CHUNK_SYSTEM_PROMPT_V2`

In `src/library-layer/library_layer/analyzer.py` (string beginning
at line 336):

**In `<rules>`:** the existing topic-sentiment rule stays as-is
(it's correct for topics). Add a new rule immediately after it
that explicitly covers competitor_refs:

```
- competitor_refs.sentiment uses "positive", "negative", "mixed",
  or "neutral". Use "neutral" when the reviewer names a comparable
  game WITHOUT taking a side (e.g. "it's like Hades", "reminds me
  of Hollow Knight") — this identifies the competitive set without
  a valence claim. Use "positive"/"negative" when the reviewer
  explicitly favors one game over the other. Use "mixed" when the
  reviewer compares on both dimensions (better at X, worse at Y).
```

**In the user-message output-format block**
(`_build_chunk_user_message_v2` at `analyzer.py:447-475`): expand
the competitor_refs line to spell the enum out, symmetric with how
topic sentiment is spelled out:

```
  competitor_refs: array of {{
    game,
    sentiment ("positive" | "negative" | "mixed" | "neutral" —
               use "neutral" for pure competitive-set identification
               with no valence claim),
    context
  }}
```

### 4. Update the synthesis prompt — `comparison_sentiment`

In `src/library-layer/library_layer/analyzer.py:288`:

```
    Each: {{game, comparison_sentiment: positive|negative|mixed|neutral, note}}
```

Add the same one-line guidance in the synthesis-rules block (near
the other `competitive_context` rules) so the synthesis model
knows `neutral` is for pure competitive-set identification, same
semantics as in chunk phase.

### 5. Do NOT bump `CHUNK_PROMPT_VERSION` or `SYNTHESIS_PROMPT_VERSION`

Leave `CHUNK_PROMPT_VERSION = "chunk-v2.0"` and
`SYNTHESIS_PROMPT_VERSION = "synthesis-v3.0"` untouched
(`analyzer.py:330, 332`). Same reasoning as the previous prompt:

- Successful games: untouched. Their cached chunks/reports under
  the current versions are valid — the change is strictly
  additive (new allowed enum value), so existing records continue
  to parse cleanly.
- Failed games: `chunk_repo.find_by_appid` finds the partial chunk
  set; re-trigger fills in DB-missing chunks with the new prompt.
- New games: pick up the new prompt text naturally.

Trade-off we're accepting (same as last time): downstream merge for
a re-run failed game mixes chunks produced by old-prompt-text and
new-prompt-text at the same version label. That's fine because the
schema change is *additive* — every chunk validates under the new
schema whether it was produced before or after the prompt update.

## Verification

1. **Unit tests + lint.**
   ```
   poetry run pytest -v tests/
   poetry run ruff check .
   ```
   No existing test should break — adding an enum value is
   additive. If a test asserts the enum is *exactly* three values
   (e.g. schema snapshot), update it.

2. **Legacy `"neutral"` values DO exist in production** — confirmed
   for the 5 current-batch failed appids, e.g.:
   ```
   SELECT appid, COUNT(*) AS chunks_persisted,
          SUM(CASE WHEN summary_json::text ~ '"sentiment"\s*:\s*"neutral"'
                   THEN 1 ELSE 0 END) AS chunks_with_neutral
   FROM chunk_summaries
   WHERE appid IN (2742830, 2289750, 2501600, 1108370, 456670)
   GROUP BY appid;
   ```
   returns 5-13 neutral rows per appid. These were persisted before
   `762640c` (chunk-phase-validation-hardening, which removed
   `neutral` from the `CompetitorRef.sentiment` Literal) and remain
   tagged with the SAME `chunk-v2.0` prompt version.

   The merge phase at `analyzer.py:953` calls
   `RichChunkSummary.model_validate(row["summary_json"])` on these
   rows — which is the *actual* source of the
   `competitor_refs.N.sentiment` ValidationError we're seeing in
   production. It's not a fresh-LLM response failing; it's the
   re-hydration of legacy data failing after the schema got
   tightened.

   This strengthens the case for widening (option B) and rules out
   further restriction (option A, which would have required
   a DB cleanup migration). The fix here is strictly additive and
   retroactively makes those legacy rows parseable again, without
   any migration.

3. **Realtime single-game smoke.** Pick one of the failing appids
   from the current batch and run a single-game realtime analysis
   locally. Confirm (a) validation passes, (b) the output JSON
   contains at least one `"sentiment": "neutral"` on a
   `competitor_refs` entry if the reviews contain pure competitive
   references.

4. **Production re-trigger.** After the user deploys, re-trigger
   the same appids that failed with the
   `competitor_refs.N.sentiment` error via
   `scripts/trigger_batch_analysis.py --env production --appids
   ...`. All should complete. Check
   `/steampulse/production/batch-collect-phase` in CloudWatch —
   zero `batch_record_validation_error` entries on the enum.

5. **UI spot-check.** Competitor refs render in the synthesized
   GameReport; verify the HTML report template renders a
   `neutral`-sentiment competitor ref without visual breakage.
   Grep for `sentiment-neutral` / `comparison_sentiment` in
   `src/lambda-functions/lambda_functions/api/templates/` — if a
   CSS class is missing, add a muted-gray variant so neutral refs
   don't fall back to unstyled.

## Rollout

- Single deploy. The change is strictly additive on the schema so
  there are no migration concerns. Cached chunks and reports
  remain valid; no prompt version bump.
- The user runs `bash scripts/deploy.sh` — do not deploy from
  Claude.
- After deploy, the user re-triggers the failed games from the
  current batch.

## Out of scope

- Further prompt-level fencing of other enums (e.g. `dlc_sentiment`,
  `sentiment_trend`). `dlc_sentiment` already has
  `not_applicable`; `sentiment_trend` has
  `improving|stable|declining` with no natural "neutral" analog.
  Revisit only if those surface as real production validation
  failures.
- Soft chunk-failure threshold in `collect_phase.py` and inline
  realtime retry of failed batch records — still separate levers,
  still orthogonal to the root-cause enum fix, still out of scope.
- Refactoring `CompetitorRef` vs `CompetitiveRef` into a single
  class. They diverged for a reason (different nesting, different
  field names), and unifying them is a bigger refactor that should
  not ride in on this fix.
