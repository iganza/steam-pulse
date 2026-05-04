# Competitive Brief POC — `scripts/competitive_brief.py`

> **Status: possibly-do-later.** Pure POC to validate a future product
> feature ("if I were building a game like this, what do I need to
> know?"). No infra, no schema, no UI, just an ops script that reads
> existing data. Revisit when per-game developer briefs become a
> candidate add-on to the per-game report, or when we want to validate
> the section quality before any UI/infra work.

## Goal

A single ops script `scripts/competitive_brief.py <appid>` that prints
a competitive market analysis brief for a target Steam game, sourced
entirely from data the platform already produces:

1. **Table-stakes features** — what every successful game in the space has.
2. **Demanded features** — what players are asking for across the genre.
3. **Where current offerings fall down** — recurring friction points.

POC validates whether the output is sharp enough to be a flagship
feature (per-game report add-on or section in the gated full report)
before any UI/infra work is scoped.

## Why now / why script first

The data is already produced — `mv_genre_synthesis.synthesis` contains
`friction_points`, `wishlist_items`, and `dev_priorities` per tag, and
per-game `report_json` contains `gameplay_friction`, `player_wishlist`,
`dev_priorities`, `competitive_context`. The three buckets the user
asked about map almost 1:1.

POC matters because writing the script forces three product decisions
that would otherwise stall a UI build:

- **Anchor-tag selection.** Top-voted tag? Most-specific tag with
  synthesis? Merge of top-3? The script has to pick something and the
  output quality across sample games tells us whether the choice is
  load-bearing.
- **Genre × per-game blending.** Genre synthesis is broad; per-game
  reports for the closest competitors are narrow. How to weight and
  de-duplicate. Easier to iterate in a script than a React view.
- **No-synthesis fallback.** Many tags don't have a Phase-4 synthesis
  yet. Script either degrades to per-game-only ("limited brief") or
  refuses. Choice cascades into the SLA story if this becomes a
  surfaced feature.

Cost to build: ~80 lines, zero infra, no new dependencies.

## POC scope

### Inputs

- Positional `appid`.
- `--anchor-tag <slug>` optional override (default: auto-pick).
- `--competitor-limit N` (default 8).
- `--format text|json` (default `text` for eyeballing).

### Pipeline

1. **Resolve target game.** `GameRepository.find_by_appid` → name,
   tags, review_count. Refuse if no Phase-3 report exists.

2. **Pick anchor tag.** From `TagRepository.find_tags_for_game(appid)`,
   the most-specific tag (Sub-Genre category preferred over Genre)
   that has a `mv_genre_synthesis` row at the current
   `pipeline_version`. Fall back to top-voted tag with any synthesis.
   Print which tag was chosen and why.

3. **Pull genre synthesis.** `GenreSynthesisRepository.get_by_slug` for
   the anchor — extract `friction_points`, `wishlist_items`,
   `dev_priorities`, `benchmark_games`.

4. **Pull competitor set.** `ReportRepository.find_related_analyzed(
   appid, limit=N)`. For each: load `report_json` and pull
   `gameplay_friction`, `player_wishlist`, `dev_priorities`,
   `design_strengths`.

5. **Aggregate three buckets** (heuristic, tunable):
   - **Must-have** = genre `dev_priorities` where `frequency >= 5`
     AND the action keyword appears in `design_strengths` of ≥3
     competitor reports.
   - **Demanded** = genre `wishlist_items` sorted by `mention_count`
     desc, top 8. Cross-check against per-competitor `player_wishlist`
     and tag any item that recurs in ≥3 competitors as "validated".
   - **Falling down** = genre `friction_points` sorted by
     `mention_count` desc, top 8. For each, list which competitor
     `source_appid` cited it (already on the FrictionPoint).

6. **Print the brief.** Sectioned, citations preserved
   (`source_appid`, `representative_quote`, `mention_count`).

### Output shape (text mode)

```
COMPETITIVE BRIEF — Chop Chains (4139720)
Anchor tag: idler (Sub-Genre, synthesis at v3)
Competitors analyzed: 8

== TABLE-STAKES (must-have) ==
1. <action> — frequency 7, present in 5/8 competitor strengths
   Why it matters: <...>
   Effort: low
...

== DEMANDED FEATURES ==
1. <title> — 6 mentions, validated across 4 competitors
   "<representative_quote>" (cited from appid <X>)
   Description: <...>
...

== WHERE CURRENT OFFERINGS FALL DOWN ==
1. <title> — 5 mentions across 3 competitors
   "<representative_quote>" (appid <X>)
   Recurring in: appids <X>, <Y>, <Z>
...
```

### Test sample

Run on at least 4 games spanning genres + synthesis-availability:

- `4139720` (Chop Chains) — incremental/idle space, narrow.
- A roguelike-deckbuilder wedge game — known synthesis quality.
- A game whose top tag has NO synthesis — exercises the fallback.
- A high-traffic mainstream game — checks that the brief stays sharp
  (or surfaces that mainstream genres produce mush).

For each, eyeball: is the output genuinely useful to a developer? Or
is it a re-skin of the genre synthesis that adds nothing per-game?

## Decisions to surface from the POC

These are deliberately NOT pre-decided — the POC's job is to inform them:

- **Anchor strategy.** Auto-pick vs user-required. If auto-pick output
  is great on 3/4 sample games, ship that. If brittle, require
  explicit `--anchor-tag`.
- **No-synthesis behavior.** Refuse, degrade gracefully, or trigger
  on-demand synthesis (~$1.30, async, minutes of latency).
- **Where the brief lives.** Whether the brief's signal lives mostly
  in the genre synthesis already (in which case the script is just an
  inventory tool) or whether per-game blending materially sharpens it
  (in which case it deserves to surface as part of the per-game
  report).

## Out of scope (POC)

- Site UI integration / per-game page tab.
- Caching the brief output anywhere persistent.
- Triggering Phase-4 synthesis on demand from the script.
- Any gating logic.
- New schema, matviews, or batch jobs.
- Anything that costs LLM tokens — POC reads existing artifacts only.

## Files (POC)

- `scripts/competitive_brief.py` (new). Standalone, follows
  `scripts/sp.py` import-side-effect rules (no `from sp import ...` —
  inline DB connection helper).

No tests for the POC script — operator-only tooling per the
no-script-tests convention.

## Verification

- Run on the 4 sample appids above.
- Manually score each brief on (1) usefulness to a dev, (2) signal
  density vs the source genre synthesis alone, (3) friction-point
  citation accuracy (spot-check 3 quotes per run against
  `representative_quote` in `report_json`).
- Decision: promote to a tracked feature prompt OR park indefinitely
  with notes on why the output didn't earn its keep.
