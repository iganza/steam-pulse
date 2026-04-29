# Page Doctor: Steam Wishlist Audit

## Context

Steam developers with weak wishlist conversion need a diligent, analyst-quality
audit of their store page, not generic checklist advice. Industry research
(presskit.gg, howtomarketagame.com, Indie Game Joe) converges on the same
levers: capsule, first 3-4 screenshots, trailer hook, short description, top
5 tags, and "what it feels like" framing. 68-88% of wishlists come from
people who never play the demo, so the store page is the conversion surface,
not the demo.

steam-pulse already has the rare ingredient that off-the-shelf advice cannot
provide: review-grounded `GameReport` data with `store_page_alignment`
(promises_delivered, promises_broken, hidden_strengths, audience_match) and
tag-vote-weighted comparables via `find_related_analyzed`. This feature wraps
those existing artifacts in one new LLM call that produces a peer-anchored,
prioritized improvement report.

This is on-demand only, never scheduled.

---

## Deliverables

### 1. Pydantic schema for the audit output

New file: `src/library-layer/library_layer/page_doctor/schema.py`

```python
class Fix(BaseModel):
    title: str
    rationale: str          # cites a GameReport field or a peer appid
    peer_evidence: int | None  # peer appid this fix is anchored on
    effort: Literal["S", "M", "L"]

class CapsuleAudit(BaseModel):
    word_count_estimate: int
    readability_at_thumbnail: Literal["clear", "marginal", "illegible", "unknown"]
    contrast_against_dark_ui: Literal["high", "medium", "low", "unknown"]
    genre_signal_in_one_second: bool | None
    findings: list[str]
    peer_examples: list[int]  # peer appids whose capsules do this well

class ScreenshotsAudit(BaseModel):
    leads_with_gameplay: bool | None
    signals_genre_fantasy_emotion_in_first_four: bool | None
    findings: list[str]
    peer_examples: list[int]

class TrailerAudit(BaseModel):
    length_seconds_known: int | None
    length_in_target_window: bool | None  # 45-75s
    opens_with_gameplay: bool | None
    sound_independent: bool | None
    findings: list[str]

class ShortDescAudit(BaseModel):
    leads_with_feeling_not_mechanics: bool | None
    scannable: bool | None
    hook_clarity: Literal["strong", "weak", "missing"]
    findings: list[str]

class TagsAudit(BaseModel):
    top_five_specificity: Literal["specific", "mixed", "generic"]
    missing_tags_from_peers: list[str]
    over_generic_tags: list[str]
    findings: list[str]

class PageVsReality(BaseModel):
    promises_broken: list[str]      # from GameReport.store_page_alignment
    hidden_strengths: list[str]
    audience_mismatch: str | None
    severity: Literal["low", "medium", "high"]

class StealPattern(BaseModel):
    peer_appid: int
    peer_name: str
    pattern: str           # one specific copyable thing
    why_it_works: str

class PageDoctorReport(BaseModel):
    appid: int
    pipeline_version: str
    peer_appids: list[int]
    used_vision: bool
    verdict: str                       # one paragraph diagnosis
    top_fixes: list[Fix]               # 3 items
    capsule_audit: CapsuleAudit
    screenshots_audit: ScreenshotsAudit
    trailer_audit: TrailerAudit
    short_desc_audit: ShortDescAudit
    tags_audit: TagsAudit
    page_vs_reality: PageVsReality
    steal_these: list[StealPattern]    # one per peer
    demo_focus_note: str
```

### 2. Orchestrator

New file: `src/library-layer/library_layer/page_doctor/runner.py`

Function: `run_page_doctor(appid: int, *, with_vision: bool = False) -> PageDoctorReport`

Steps:

1. Load or run `GameReport` for `appid` (reuse `analyzer.analyze_game` if missing).
2. Load `games` row plus tags, screenshots, movies via existing repositories.
3. Pick peers via `ReportRepository.find_related_analyzed(appid, limit=15)`,
   filter to `review_count > 500` and `positive_pct > 75`, take top 5 by
   tag-overlap score.
4. For each peer: load their cached `GameReport` and `games` row.
5. Build the prompt input (JSON-serialized structured context). If
   `with_vision=True`, additionally fetch the dev's capsule and first 4
   screenshots, plus each peer's capsule, as image bytes and attach as
   image content blocks.
6. Single LLM call with the system prompt below and structured output enforced
   against `PageDoctorReport`.
7. Validate, persist via a new `page_doctor_reports` table keyed on
   `(appid, peer_set_hash, pipeline_version)`, return.

### 3. The prompt

System prompt:

```
You are a senior Steam store-page analyst. You are auditing one game's
storefront for wishlist conversion. You have:
- the game's review-derived GameReport (especially store_page_alignment),
- its store metadata (tags with vote weight, short_desc, long_desc,
  screenshots, trailer URLs, capsule URL),
- five high-performing tag-overlapping peers' equivalents,
- optionally, image content blocks for the capsule and first 4 screenshots
  of this game and peer capsules.

Produce a triage. Rules:

1. Lead with the highest-leverage fix. Order top_fixes by impact, not
   section order.
2. Every recommendation must cite either a specific review-grounded signal
   from GameReport (name the field) or a specific peer's appid as evidence.
   No floating advice.
3. If a section has no actionable finding for this game, return findings=[]
   and leave the booleans null. Do not invent a finding to fill a section.
4. Where vision input is absent, set vision-dependent booleans to null and
   keep capsule/screenshots findings limited to what URLs and metadata can
   support. Do not pretend you saw the image.
5. The verdict is one paragraph. State the diagnosis plainly. No throat-
   clearing, no preamble.
6. The page_vs_reality section is the most important: it is the only thing
   here a generic Steam-marketing blog cannot produce. Lean on
   GameReport.store_page_alignment.
7. The demo_focus_note must reflect that 68-88% of wishlists come from
   non-demo-players. If the page itself is weak, say so and tell the dev
   to fix the page before iterating on the demo.
8. Output must validate against the PageDoctorReport schema exactly.
```

User prompt template (filled by the orchestrator):

```
GAME UNDER AUDIT
appid: {{appid}}
name: {{name}}
release_date: {{release_date}}
review_count: {{review_count}}
positive_pct: {{positive_pct}}
has_demo: {{has_demo}}
price_usd: {{price_usd}}
short_description: {{short_desc}}
long_description: {{long_desc}}
top_tags (with votes): {{tags_with_votes}}
capsule_url: {{capsule_image}}
header_url: {{header_image}}
screenshot_urls (first 4): {{screenshots_first_4}}
trailer_urls: {{movies}}

GameReport (review-derived):
{{game_report_json}}

PEER SET (5 tag-overlapping high-performers)
{{for each peer}}
  appid: {{peer.appid}}, name: {{peer.name}}
  review_count: {{peer.review_count}}, positive_pct: {{peer.positive_pct}}
  short_description: {{peer.short_desc}}
  top_tags: {{peer.tags}}
  capsule_url: {{peer.capsule_image}}
  GameReport: {{peer.game_report_json}}
{{/for}}

VISION_AVAILABLE: {{with_vision}}
(If true, image blocks for the dev's capsule + first 4 screenshots and each
peer's capsule are attached.)

Produce a PageDoctorReport.
```

### 4. Persistence

New migration adds `page_doctor_reports` table mirroring `reports`:
- `appid INT NOT NULL`
- `peer_set_hash TEXT NOT NULL`
- `pipeline_version TEXT NOT NULL`
- `with_vision BOOLEAN NOT NULL`
- `report_json JSONB NOT NULL`
- `crawled_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- PRIMARY KEY `(appid, peer_set_hash, pipeline_version, with_vision)`

The `crawled_at` column follows the freshness convention for any record
sourced from external API or LLM output.

### 5. Render surface

New Jinja template: `src/lambda-functions/lambda_functions/api/templates/page_doctor.html.j2`

Mirrors `report.html.j2` patterns. Sections render in this visual order:

1. Verdict (full width, prominent)
2. Top 3 Fixes (cards with effort badges)
3. Page-vs-Reality (highlighted, this is the moat)
4. Capsule audit (with peer capsule thumbnails)
5. Screenshots audit
6. Trailer audit
7. Short description audit
8. Tags audit
9. Steal These Patterns (peer cards)
10. Demo focus note

Pro-gated sections (everything except Verdict, Top Fixes, Page-vs-Reality)
render behind an entitlement check at the template level. Free users see the
gated sections collapsed with an upsell stub.

### 6. CLI entry point

`poetry run python -m library_layer.page_doctor.runner --appid <id> [--with-vision]`

Prints rendered audit to stdout and persists to DB.

---

## Reuse, Not Reinvent

- **3-phase analyzer** at `src/library-layer/library_layer/analyzer.py`: produces the input `GameReport`. Do not duplicate.
- **`store_page_alignment`** already on `GameReport`: source of `page_vs_reality`. Do not re-prompt for this signal.
- **Peer selection** at `src/library-layer/library_layer/repositories/report_repo.py::find_related_analyzed`: tag-vote-weighted overlap with sparse-fallback. Reuse as-is.
- **Render**: copy structure from `src/lambda-functions/lambda_functions/api/templates/report.html.j2`.
- **Pydantic conventions**: every domain object is `BaseModel`; subclass discriminator fields use base type plus default; no field defaults that hide required-ness.

---

## Packaging (Free vs Pro)

- **Free**: verdict, top_fixes, page_vs_reality. The headline insight, fully grounded in review data, no vision needed. Publishable on its own.
- **Pro**: all other sections, plus `with_vision=True`. Capsule, screenshots, trailer, tags, steal-these. These sections justify their cost only when vision is on.

The single LLM call produces all sections. Gating happens at the render layer, not at the prompt layer. This keeps one prompt under maintenance, not two.

---

## Verification

1. Pick 4 ground-truth appids: the user's own game, two known low-wishlist controls, one known high-wishlist control.
2. Run `run_page_doctor(appid, with_vision=False)` and `with_vision=True` on each.
3. Schema and grounding checks:
   - Output validates against `PageDoctorReport`.
   - Every `top_fixes[i].peer_evidence` is one of the 5 selected peer appids or `None` only if `rationale` cites a `GameReport` field by name.
   - When `with_vision=False`, capsule/screenshots/trailer vision-dependent booleans are all `null`.
4. Behavior checks:
   - Low-wishlist controls yield non-empty `top_fixes` and at least one `promises_broken` or `audience_mismatch` finding.
   - High-wishlist control yields short or empty `top_fixes` and `verdict` admits the page is fine (negative test, prevents the prompt from inventing problems).
5. Render the HTML for one example and visually compare against `report.html.j2`.

---

## Out of Scope

- Wishlist count or conversion rate data. Steam does not expose these
  publicly per appid; the audit reasons about page quality, not measured
  funnel metrics. If the dev later supplies their own funnel numbers, that
  is a future enhancement.
- A/B testing of capsule variants.
- Auto-generation of new capsule art or copy. The audit advises; it does
  not produce assets.
- Localization audit. English store pages only for v1.
