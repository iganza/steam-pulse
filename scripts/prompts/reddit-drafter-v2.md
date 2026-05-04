# Reddit Drafter v2: deterministic skeleton from GameReport

## Context

`scripts/reddit_drafter_v1.py` was built around a 200-line system prompt that
shipped the entire `GameReport` plus a 55-review pool to Claude and asked the
LLM to write the whole post. In practice the operator hand-edited every output
heavily (see `reports/reddit_drafts/Vampire_Crawlers_final.md`, which is the
canonical "what we actually post" reference). The structural work — picking
findings, parsing mention counts, ordering positives and negatives, attaching
the limitations and CTA boilerplate — is mechanical and deterministic. The
LLM was being paid to assemble fields the report already contains.

v2 strips the LLM out. Pull the report JSON from prod, run deterministic
selection rules over it, render a Reddit markdown skeleton, attach the review
pool as a quote-picker appendix. The operator finishes voice and quotes by
hand. No prompt, no batch, no Anthropic call.

## Approach

Rewrite `scripts/reddit_drafter_v1.py` in place (keep filename, drop the LLM).

### Field selection rules

All rules read from `report_json` (validated as `library_layer.models.analyzer_models.GameReport`) plus the joined `games` row (`name`, `appid`, `review_count`, `positive_pct`, `genres`).

**Title candidates (3, ranked).** Use a `_extract_mention_count(text: str) -> int` helper (regex `(\d+)\+?\s*(?:explicit\s+)?(?:mention|request)`) to rank `dev_priorities[]` by parsed mention count.
1. Lede line: `f"I analyzed {total_reviews_analyzed:,} reviews of {game_name} and {hook}"` where `hook` is the top dev_priority's `action` rephrased as a surprise. Fallback: `one_liner`.
2. Promise-gap angle: `f"{game_name} ({positive_pct}% positive): the store page is selling a different game"` — only if `store_page_alignment.promises_broken` is non-empty.
3. Hidden-strength angle: `f"What {game_name} is hiding from its own store page"` — only if `store_page_alignment.hidden_strengths` is non-empty.

If a candidate's source is missing, fall back to a `gameplay_friction[0]` framing so we always emit 3.

**TLDR (one paragraph).** Concatenate, in order:
- `f"{total_reviews_analyzed:,} reviews of {game_name} ({positive_pct}% positive)"`
- top dev_priority's `why_it_matters` (verbatim, has the mention count)
- one-line summary of `store_page_alignment.audience_match_note` if present

**Findings (5, fixed slots).**

| # | Source                                            | Bold claim                                  | Evidence                                |
|---|---------------------------------------------------|---------------------------------------------|-----------------------------------------|
| 1 | top dev_priority by parsed mention count          | `action`                                    | `why_it_matters` verbatim               |
| 2 | `design_strengths[0]`                             | the strength itself                         | top second-ranked dev_priority's `why_it_matters` if topically related, else empty |
| 3 | `store_page_alignment.promises_broken[0]` (or `gameplay_friction[0]` fallback) | the broken promise | second dev_priority `why_it_matters`     |
| 4 | `store_page_alignment.hidden_strengths[0]` (or `design_strengths[1]` fallback) | the hidden strength | empty (positives rarely have mention counts) |
| 5 | `churn_triggers[0]` (or `player_wishlist[0]` fallback) | the trigger/wish                       | `content_depth.signals[0]` if present   |

Each finding renders:
```
**N. {bold_claim}.**

{evidence}

> [Pick a verbatim quote from the review pool below that supports this finding.]
>
> *N helpful, M funny (Xh playtime, recommended)*
```

The blockquote is a placeholder — the operator picks from the appendix and pastes. We deliberately do *not* attempt keyword-match selection; first-pass review picking is the kind of judgment we want a human to make.

**Limitations paragraph.** Hardcoded:
> A few honest limits: English-language reviews only, post-launch only (no pre-release wishlist signal), Steam-only (no console/Epic/GOG), and Steam reviewers self-select toward enthusiasts.

**CTA.** Hardcoded: `"Happy to run this on your game, drop the appid. DM me if you want the methodology."`

**Review pool appendix.** Append the existing review pool (top 40 helpful + top 15 funny, dedup, sorted by helpful then funny) as a numbered list at the bottom of the markdown, each entry showing `[review_id, votes_helpful, votes_funny, playtime_hours, voted_up, body]`. The operator scrolls and copy-pastes into the placeholders.

### What goes away

- `SYSTEM_PROMPT` (lines 83-285)
- `submit_batch_and_wait`, all `BATCH_*` exit codes, `MODEL`, `MAX_TOKENS`, `BATCH_POLL_SECONDS`, `CUSTOM_ID`, `_strip_code_fences`, `anthropic` import
- `RedditDraft`, `SubredditRecommendation` Pydantic models (no LLM output to validate)
- CLI args `--subreddit`, `--audience` (operator picks the sub when posting; framing is general-purpose)

### What stays

- `open_readonly_conn()`, `SOURCE_QUERY`, `load_source_bundle()` — unchanged
- `load_review_pool()`, `REVIEW_POOL_QUERY`, `REVIEW_BODY_MAX_CHARS` — unchanged
- `SourceBundle`, `ReviewSnippet` Pydantic models — unchanged (still useful for the data sidecar)
- Output paths: `reports/reddit_drafts/{appid}_{ts}.md` + `_data.json`
- `--data-only` flag

### New helpers

- `_extract_mention_count(text: str) -> int`
- `_pick_findings(report: GameReport) -> list[Finding]` (returns 5 `Finding(claim, evidence)` items)
- `_pick_titles(report: GameReport) -> list[str]`
- `render_markdown(...)` — rewritten end to end against the new layout

## Files to modify

- `scripts/reddit_drafter_v1.py` — full rewrite, same path

## Verification

- `STEAMPULSE_PROD_DATABASE_URL=… poetry run python scripts/reddit_drafter_v1.py --appid 3265700`
- Compare structure to `reports/reddit_drafts/Vampire_Crawlers_final.md` — same section order, same density, same boilerplate. Voice will be flatter (that's intended; the operator polishes).
- Sanity-check: at least one title candidate contains a parsed integer (e.g., 243, 161); finding #1's evidence contains a mention-count number; the review pool appendix is non-empty.
- Re-run on `--appid 18500` (the other game already drafted) to confirm the rules generalize beyond Vampire Crawlers.

## Open question to confirm before implementing

- Confirm "no LLM at all" is the right call vs. a tiny optional `--polish` flag that runs a single Claude call to rewrite voice on the rendered skeleton. My recommendation: ship deterministic-only first; add `--polish` later if the hand-edit step turns out to be high-friction.
