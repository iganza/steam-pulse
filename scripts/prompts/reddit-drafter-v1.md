# Reddit Drafter v1 (Standalone, Reads Prod `reports` Table)

## Context

The wedge needs distribution. Reddit is the highest-leverage channel for
the operator: r/gamedev, r/patient_gamers, r/Steam, and game-specific or
genre subs collectively reach the audience SteamPulse already serves. The
dominant viral format on those subs is the **"I analyzed [specific
number] of [thing] and here's what I found"** post. It works because it
leads with rigor, gives away the insight for free, and the call-to-action
is earned, not led.

We already produce per-game review syntheses via the three-phase analysis
pipeline. Each Phase 3 `GameReport` distills up to 2,000 Steam reviews
into a structured payload: `total_reviews_analyzed`, one-liner, audience
profile, design strengths, gameplay friction, player wishlist, churn
triggers, dev priorities (with mention counts), refund signals,
community/monetization/content health, promise-gap (`store_page_alignment`),
sentiment trend, hidden-gem score, competitive context. That is exactly
the raw material a Reddit post needs.

The bottleneck is the operator's time turning that analyst-voice
structured payload into a Reddit-voice draft.

**Reddit Drafter v1** is a one-shot script: pass an `--appid`, get back a
Reddit-ready draft (title candidates, post body, TLDR, subreddit
recommendations, self-edit checklist) the operator can paste with about
five minutes of hand editing.

Not a content engine. Not scheduled. Runs once per post, on demand, after
the Phase 3 report exists for the appid. No DB writes. No web fetches.
One batch LLM call.

**Scope is intentionally narrow**: Phase 3 `GameReport` only. Concept
Doctor, Tag Doctor, Niche Scout, and Trend Spotter outputs are deliberately
out of scope. Their natural Reddit angles are different enough that
separate prompts will do them justice; bundling would water down all of
them.

## Deliverable

One file: `scripts/reddit_drafter_v1.py`.

CLI:
```
poetry run python scripts/reddit_drafter_v1.py --appid <N> [--subreddit r/gamedev] [--audience devs|players] [--data-only]
```

- `--appid` (required): the Steam appid whose Phase 3 report drives the
  draft. The script reads `reports.report_json` and `games.name` from
  prod for that appid.
- `--subreddit` (optional): if set, the LLM tunes voice, length, and
  framing to that subreddit's norms instead of producing a sub-agnostic
  post and recommending 1-3 fits. Accepts canonical form (`r/gamedev`,
  `r/patient_gamers`, etc.). Default: empty string (LLM recommends).
- `--audience` (optional): `devs` or `players`. Devs framing leans on
  dev priorities, churn triggers, and promise-gap as design lessons.
  Players framing leans on whether-to-buy, hidden strengths, value
  perception, and playtime correlation. Default: empty string (LLM
  picks based on report strengths).
- `--data-only` (optional): skip the LLM call. Print the parsed
  `SourceBundle` and exit. Useful for verifying the input parser
  without paying for a batch.

Output:
- `reports/reddit_drafts/<appid>_<utc_timestamp>.md` (the draft)
- `reports/reddit_drafts/<appid>_<utc_timestamp>_data.json` (the
  Pydantic dump: titles, body, TLDR, subreddit recs, edit checklist,
  source pointer)

Also prints the draft to stdout.

## DB connection

Reads prod via `STEAMPULSE_PROD_DATABASE_URL` env var (psycopg2
directly, no SQLAlchemy, no `library_layer` imports). Do NOT
`from sp import ...` (per `feedback_sp_py_import_side_effects.md`). Same
pattern as `concept_doctor_v1.py`, `niche_scout_v1.py`,
`tag_doctor_v1.py`, `trend_spotter_v1.py`. Reuse `open_readonly_conn`
shape inline.

One query:

```sql
SELECT
  r.report_json,
  r.pipeline_version,
  r.created_at,
  g.name AS game_name,
  g.appid,
  g.review_count_total,
  g.positive_pct,
  g.genres
FROM reports r
JOIN games g ON g.appid = r.appid
WHERE r.appid = %s
```

(Adjust column names to match the actual `games` schema; the explore
step should verify before coding.)

If no row: exit non-zero with
`No Phase 3 report for appid <N>. Run analysis first.`

## Why this format works on Reddit

Patterns observed in successful "I analyzed X" posts on r/gamedev,
r/patient_gamers, r/Steam, and genre subs:

1. **Specific, non-round number in the title.** "I analyzed 1,997
   reviews" beats "I analyzed 2,000". Round numbers read as marketing.
   The script always uses the exact `total_reviews_analyzed` from the
   report, never rounds.
2. **Title carries the surprise.** The most counterintuitive finding
   goes in the title. Strong candidates from a typical GameReport:
   - The promise-gap surprise (`store_page_alignment.promises_broken`
     or `hidden_strengths`).
   - The playtime correlation (e.g., 10-200h rate 98%, sub-2h rate
     85%).
   - The dev-priority headline mention count (e.g., "68+ players
     mention X").
   - The age/longevity gap (e.g., 15 years old, still rated 96%).
3. **Methodology in 1-2 sentences.** Academic preamble kills posts.
4. **3-5 numbered findings, skimmable.** Each: bold claim, evidence
   citing a specific field or mention count, what-it-means line.
5. **Limitations paragraph late in the post.** Humility builds trust.
   For Phase 3 reports the honest limits are: English-language reviews
   only, post-launch only (no pre-release wishlist data), Steam-only
   (no console/Epic), self-selected reviewers.
6. **Soft CTA at the very end.** "Happy to run this on your game,
   drop your appid below." No URLs.
7. **First-person voice.** "I" not "we". One mention of "a small
   tool I built" is allowed, late in the post, in passing.
8. **Anti-AI tells removed.** No em-dashes. No "delve", "tapestry",
   "navigate the landscape", "crucial", "leverage" as a verb. No
   perfect three-clause parallelism.

Encoded as explicit grounding rules in the system prompt, not soft
suggestions.

## Input adapter (Phase 3 GameReport only)

Phase 3 `GameReport` schema (from
`src/library-layer/library_layer/models/analyzer_models.py`):

```
game_name, total_reviews_analyzed, sentiment_trend, sentiment_trend_note,
sentiment_trend_reliable, sentiment_trend_sample_size, one_liner,
audience_profile {ideal_player, casual_friendliness, archetypes, not_for},
design_strengths[], gameplay_friction[], player_wishlist[],
churn_triggers[], technical_issues[],
refund_signals {refund_language_frequency, primary_refund_drivers, risk_level},
community_health {overall, signals, multiplayer_population},
monetization_sentiment {overall, signals, dlc_sentiment},
content_depth {perceived_length, replayability, value_perception, signals,
               confidence, sample_size},
dev_priorities[] {action, why_it_matters, frequency, effort},
competitive_context[] {game, comparison_sentiment, note},
genre_context, hidden_gem_score, appid,
store_page_alignment {promises_delivered, promises_broken, hidden_strengths,
                      audience_match, audience_match_note},
review_date_range_start, review_date_range_end
```

The adapter pulls a `SourceBundle` for the LLM:

```python
class SourceBundle(BaseModel):
    appid: int
    game_name: str                  # from games.name
    total_reviews_analyzed: int     # the headline number
    review_date_range_start: str    # for the temporal hook
    review_date_range_end: str
    pipeline_version: str
    report_created_at: str
    review_count_total: int         # all-language total from games
    positive_pct: int               # Steam's positive %
    genres: list[str]               # for subreddit suggestion
    report_json: dict               # the full GameReport, passed verbatim
```

The system prompt receives the full `report_json` so the LLM can quote
verbatim from `design_strengths`, `gameplay_friction`, etc., and cite
exact `dev_priorities[i].why_it_matters` text including any mention
counts the synthesis baked in (e.g., "28+ explicit mentions"). Mention
counts are the Reddit-credibility goldmine; the grounding rules require
they appear at least twice in the body when present in the source.

## Pydantic data structures

```python
class SubredditRecommendation(BaseModel):
    name: str                  # "r/gamedev"
    confidence: str            # "high" | "medium" | "low"
    rationale: str             # 1-2 sentences
    body_tweaks: str           # how to adjust the draft for this sub

class RedditDraft(BaseModel):
    candidate_titles: list[str]                 # exactly 3, ranked
    recommended_subreddits: list[SubredditRecommendation]   # 1-3
    chosen_audience: str                        # "devs" | "players" (LLM picks if --audience empty)
    post_body: str                              # Reddit-flavored markdown
    tldr: str                                   # 2-3 sentences
    self_edit_checklist: list[str]              # 5-7 actionable items

class RedditDrafterData(BaseModel):
    generated_at: str
    source: SourceBundle
    target_subreddit: str      # empty if --subreddit not passed
    requested_audience: str    # empty if --audience not passed
    draft: RedditDraft
```

Per `feedback_avoid_none_types.md`: no `| None`. Empty strings, empty
lists, zero ints. Per `feedback_no_field_defaults.md`: every field is
required.

## LLM call

One Anthropic batch request via the batch API per
`feedback_always_batch_api.md`. Model: `claude-opus-4-7`. Lifecycle
copied inline from `concept_doctor_v1.submit_batch_and_wait`. custom_id:
`reddit_drafter_v1`.

System prompt structured with XML tags (matching the post-Tag-Doctor-v1
convention):

- `<inputs>`: `SourceBundle` schema description, plus the verbatim
  `report_json` payload. `target_subreddit` (empty means recommend).
  `requested_audience` (empty means LLM picks).
- `<goal>`: Produce a Reddit post draft modeled on the "I analyzed
  [N] reviews of [Game] and here's what I found" format. Optimize for
  upvotes from craft-focused indie devs OR thoughtful players
  depending on `chosen_audience`. The operator hand-edits, so
  prioritize structure and substance over voice perfection. Three
  title candidates, ranked. 1-3 subreddit recommendations with
  body-tweak notes (or, if `target_subreddit` is set, return exactly
  that one entry, confidence "high", body_tweaks empty).
- `<grounding_rules>`:
  - Every numeric claim cites a field from the source. No invented
    stats. Use `total_reviews_analyzed` exactly, never round.
  - Pick the most counterintuitive finding for the title. Strong
    candidates: a `store_page_alignment.promises_broken` item that
    contradicts marketing, a `hidden_strengths` item the store page
    underplays, a churn trigger with a specific time window, a
    dev priority with a high mention count, longevity if
    `review_date_range_start` is more than 5 years ago.
  - When `dev_priorities[i].why_it_matters` contains mention counts
    like "28+ explicit mentions", quote them in the body. Mention
    counts are credibility multipliers. Use at least two when
    available.
  - Quote churn triggers as specific behaviors with their time
    window or trigger condition (e.g., "players expecting RPG
    progression drop out within 3-9 hours"), not as paraphrase.
  - If `chosen_audience` is "devs": frame findings as design and
    marketing lessons. Pull from `dev_priorities`, `churn_triggers`,
    `store_page_alignment`, `competitive_context`. Body 600-900
    words.
  - If `chosen_audience` is "players": frame as whether to buy,
    what to expect, who it's for. Pull from `audience_profile`,
    `design_strengths`, `content_depth`, `hidden_strengths`,
    `playtime correlation` if present. Body 400-700 words.
  - If `target_subreddit` is set, override `chosen_audience`
    accordingly: r/gamedev, r/IndieDev, r/SoloDevelopment ->
    devs. r/patient_gamers, r/Steam, r/pcgaming -> players.
    Genre subs (r/towerdefense, r/roguelikedev, etc.) -> players
    by default unless the source data is exceptionally
    design-focused.
  - Limitations paragraph mandatory. Use these honest limits for
    Phase 3 reports: English-language reviews only, post-launch
    only (no pre-release wishlist signal), Steam-only (no
    console/Epic/GOG), self-selected reviewers (Steam reviewers
    skew positive vs silent majority), `total_reviews_analyzed`
    is a cap (large games sample 2,000 of many more). Pick 2-3
    that fit; do not list all of them.
  - Soft CTA only. Accepted forms: "happy to run this on your
    game, drop the appid", "DM me if you want the methodology".
    Forbidden: "check out my SaaS", "sign up at", any link to
    steam-pulse.org or any domain.
  - First-person. "I" not "we". One mention of "a small tool I
    built" allowed, late, in passing. The post is about the
    findings, not the tool.
  - Mild self-deprecation when honest. "I expected X but the data
    said Y" works when supported by the report.
  - No em-dashes anywhere (per `feedback_no_em_dashes.md`). No
    "delve", "tapestry", "navigate the landscape", "in today's
    rapidly evolving", "crucial" (as adjective), "leverage" (as
    verb), "myriad", "robust", "seamless".
  - Reddit markdown only: `**bold**`, `*italic*`, `1.` ordered
    lists, `*` unordered, `>` block quotes, code via 4-space
    indent. No tables. No HTML.
- `<output_rubric>`:
  - `<section role="candidate_titles" length="3 items">`: ranked.
    Each title 60-110 chars. Title #1 has the sharpest specific
    number plus game name plus counterintuitive claim. Titles 2
    and 3 vary the angle (one drier/methodological, one bolder/
    contrarian) so the operator has real choices.
  - `<section role="recommended_subreddits" length="1-3 items">`:
    each names the sub, confidence, rationale (1-2 sentences),
    `body_tweaks` (what to change for that sub). If
    `target_subreddit` is set, return exactly one entry,
    confidence "high", `body_tweaks` empty. Skip r/IndieDev when
    the game is clearly not an indie title (heuristic: AAA studio
    in `competitive_context`, or large `review_count_total`).
  - `<section role="chosen_audience" length="1 word">`: "devs"
    or "players". Echoes `requested_audience` if set, else picks.
  - `<section role="post_body" length="see grounding rules">`:
    Reddit-flavored markdown. Structure: hook (1-2 sentences,
    leads with `total_reviews_analyzed` and the surprise),
    methodology (1-2 sentences, casual; mention review-date range
    if it strengthens the angle), 3-5 numbered findings (each:
    bold claim, evidence with cited stat or mention count, what-
    it-means line), limitations (1 paragraph, 2-3 honest limits),
    soft CTA (1 line). Do not include the title. Do not include
    the TLDR.
  - `<section role="tldr" length="2-3 sentences">`: distilled.
    Operator pastes at top or bottom; LLM doesn't position it.
  - `<section role="self_edit_checklist" length="5-7 items">`:
    each item is a concrete edit. Required items: confirm appid
    and game name accuracy, read limitations aloud for tone,
    verify subreddit self-promo rules, add one personal sentence
    only the operator could write, double-check any quoted
    mention counts against the source. Other 1-2 items are
    draft-specific.
- `<style>`: indie-dev-to-indie-devs (or thoughtful-player-to-
  thoughtful-players) voice, blunt, lightly self-deprecating where
  honest, no marketing adjectives.

User message: `SourceBundle.model_dump_json(indent=2)` followed by
`Target subreddit: <target_subreddit or "none specified">.` and
`Requested audience: <requested_audience or "let the model pick">.`
followed by `Produce the draft.`

## Files to create

| File | Purpose |
|---|---|
| `scripts/reddit_drafter_v1.py` | The script |
| `reports/reddit_drafts/` | Output dir, created at first run if missing |

No changes to `library_layer`, no migrations, no API endpoints, no tests.

## Reusable surface map

| Component | Source |
|---|---|
| Read-only DB connection | `scripts/concept_doctor_v1.py:open_readonly_conn` |
| Batch lifecycle (submit + poll + parse) | `scripts/concept_doctor_v1.py:submit_batch_and_wait` |
| Output dual-file pattern | `scripts/niche_scout_v1.py:main` |
| LLM-prompt XML tagging convention | `scripts/concept_doctor_v1.py:SYSTEM_PROMPT`, `scripts/tag_doctor_v1.py:SYSTEM_PROMPT` |
| Phase 3 `GameReport` schema | `src/library-layer/library_layer/models/analyzer_models.py` (read but do not import; mirror the field names) |
| utc_timestamp generation | any existing v1 script |

Copy, do not import, per `feedback_sp_py_import_side_effects.md`.

## Implementation notes

- One file. Helpers inline.
- pydantic.BaseModel for all data structures (per
  `feedback_always_pydantic.md`).
- One-line comments only (per `feedback_terse_comments.md`).
- No `| None` (per `feedback_avoid_none_types.md`).
- No field defaults (per `feedback_no_field_defaults.md`).
- No script tests (per `feedback_no_script_tests.md`).
- No em-dashes anywhere in code or output strings (per
  `feedback_no_em_dashes.md`).
- No commit/push from the assistant (per
  `feedback_no_commit_push.md`).
- No `from sp import ...` (per
  `feedback_sp_py_import_side_effects.md`).
- Per `feedback_no_speculative_llm_spend.md`: validate the report
  exists for the appid before submitting the batch. If not, exit
  non-zero with the exact appid and a one-line action ("run
  three-phase analysis on appid <N> first").
- Cost note (per `feedback_llm_cadence_economics.md`): one batch
  call per run, ~6K input tokens (the full report_json) + ~2K output
  at opus-4-7 batch pricing is roughly $0.15 per draft. On-demand
  only.
- Reddit markdown is stricter than GitHub-flavored. Forbid tables in
  the system prompt. If the LLM emits a pipe-table anyway, the
  script does not post-process; the self-edit checklist tells the
  operator to flatten it.

## Verification

1. **Real run on a known good appid** (use 18500 / Defense Grid: The
   Awakening, since it has a current Phase 3 report visible at
   `https://d1mamturmn55fm.cloudfront.net/games/18500/...`):
   `poetry run python scripts/reddit_drafter_v1.py --appid 18500`
   Confirm:
   - 3 candidate titles, all under 110 chars, all containing
     `1,997` (the exact `total_reviews_analyzed`) and the game
     name. None contain `2,000`.
   - 1-3 subreddit recommendations. r/gamedev should appear at
     "high" confidence (the dev_priorities and churn_triggers are
     rich). r/towerdefense or r/Steam reasonable as a player-side
     alternative.
   - `chosen_audience` is "devs" or "players", non-empty.
   - Body is in the right word band for the chosen audience and
     contains no em-dashes (`grep '—' <output_path>` returns
     nothing), no "delve", no "tapestry", no "leverage" as verb.
   - Body cites at least one mention count from the source's
     `dev_priorities` (e.g., "28+ mentions") if such counts are
     present in the report.
   - Body quotes at least one `churn_triggers` item with its
     specific time window or condition.
   - Limitations paragraph present, contains 2-3 of the canonical
     limits.
   - CTA contains no URLs and no "steam-pulse".
   - TLDR is 2-3 sentences.
   - Self-edit checklist has 5-7 items including the required
     ones.

2. **--data-only**:
   `poetry run python scripts/reddit_drafter_v1.py --appid 18500 --data-only`
   Confirms the parsed `SourceBundle` shows correct
   `total_reviews_analyzed` (1,997), correct game name, correct
   review date range, populated `report_json`. No batch call made.

3. **--audience devs override**:
   `--appid 18500 --audience devs`
   Confirms body length skews 600-900 words and findings center on
   dev_priorities + churn_triggers + store_page_alignment.

4. **--audience players override**:
   `--appid 18500 --audience players`
   Confirms body length skews 400-700 words and findings center on
   audience_profile + design_strengths + hidden_strengths + content
   depth.

5. **--subreddit r/patient_gamers override**:
   `--appid 18500 --subreddit r/patient_gamers`
   Confirms `recommended_subreddits` returns exactly one entry for
   r/patient_gamers, confidence "high", body_tweaks empty.
   `chosen_audience` should resolve to "players".

6. **Missing report**:
   `--appid 1` (or any appid known to have no Phase 3 report)
   Exit non-zero, message: "No Phase 3 report for appid 1. Run
   analysis first." Batch call not submitted.

7. **Anti-AI-tell grep**:
   `grep -i -E 'delve|tapestry|navigate the landscape|—|leverage' <output_path>`
   Returns no matches.

## Out of scope (v2 / future)

- Macro/cohort report types (Concept Doctor, Tag Doctor, Niche
  Scout, Trend Spotter). Each gets its own future prompt with a
  different framing template.
- Multiple drafts per run (e.g., one r/gamedev + one
  r/patient_gamers in parallel). v1 is one draft per invocation;
  re-run with `--subreddit` for variants.
- Tone/voice profile per operator.
- Auto-posting to Reddit via the API. Manual paste only.
- A/B title generation (more than 3 candidates).
- Image / screenshot suggestions. Operator picks media.
- Comment-reply drafting. Operator handles comments.
- Cron / scheduled execution. On-demand only.
- A `/api/reddit-drafts` endpoint. Disk output is the surface.
