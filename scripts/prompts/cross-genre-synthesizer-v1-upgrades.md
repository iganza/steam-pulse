# Cross-genre synthesizer — v1 upgrades (post-Stage-1 signal)

> **DO NOT IMPLEMENT until the Stage-1 exit gate in `steam-pulse.org`
> has fired** (50 waitlist signups, 5 meaningful conversations with
> wedge-niche devs, ≥ 2 user-driven changes shipped, no broken flows).
>
> If the wedge is killed at Stage 0 or Stage 1, **delete this file** —
> none of it is worth building without signal.
>
> Pairs with `cross-genre-synthesizer-matview.md` (the v0 spec). These
> are strictly additive upgrades to v0, gated on real evidence that
> the synthesis lands with real devs.

## Why this file exists

The v0 spec is intentionally minimal — enough to produce the first
`/genre/roguelike-deckbuilder/insights` demo and show it to 5 indie
RDB devs on Discord. If their reaction is "oh damn, send me that
link," we have signal to justify investing in v1. If their reaction
is "huh, neat," no amount of the below would have saved it.

This file captures the audit findings from 2026-04-17, which were
briefly folded into v0 and then (correctly) reverted. Research
sources behind the findings:

- Repo audit: `library_layer/analyzer.py` phase-1/2/3 prompts,
  `GameReport` schema in `library_layer/models/analyzer_models.py`,
  `BaseRepository` / matview patterns, `doc/prompt-strategy.org`,
  `doc/top-100-questions.org`, `doc/strategic-questions.org`.
- Anthropic 2026 guidance: prompt caching, extended thinking, strict
  tool_use, long-context document ordering (`arxiv.org/abs/2307.03172`
  and follow-ups), evaluation tool.
- Industry / academic: Chris Zukowski (HTMAG), Deconstructor of Fun
  analytics masterclass, ABSA literature on Steam reviews (Strååt &
  Verhagen; IEEE 2021), WikiAsp / ACLSum, ConQual + GRADE for
  qualitative-synthesis confidence.
- Competitor teardown: Datahumble, Steam Sentimeter, HowlRound,
  SteamReview AI.

---

## A. Schema upgrades

### A1. Add `shared_strengths` (highest-value single addition)

v0 surfaces only friction and wishlist. Every competitor also surfaces
praise, and marketers need it more than friction for positioning.

**Shape** — mirror of `FrictionPoint`:

```python
class Strength(BaseModel):
    title: str
    description: str
    representative_quote: str
    source_appid: int
    mention_count: int
```

Add to `GenreSynthesis`:
`shared_strengths: list[Strength]  # 10 for free / 20 for Pro`

Add a prompt rule: a signal is either a Strength, a FrictionPoint, a
WishlistItem, or a MonetizationSignal — never two. Discriminator is
valence + intent. See anti-duplication matrix below (A9).

**Cost:** 0 schema cost; same LLM call.

### A2. Upgrade `representative_quote` → `Evidence` block

v0's `representative_quote + source_appid + mention_count` is thin.
ConQual/GRADE patterns suggest structured evidence with sourcing
diversity.

```python
class SourceSignal(BaseModel):
    text: str           # verbatim substring of source report JSON
    source_appid: int

class Confidence(StrEnum):
    LOW    = "low"       # corpus_fraction < 0.05
    MEDIUM = "medium"    # 0.05 <= corpus_fraction < 0.15
    HIGH   = "high"      # corpus_fraction >= 0.15

class Evidence(BaseModel):
    game_count: int              # distinct appids mentioning this
    mention_count: int           # total per-report mentions
    corpus_fraction: float       # game_count / input_count
    confidence: Confidence       # derived from corpus_fraction
    signals: list[SourceSignal]  # 3-5 from DISTINCT source_appids
```

Every insight type (FrictionPoint, WishlistItem, Strength,
DevPriority, DropoutBucket, MonetizationSignal) carries `evidence:
Evidence` instead of the scalar fields.

**Why this matters:** an insight backed by 50/141 games is
structurally different from one backed by 3/141. The frontend can
hide low-confidence items; Pro filter UI can surface only
`confidence >= HIGH`.

### A3. Add `aspect: Aspect` enum to every insight

ABSA research converges on a stable aspect taxonomy. Required on
FrictionPoint, WishlistItem, Strength, DevPriority, AspectMomentum.

```python
class Aspect(StrEnum):
    GAMEPLAY    = "gameplay"
    ART         = "art"
    AUDIO       = "audio"
    NARRATIVE   = "narrative"
    PERFORMANCE = "performance"
    PRICE       = "price"
    COMMUNITY   = "community"
    ONBOARDING  = "onboarding"
    ENDGAME     = "endgame"
    IMMERSION   = "immersion"
```

Enables:
- Filter UI ("show me only performance friction in this genre")
- Cross-genre comparison at the aspect level
- Aggregation queries ("top 5 onboarding complaints across all
  roguelike-adjacent genres")

### A4. Add `AudienceProfile` (marketing gold)

Aggregate of the per-game `audience_profile` across the corpus.

```python
class AudienceProfile(BaseModel):
    who_its_for: list[str]            # <=3 crisp descriptors
    who_its_not_for: list[str]        # <=3 anti-personas
    tonal_descriptors: list[str]      # "meditative roguelike"
    comparable_steam_tags: list[str]  # for ad targeting
```

Single most valuable field for the marketing-persona reader. Drives
positioning copy, ad keyword strategy, "for fans of X" store-page
language.

### A5. Add `MonetizationSignal[]` bucket

Steam reviews frequently comment on price/DLC/EA. Burying these in
FrictionPoint loses the signal. Break out:

```python
class MonetizationDimension(StrEnum):
    PRICE_TO_CONTENT      = "price_to_content"
    DLC_FAIRNESS          = "dlc_fairness"
    EA_DELIVERY           = "ea_delivery"
    CONTENT_CADENCE       = "content_cadence"
    MONETIZATION_PRESSURE = "monetization_pressure"

class MonetizationSignal(BaseModel):
    dimension: MonetizationDimension
    sentiment: Sentiment  # positive / negative / mixed
    description: str
    evidence: Evidence
```

Gated count: 3-8 per synthesis. Empty list if the genre has no
meaningful monetization discourse (rare).

### A6. Replace scalar churn with a curve

v0's `typical_dropout_hour: float` loses shape — drop-off at 1h +
drop-off at 20h are different failure modes that scalar collapses.

```python
class DropoutBucket(BaseModel):
    hour_bucket: str         # "0-1h" | "1-5h" | "5-20h" | "20h+"
    corpus_fraction: float
    primary_reason: str
    evidence: Evidence

class ChurnInsight(BaseModel):
    dropout_curve: list[DropoutBucket]  # 2-4 non-overlapping buckets
    overall_summary: str                # one-sentence gloss
```

### A7. Add `genre_contract: list[str]`

Zukowski's "what the tribe expects" — the implicit promises every
successful game in the niche keeps. 3-7 short declarative strings.
Example for RDB: "Runs reset; meta-progression persists", "Card
synergy is the primary skill expression", "A run fits in a session".

High-value for devs evaluating "is my game in-genre enough to get
the niche audience on day one."

### A8. Add `momentum: list[AspectMomentum]`

Per-aspect directional trend across the corpus. Derived from
distribution of input reports' `sentiment_trend` values weighted by
which aspect dominates each report.

```python
class AspectMomentum(BaseModel):
    aspect: Aspect
    trend: Trend    # improving / stable / degrading
    description: str
```

Valuable for investors and publishers evaluating timing. "Genre
performance sentiment has been degrading for 18 months" is a
thesis-level signal.

### A9. Expand `BenchmarkGame` with `what_to_steal`

v0 has `why_benchmark` only (positioning). Split into:
- `why_benchmark: str` — positioning ("Defines modern deckbuilder pacing")
- `what_to_steal: str` — design lesson ("Per-turn energy clock + card draft loop")
- `mention_count: int` — how many input reports referenced this game

Serves two distinct readers (marketer vs dev) from the same list.

### A10. Anti-duplication matrix (prompt rule)

With Strength added, the prompt must prevent signal double-counting:

| Example signal                          | Section              | Discriminator     |
|----------------------------------------|----------------------|-------------------|
| "Card variety is excellent"             | shared_strengths     | positive          |
| "Card pool too small"                   | friction_points      | negative          |
| "Please add more card variety"          | wishlist_items       | unmet demand      |
| "DLC too expensive for content"         | monetization_signals | price dimension   |
| "Frame drops on Steam Deck Act 3"       | friction_points      | performance       |

Rule: a signal appears in exactly one of {shared_strengths,
friction_points, wishlist_items, monetization_signals}. `dev_priorities`
is allowed to restate a friction as an action — that overlap is
intentional.

---

## B. LLM API improvements

### B1. Extended thinking (10k budget)

Cross-doc pattern recognition across 141 inputs benefits materially.
Budget 10k tokens. Diminishing returns above 15k per Anthropic docs.

```python
messages.create(
    model="claude-sonnet-4-6",
    thinking={"type": "enabled", "budget_tokens": 10000},
    ...
)
```

Cost: +~$0.15 per synthesis. Enables better adherence to the
aggregation and self-check rules.

### B2. Prompt caching via `cache_control`

Mark end of system prompt with `{"type": "ephemeral"}`. Weekly cadence
has limited cache value, but during prompt-iteration debug runs the
1h TTL is meaningful ($2.10 → $0.50 per debug call).

```python
system=[{
    "type": "text",
    "text": GENRE_SYNTHESIS_SYSTEM_PROMPT,
    "cache_control": {"type": "ephemeral"},
}]
```

Log `usage.cache_creation_input_tokens` and
`usage.cache_read_input_tokens` via Powertools.

### B3. Strict tool_use + larger max_tokens

```python
tools=[{"name": "emit_synthesis", "input_schema": ..., "strict": True}]
tool_choice={"type": "tool", "name": "emit_synthesis"}
max_tokens=16000  # full v1 schema can land 8-10k output; headroom matters
```

### B4. Inverted-V ordering + XML document delimiters

At 420k input tokens across 141 docs, lost-in-the-middle degradation
is real (8-12% accuracy loss per research). Mitigation:

1. Order reports inverted-V: top-5 by review_count at head, middle
   reports in review_count DESC, top-5 repeated at tail.
2. Wrap each report in `<game appid="..." name="..." review_count="...">
   {json_dump}</game>`. XML delimiters + attribute metadata
   outperform concatenated JSON (Anthropic guidance).

Defer until there's measurable quality pressure on v0 output. Cheap
to add when needed.

---

## C. Validation & safety

### C1. Quote-fidelity framing (the honest correction)

**v0 has a subtle bug in framing, not code.** `representative_quote`
suggests a player quote, but `GameReport` fields are narrative strings
from Phase-3 synthesis — they do not contain raw player reviews.
Phase-4 quotes are actually verbatim substrings of the input report
JSON dump.

Three options at v1 time:

(a) **Rename + relabel.** `SourceSignal.text` replaces
`representative_quote`; frontend reads "signal from N reports"
instead of "player quote." Cheapest, preserves honesty. **Preferred.**

(b) **Inject real Phase-1 quotes.** Pull 2-3 `ReviewQuote` objects per
game from Phase-1 `RichChunkSummary` rows, include alongside the
GameReport in the Phase-4 prompt. Output can cite actual player
voices. Cost: ~+120k input tokens / +$0.60 per synthesis. Worth it
only if "signal from N reports" reads thin to users in post-Stage-1
feedback.

(c) **Status quo.** Keep v0 framing but accept the dishonesty and
document it loudly. Don't do this; frontend messaging gets confused.

### C2. Programmatic quote-fidelity validator

Hard gate before upsert. Substring match every
`SourceSignal.text` against the named source report's
`model_dump_json()`.

```python
def _validate_signal_fidelity(
    synthesis: GenreSynthesis,
    source_reports_by_appid: dict[int, GameReport],
) -> None:
    source_dumps = {
        appid: r.model_dump_json() for appid, r in source_reports_by_appid.items()
    }
    violations = []
    for insight_list in _iter_insights_with_evidence(synthesis):
        for insight in insight_list:
            for signal in insight.evidence.signals:
                if signal.text not in source_dumps.get(signal.source_appid, ""):
                    violations.append(
                        f"{type(insight).__name__}({insight.title!r}) signal "
                        f"from appid={signal.source_appid} not verbatim"
                    )
    if violations:
        raise QuoteFidelityError(violations)
```

On violation: CloudWatch metric, DLQ, no upsert. A human inspects.

### C3. Structural validators (before upsert)

- Every `evidence.corpus_fraction` matches `game_count / input_count`
  to 3 decimals.
- Every `aspect` is in the `Aspect` enum (pydantic enforces but
  double-check).
- No signal text appears across two of {shared_strengths,
  friction_points, wishlist_items, monetization_signals}.
- Every `source_appid` is in `input_appids`.
- Each insight has ≥3 signals from distinct `source_appid`s.
- Diversity alarm: if >60% of an insight list's signals come from the
  same game, flag as likely ordering-bias artifact.

---

## D. Eval / regression detection

### D1. Golden-set eval (CI-gated on `prompt_version` bumps)

`tests/data/genre_synthesis_golden/` with 3 curated genres
(roguelike-deckbuilder, survival-crafting, visual-novel) at ~20 pinned
GameReport JSONs each. Each fixture includes a reference
`GenreSynthesis` output (hand-edited, checked into git) and a rubric.

`poetry run pytest tests/eval/test_genre_synthesis.py` on every
`GENRE_SYNTHESIS_PROMPT_VERSION` bump:
- All structural validators pass (hard gate).
- friction / strength / wishlist title Jaccard vs golden ≥ 0.5.
- benchmark_games appid set ≥ 3/5 overlap with golden.
- narrative_summary ≤150 words and doesn't restate list content
  (n-gram overlap check).

Pass rate ≥ 80% across fixtures. Drop > 15% blocks deploy.

### D2. LLM-as-judge (monthly, not per-run)

`scripts/eval/llm_judge_genre_synthesis.py` runs a Sonnet judge over
the latest synthesis for all live genres. Scores: specificity (no
corporate speak), actionability (a dev could act on `dev_priorities`),
surprise (`narrative_summary` leads with non-obvious finding). Not a
deploy gate — a product-quality tracker.

---

## E. Cost delta

| Item                       | v0      | v1 full | Delta       |
|----------------------------|---------|---------|-------------|
| Input tokens (141 reports) | ~420k   | ~420k   | 0           |
| Extended thinking          | off     | 10k     | +$0.15      |
| Cache (cold)               | off     | enabled | 0 (cold)    |
| Cache (debug iter)         | off     | enabled | -$1.60      |
| Raw-quote injection (C1b)  | off     | off†    | +$0.60 if on|
| Output (v1 larger schema)  | ~3k     | ~8-10k  | +$0.10      |
| **Total per cold synth**   | ~$1.30  | ~$2.60  | +$1.30      |

† Option C1b off by default; only enable if the "signal from N reports"
framing reads thin.

Weekly cadence, one genre: ~$10/month. Five genres: ~$50/month.
Still well inside the $500 LLM budget.

---

## F. Sequencing if Stage-1 fires

Not all of the above should ship at once. Suggested order:

1. **A1** (`shared_strengths`) — biggest single UX lift. One day.
2. **C1a** (rename to `SourceSignal.text`, frontend relabel) + **C2**
   (validator) — honesty + safety. One day.
3. **A3** (`aspect` enum on every insight) — unlocks filter UI. Two
   days including frontend.
4. **A4** (`AudienceProfile`) + **A9** (`what_to_steal`) — marketer /
   dev readability. One day.
5. **A2** (`Evidence` block) — refactor touch. Three days including
   migration of historical rows.
6. **B1** (extended thinking) + **B2** (caching) + **B3** (strict
   tool_use + max_tokens) — LLM config. One day.
7. **A5** (`MonetizationSignal`) + **A6** (`dropout_curve`) + **A7**
   (`genre_contract`) + **A8** (`momentum`) — schema breadth. Two
   days total.
8. **D1** (golden evals) — regression guardrail. Two days of fixture
   curation.
9. **B4** (inverted-V + XML) — only if lost-in-the-middle manifests.

Expect ~2 weeks of focused engineering for the full v1 upgrade.

---

## G. If the wedge is killed

Delete this file. Do not let it become aspirational background noise.
