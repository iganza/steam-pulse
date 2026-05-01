# Reddit Drafter — include up to 3 positive findings

## Context

`scripts/reddit_drafter_v1.py` produced `reports/reddit_drafts/3265700_20260501T025113Z.md` (Vampire Crawlers, 98% positive). All findings came back negative even though the report has rich `design_strengths` / `hidden_strengths` data. The hand-edit kept all five negative because there was no positive coverage to work with — the prompt biased the model to negative-only.

A previous tuning round (now reverted) tried to fix this with a conditional mix rule plus restructuring (lede-as-first-line, personal-hook placeholder, TLDR inline, no Limitations paragraph, etc.). The mix rule was ignored by the model and the structural changes weren't load-bearing — the operator hand-edits the structure regardless. The v1 wording produced a tighter draft.

## Change

One line added to `<grounding_rules>` in `SYSTEM_PROMPT` at `scripts/reddit_drafter_v1.py:73`:

> Include up to 3 positive findings drawn from `design_strengths`, `hidden_strengths`, `audience_profile` praise drivers, or `store_page_alignment.hidden_strengths`. Mix them with friction or churn findings; do not stack all positives or all negatives.

Everything else reverts to the v1 wording (`scripts/prompts/completed/reddit-drafter-v1.md`):
- Body structure: hook → methodology → 3-5 findings (bold claim, evidence, what-it-means line) → limitations paragraph → soft CTA. No lede line, no personal-hook placeholder, no inline TLDR.
- Limitations paragraph mandatory, 2-3 honest limits.
- Findings keep the "what-it-means" line.
- TLDR stays a separate field; the operator positions it.

## Why revert the rest

- The lede-as-first-line and personal-hook placeholder are operator-level edits. The prompt's job is the structured draft; the operator restructures.
- The conditional mix rule (`if positive_pct ≥ 80 OR …`) was too long for the model to honor reliably. A single short permissive rule ("up to 3 positive") is enough; the model uses positive material when it's there.
- Removing the Limitations paragraph and "what-it-means" lines made the draft tighter but the operator already trims those by hand.

## Files to change

- `scripts/reddit_drafter_v1.py:73` — `SYSTEM_PROMPT` constant (revert + add the positive-findings rule).

No schema changes. No DB changes. No new dependencies.

## Verification

1. Re-run on Vampire Crawlers: `poetry run python scripts/reddit_drafter_v1.py --appid 3265700`. Expect at least 1-2 positive findings drawn from the report's strengths (Yoko Shimomura soundtrack, free demo / save carryover, accessibility, the 98% positive itself, viral launch arc) mixed in with the negative ones, instead of an all-negative finding list.
2. Re-run on a game in the 60-75% range to confirm the rule is permissive ("up to 3") not mandatory — fewer positives are fine when the report's strengths section is thin.
3. Spot-check: no em-dashes, no banned words, no invented stats, mention counts match the source report.
