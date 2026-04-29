# Page Doctor v1 Prototype (Standalone Batch)

## Context

Validate the Page Doctor audit prompt end-to-end before integrating with the
library layer, the reports table, peer selection, or the rendering surface.
This v1 is a single Python script the user runs against their own game (and
any other appids they want to spot-check). No DB writes, no peers, no vision.
Markdown output. Iterate the prompt by hand until it produces useful audits,
then promote to the v2 design in `scripts/prompts/page-doctor.md`.

Uses the Anthropic batch API (50% discount, matches the production cost path).
A single-request batch is fine; async return in minutes is acceptable for a
prototype the user runs from the terminal.

## Deliverable

One file: `scripts/page_doctor_v1.py`.

CLI:
```
poetry run python scripts/page_doctor_v1.py --appid <id> [--reviews 200]
```

Optional `--reviews` controls the cap on reviews pulled (default 200).

## What the Script Does

1. **Fetch Steam metadata** via the public storefront endpoint:
   `https://store.steampowered.com/api/appdetails?appids=<appid>&cc=us&l=english`
   Extract: name, short_description, detailed_description, about_the_game,
   header_image, capsule_image, screenshots (URLs), movies (URLs and webm
   metadata), genres, categories, release_date, platforms,
   supported_languages, price_overview, developers, publishers.

2. **Fetch tags with vote weights** via SteamSpy:
   `https://steamspy.com/api.php?request=appdetails&appid=<appid>`
   Extract the `tags` dict (tag name to vote count). Sort descending; keep
   top 20.

3. **Fetch reviews** via the public Steam reviews endpoint:
   `https://store.steampowered.com/appreviews/<appid>?json=1&num_per_page=100&language=english&filter=helpful`
   Then again with `&filter=recent`. Dedupe by `recommendationid`. Cap at
   `--reviews` total. Keep: review text, voted_up, votes_up,
   weighted_vote_score, playtime_forever, timestamp_created.

4. **Build one prompt** combining everything in plain text. No JSON schema
   enforcement in v1; the model returns markdown.

5. **Submit to the Anthropic batch API** as a single-request batch using the
   `anthropic` Python SDK. Model: `claude-opus-4-7`. Read API key from
   `ANTHROPIC_API_KEY` env var.

6. **Poll the batch** until status is `ended`. Print a progress line every
   30 seconds with elapsed time.

7. **Write output** to `reports/page_doctor/<appid>_<utc_timestamp>.md`.
   Also print to stdout.

8. **Save the prompt input** alongside output as
   `reports/page_doctor/<appid>_<utc_timestamp>_input.txt` so the prompt is
   reproducible while we iterate.

## The Prompt (markdown output, no schema)

System:

```
You are a senior Steam store-page analyst. You audit one game's storefront
for wishlist conversion. You have the game's metadata, top tags with vote
weights, and a sample of recent and helpful reviews.

Produce a triage in markdown. Rules:

1. Lead with the highest-leverage fix. Order Top Fixes by impact.
2. Every recommendation cites a specific signal: a quote from a review, a
   metadata field, or a tag. No floating advice.
3. Be blunt. Do not pad. If a section has no actionable finding, say "no
   action" and move on.
4. The Verdict is one paragraph. State the diagnosis plainly. No throat-
   clearing.
5. The Page-vs-Reality section is the most important: surface where the
   store page over-promises something reviewers complain about, where
   reviewers love things the page does not pitch, and where the page
   targets the wrong audience. This is the section a generic Steam-
   marketing blog cannot produce.
6. The Demo Focus Note must reflect that 68 to 88 percent of wishlists come
   from people who never play the demo. If the page itself is weak, say so
   and tell the dev to fix the page before iterating on the demo.
7. Cite review evidence with a short quote (under 20 words) plus the
   approximate count of similar reviews you saw.
```

Output sections (model emits markdown headings in this order):

- `## Verdict`
- `## Top 3 Fixes` (each: title, rationale, effort S or M or L)
- `## Page vs Reality` (promises broken, hidden strengths, audience mismatch)
- `## Capsule and First Screenshots` (URL-based critique only, no vision in v1)
- `## Trailer Hook` (length, opening, sound-independence inferred from movie metadata)
- `## Short Description and Long Description` (lead, scannability, hook clarity)
- `## Tag Strategy` (top 5 specificity, generic tags to drop, sub-genre tags missing)
- `## Demo Focus Note`

User message template (filled by the script):

```
GAME UNDER AUDIT
appid: {{appid}}
name: {{name}}
developers: {{developers}}
publishers: {{publishers}}
release_date: {{release_date}}
price: {{price_overview}}
platforms: {{platforms}}

short_description:
{{short_description}}

about_the_game:
{{about_the_game}}

detailed_description:
{{detailed_description}}

genres: {{genres}}
categories: {{categories}}

top_tags (name: votes):
{{tags_top_20}}

capsule_image: {{capsule_image}}
header_image: {{header_image}}
screenshots (in order):
{{screenshot_urls}}
movies:
{{movie_metadata}}

REVIEWS SAMPLE
{{N reviews, each formatted as:}}
- voted_up={{voted_up}}, playtime_hours={{playtime_forever_hours}}, votes_up={{votes_up}}
  {{review_text}}

Produce the audit in the markdown format described in the system prompt.
```

## Implementation Notes

- Use `httpx` or `requests` for HTTP fetches; whatever the project already
  uses. Set a polite User-Agent.
- Steam endpoints occasionally rate-limit; on 429 sleep 5 seconds and retry
  twice.
- SteamSpy returns tags as a dict; if missing, keep the script working with
  empty tags (note in the prompt).
- Anthropic batch API: use `anthropic.Anthropic().messages.batches.create`
  with one request. Poll `batches.retrieve` until `processing_status ==
  "ended"`. Then `batches.results` to stream the result.
- Do not import from `sp.py`; that module injects dummy AWS creds at import
  time and this prototype has no AWS dependency.
- One-line comments only.

## Out of Scope (Promoted to v2)

- Peer comparison via `find_related_analyzed`
- Vision on capsule and screenshots
- Pydantic schema validation
- DB persistence
- HTML rendering
- Free vs Pro gating
- Wedge-gated rollout

## Verification

1. Run on the user's own appid. Read the output. Iterate the system prompt
   until the audit is genuinely useful, not generic.
2. Run on one known-strong store page (any high-wishlist control the user
   picks). Confirm Verdict admits the page is fine and Top Fixes is short
   or empty.
3. Run on one known-weak store page. Confirm at least one promises_broken
   or audience_mismatch finding.
4. Re-run with the same appid; confirm the saved input file is the same
   modulo review timestamps so iteration is reproducible.

Once 1 to 3 produce outputs the user trusts, lock the prompt and promote
the structure into the v2 schema in `scripts/prompts/page-doctor.md`.
