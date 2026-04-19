# Wedge Pre-Scale Quality Gate — Automated Checker

## Context

Before committing the full analysis budget on the roguelike-deckbuilder wedge
(141 games × ~$1/game), we run Phase 1-3 on a stratified sample of ~25 games
and need deterministic quality checks to catch systemic prompt failures cheaply.
Phase 4 (cross-genre synthesis) runs once on the full wedge afterward and is
not covered here.

This is **complementary** to `scripts/prompts/prompt-eval-pipeline.md`, which
defines per-report scoring against the `GameReport` schema. This prompt targets
the sample-selection + cross-data-source consistency layer that the eval
pipeline does not currently cover.

No LLM calls in the checker — deterministic checks only, cheap to re-run.

---

## Deliverables

### 1. Stratified sample selector — `scripts/eval/select_sample.py`

- Query the roguelike-deckbuilder wedge from the games table
- Stratify across three dimensions:
  - **genre subtype** (e.g. classic deckbuilder, roguelite-deckbuilder hybrid,
    deckbuilder-shooter — use existing tag/cluster data, don't re-invent)
  - **review count tier**: niche `<100`, mid `100-5000`, hit `>5000`
  - **release status**: released, early access, unreleased
- Select 2-3 games per non-empty cell; target ~25 total
- Output: JSON list of `{appid, name, stratum_label}` to stdout, also persist
  under `scripts/eval/fixtures/sample_<wedge>_<timestamp>.json` so later
  validator runs can reference the same sample
- CLI: `poetry run python scripts/eval/select_sample.py --wedge roguelike-deckbuilder`

### 2. Cross-data-source validator — `scripts/eval/validate_cross_source.py`

Takes a sample JSON (or `--all`) and for each app_id runs these checks against
the persisted report plus the source data in the DB:

**Citation fidelity**
- Extract every quoted review snippet from the report (anything in `"..."`
  that looks like a review quote — include chunk summaries if those are
  persisted)
- For each quote, verify it appears in the `reviews` table for that `appid`,
  either verbatim or with fuzzy-match similarity ≥0.85 (rapidfuzz)
- Flag any quote that cannot be grounded

**Cross-phase entity consistency**
- Extract named entities from Phase 2 and Phase 3 outputs: competitor games,
  mechanics, features, archetypes
- Verify each named entity was introduced in Phase 1 (if Phase 1 is the
  discovery phase) — or, if entities can originate in later phases, check
  that no Phase 2/3 reference contradicts a Phase 1 claim about the same
  entity
- Flag any entity reference whose source phase we can't locate

**Steam metadata fact-check**
- Load the corresponding `games` row
- Assert report-stated developer, publisher, release date, and primary genre
  tags match the row (exact match for names; release date within ±1 day)
- Flag any mismatch

Output: one machine-readable JSON file per run under
`scripts/eval/fixtures/validation_<sample>_<timestamp>.json` plus a
Rich-formatted stdout summary grouped by check category.

### 3. Aggregate reporter

At end of a run, print which checks fail most often across the sample. A
single failing report is noise; a pattern is a prompt bug. Example:

```
Citation fidelity: 3/25 reports have ungrounded quotes
  - Most common failure: quote paraphrases review rather than copies it
Cross-phase consistency: 1/25 reports reference a competitor not in Phase 1
Metadata fact-check: 0/25 — clean
```

Also emit a JSON aggregate alongside the per-report output so we can diff
results across prompt iterations.

---

## Constraints (follow these exactly)

- Use `pydantic.BaseModel` for all domain/context objects (no dataclasses)
- Run against `steampulse_test` DB, never the live dev DB
- No git add / commit / push — the user handles VCS
- No LLM calls in the checker
- No new mocks for the DB — integration tests hit a real `steampulse_test`
- Subclass discriminator fields use base type + default (e.g.
  `SqsMessageType = "x"`), not ad-hoc `Literal["x"]`

## Out of scope

- Subjective quality ("is this insight sharp, would a publisher pay for it?")
  — that's the human rubric under `doc/human+quality_review_rubric.org`
- Per-field scoring against `GameReport` — covered in
  `scripts/prompts/prompt-eval-pipeline.md`
- Phase 4 (cross-genre synthesis) validation — separate concern; one-shot
  artifact, no sample possible

## Suggested implementation order

1. `select_sample.py` with fixture persistence
2. Citation extractor + fuzzy matcher (unit tests with a synthetic report)
3. Metadata fact-checker (trivial DB join, do this second to build momentum)
4. Cross-phase entity check (hardest — start with named-entity regex, iterate)
5. Aggregate reporter + CLI wiring
6. Run on the live sample, review failures, iterate
