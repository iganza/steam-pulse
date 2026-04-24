# Genre narrative-intro: rewrite for readable, structured opening

## Context

The first genre analysis is live at
`https://d1mamturmn55fm.cloudfront.net/genre/roguelike-deckbuilder`.
The opening renders as **one huge unbroken block** — ~150 words in a
single `<p>`. That's both a visual problem (a wall of text before the
reader hits the first section header) and a writing problem (no
rhythm, no hook, no distinct paragraphs doing distinct jobs).

Two compounding root causes:

1. **Prompt rule forces one paragraph.** `genre_synthesis_v1.py:56-57`:
   > `narrative_summary: one paragraph, 3-5 sentences. Headline what
   > this genre's players actually want. Plain English, no corporate
   > fluff.`

   The LLM obediently emits one paragraph with no `\n\n` breaks.

2. **Frontend only splits on explicit paragraph breaks.**
   `frontend/components/genre/EditorialIntro.tsx:34` does
   `intro.split(/\n\n+/).map(...)`. No `\n\n` in input → one `<p>`.

Both behave correctly given the inputs; the spec is what's wrong.

The writing quality problem is deeper than formatting: a good intro
should have a *hook* (the non-obvious finding), a *tribe* frame (what
this niche universally expects), and a *takeaway* (what the reader
walks away with before scrolling) — each as its own short paragraph.
Today's paragraph tries to do all three in one breath and ends up
doing none of them well.

Fix = evolve the prompt to produce a **structured, multi-paragraph
narrative with a rubric** and regenerate. Schema stays the same —
`narrative_summary: str` with `\n\n` between paragraphs. Frontend
already handles that.

## Recommended approach

**Edit `genre_synthesis_v1.py` in place** (pre-launch, single row in
`mv_genre_synthesis`, no production readers to preserve). Replace the
`narrative_summary` rule with a paragraph-level rubric + style guide +
worked example. Delete the stale row and re-run synthesis for the one
affected genre.

Why not bump to v2: the module comment documents "bump on material
prompt changes," but the `prompt_version` cache-key machinery exists
for auditability across time, not to keep dead outputs around. Only
one genre is synthesized; re-running is ~$1. Edit-in-place honors
the pre-launch "no flags / no dual paths" preference.

Why not restructure the schema into `hook / tribe / takeaway` fields:
cleaner but invasive, couples the frontend to the writing structure,
and `cross-genre-synthesizer-v1-upgrades.md` already owns that class
of schema change (gated on Stage-1 signal). This prompt is a
single-purpose writing fix, not schema evolution.

## Files to change

| File | Change |
| --- | --- |
| `src/library-layer/library_layer/prompts/genre_synthesis_v1.py` | Replace the `narrative_summary` rule (lines 56-57) with the new multi-paragraph rubric + worked example (spec below). No other file edits. |
| `mv_genre_synthesis` row for `slug='roguelike-deckbuilder'` | Delete (or let `force=True` re-synth overwrite); re-run `scripts/trigger_genre_synthesis.py` to regenerate. |

Nothing else — frontend already handles `\n\n` splits, schema
unchanged, tests untouched (synthesizer output is LLM-generated, no
unit tests for script-level behavior).

## The new prompt rule (drop-in replacement for lines 56-57)

```
- narrative_summary: 3–4 short paragraphs separated by blank lines
  (\n\n). Each paragraph does ONE specific job. Do NOT restate the
  lists below — the reader will see friction_points, wishlist_items,
  and dev_priorities rendered as sections immediately after.

  Paragraph 1 (Hook, 1–2 sentences): the single non-obvious thing
  that defines this genre's players. Lead with a concrete,
  declarative claim — NOT "Players of X enjoy Y." Start from
  tension, surprise, or a specific behavior.

  Paragraph 2 (Tribe, 2–3 sentences): what this niche universally
  expects — the "genre contract." Name at least one benchmark game
  by its actual title. Describe what a player silently assumes will
  be true on hour one.

  Paragraph 3 (Tension, 2–3 sentences): the specific place where
  successful games in the niche pull ahead of the pack. Cite
  patterns from the input reports (e.g. synergy depth, run pacing,
  meta-progression cadence). If there's a dominant friction that
  cuts across most inputs, name it here.

  Paragraph 4 (Takeaway, 1–2 sentences, OPTIONAL): the single thing
  a developer reading this should walk away with before scrolling.
  One sentence of plain-English advice. Skip this paragraph if
  paragraphs 1–3 already land the takeaway — do not pad.

  Style:
  - Short sentences. Active voice. No hedging ("arguably",
    "somewhat", "in some cases").
  - Use proper nouns, not placeholders. "Slay the Spire" not
    "a leading title." "Hour 20" not "later in the game."
  - No meta-writing. Never say "this report", "this genre", "below
    you'll find", "we analyzed N games."
  - No corporate voice, no marketing adjectives ("immersive",
    "engaging", "rich"). Write like a senior designer talking to
    another senior designer over coffee.
  - Total length: 120–200 words across all paragraphs.
```

## Worked example (append to rules block, before the "Output MUST be..." line)

```
<example genre="roguelike-deckbuilder">
Roguelike deckbuilder players stop playing when winning stops
feeling like discovery — not when they lose.

The genre contract is unusually strict. Slay the Spire set the
template: a run fits in a single sitting, card synergies are the
primary skill expression, and meta-progression persists between
deaths. Balatro extended the contract by proving the scoring
ceiling itself can be the endgame. Anyone shipping in this niche
inherits both promises on day one.

The games that pull ahead all do the same thing: they reward
discovery over execution. Players consistently cite "the first
time a build clicked" as their peak moment, and the sharpest
friction across inputs is build homogenization after ~40 hours,
when the synergy space feels fully mapped. A second axis of
friction is difficulty that spikes on luck rather than on
decisions.

For a developer shipping here: broad viable build diversity and a
difficulty curve that rewards reads over rolls are the two
investments this audience pays back.
</example>

The example is illustrative. Use the specific input reports for the
actual synthesis — never copy example phrasing into another genre.
```

## Regeneration steps (post-edit)

1. Edit `genre_synthesis_v1.py` per spec above.
2. `DELETE FROM mv_genre_synthesis WHERE slug = 'roguelike-deckbuilder';`
   (single-row pre-launch clean-up; alternatively re-run with
   `force=True` if the trigger script supports it — check
   `scripts/trigger_genre_synthesis.py` for the exact arg).
3. Re-run the trigger for `roguelike-deckbuilder` via
   `scripts/trigger_genre_synthesis.py`.
4. Wait for batch completion (~10 min based on existing monitoring).
5. Visit `/genre/roguelike-deckbuilder` on the deployed frontend to
   verify rendering.

## Verification

- `narrative_summary` in the new row contains at least two `\n\n`
  sequences (3+ paragraphs). Check with:
  `SELECT narrative_summary FROM mv_genre_synthesis WHERE slug='roguelike-deckbuilder';`
- Rendered page shows 3–4 distinct paragraphs with blank-line spacing
  (the existing `space-y-4` on the `<div>` handles this once the
  `split` produces multiple paragraphs).
- Each paragraph reads as doing its specified job. If paragraph 1
  reads like an encyclopedia lead ("Roguelike deckbuilders are games
  that combine..."), the rubric failed — tighten the rule or
  regenerate.
- Total intro word count is 120–200. Over 250 → tighten the rule;
  under 90 → loosen.
- No meta-language ("this analysis", "this report") in the output.

## Out of scope

- Schema changes to `GenreSynthesis` (split `narrative_summary` into
  `hook` / `tribe` / `takeaway` fields) — owned by the separate
  Stage-1-gated `cross-genre-synthesizer-v1-upgrades.md`.
- Frontend styling of individual paragraphs (e.g. drop cap on the
  hook, tighter leading on the takeaway) — deferrable; visible
  improvement should come from paragraph breaks + writing quality
  alone.
- Sentence-fallback splitter in `EditorialIntro.tsx` that would
  rescue poorly-formatted outputs by splitting on sentence
  boundaries. Not needed if the prompt reliably emits `\n\n`; adds
  debt otherwise.
- `editorial_intro` curator override path — stays available as the
  manual escape hatch, but the synthesizer's default should be
  publishable.

## Risk / rollback

Low risk. Single LLM call, single DB row. If the regenerated intro
reads worse than today's, revert the prompt edit and re-run
synthesis — the column is not referenced by any other computation.
