# Tag Doctor v1 (Standalone, Reads Prod DB)

## Context

Tags are the highest-leverage Steam page lever after the capsule. Steam's
algorithm weights the top 5 tags heavily; generic tags ("Indie",
"Singleplayer") in those slots dilute discovery. Tag wizard moves are
"run-monthly" advice in the established marketing literature (Zukowski,
presskit.gg).

Tag Doctor is the smallest atomic primitive in the dev/marketing toolkit:
it audits one game's tag strategy by comparing against high-performing
tag-overlap peers. Page Doctor's tag section will eventually call this
logic; building Tag Doctor first means Page Doctor v2 reuses it instead
of duplicating it.

v1 is a standalone Python script the user runs locally. It reads from
prod DB (no writes). Mostly data analysis, with one small LLM call at
the end for narrative. No web fetches, no DB writes, no integration
with the library layer.

## Deliverable

One file: `scripts/tag_doctor_v1.py`.

CLI:
```
poetry run python scripts/tag_doctor_v1.py --appid <id> [--peers 15] [--data-only]
```

- `--peers` caps the peer set size (default 15).
- `--data-only` skips the LLM narrative call and emits the data report only.

Output:
- `reports/tag_doctor/<appid>_<utc_timestamp>.md` (rendered report)
- `reports/tag_doctor/<appid>_<utc_timestamp>_data.json` (raw structured data, for reproducibility and downstream reuse)

Also prints the report to stdout.

## DB Connection

Reads from prod via `STEAMPULSE_PROD_DATABASE_URL` env var (psycopg
directly, no SQLAlchemy, no library_layer imports). Do NOT
`from sp import ...`; sp.py injects dummy AWS creds at import time. The
script connects with `psycopg.connect(os.environ["STEAMPULSE_PROD_DATABASE_URL"])`
and explicitly opens transactions in read-only mode.

## What the Script Does

### 1. Pull the dev's game and top tags

```sql
SELECT g.appid, g.name, g.slug, g.review_count, g.positive_pct, g.release_date
FROM games g
WHERE g.appid = :appid;
```

```sql
SELECT t.name, gt.votes
FROM game_tags gt
JOIN tags t ON t.id = gt.tag_id
WHERE gt.appid = :appid
ORDER BY gt.votes DESC
LIMIT 20;
```

If no tags found in DB, abort with a helpful error pointing at the
SteamSpy/Steam-store-page tag ingestion path (per the steam-pulse.org
backlog item about tag pipelines).

### 2. Pick high-performing tag-overlap peers

Compute peer scores via tag-vote-weighted overlap, restricted to peers
with proven traction:

```sql
WITH dev_tags AS (
  SELECT tag_id, votes
  FROM game_tags
  WHERE appid = :appid
)
SELECT g.appid, g.name, g.slug, g.review_count, g.positive_pct,
       SUM(gt.votes * dt.votes) AS overlap_score
FROM games g
JOIN game_tags gt ON gt.appid = g.appid
JOIN dev_tags dt ON dt.tag_id = gt.tag_id
WHERE g.appid != :appid
  AND g.review_count >= 500
  AND g.positive_pct >= 75
GROUP BY g.appid, g.name, g.slug, g.review_count, g.positive_pct
ORDER BY overlap_score DESC
LIMIT :peers;
```

### 3. Pull each peer's top tags

One batched query for all selected peer appids:

```sql
SELECT gt.appid, t.name, gt.votes,
       ROW_NUMBER() OVER (PARTITION BY gt.appid ORDER BY gt.votes DESC) AS rank
FROM game_tags gt
JOIN tags t ON t.id = gt.tag_id
WHERE gt.appid = ANY(:peer_appids)
  AND gt.votes > 0;
```

Filter in Python to top 10 per peer.

### 4. Compute generic-tag frequency across the catalog

For each tag in the dev's top 10, get its catalog-wide adoption rate
(what percent of all eligible games carry this tag in their top 10):

```sql
WITH per_game_top10 AS (
  SELECT gt.appid, gt.tag_id,
         ROW_NUMBER() OVER (PARTITION BY gt.appid ORDER BY gt.votes DESC) AS rank
  FROM game_tags gt
  JOIN games g ON g.appid = gt.appid
  WHERE g.review_count >= 100
)
SELECT t.name,
       COUNT(*) FILTER (WHERE pgt.rank <= 10) AS games_with_in_top10,
       (SELECT COUNT(*) FROM games WHERE review_count >= 100) AS eligible_total
FROM per_game_top10 pgt
JOIN tags t ON t.id = pgt.tag_id
WHERE t.name = ANY(:dev_top10_tag_names)
GROUP BY t.name;
```

A tag with adoption_rate > 40% across the eligible catalog flags as
generic (low discovery signal in a top slot).

### 5. Compute the diagnostic data structures

In Python, with pydantic models:

```python
class TagWithVotes(BaseModel):
    name: str
    votes: int

class PeerSummary(BaseModel):
    appid: int
    name: str
    review_count: int
    positive_pct: float
    overlap_score: int
    top_tags: list[TagWithVotes]

class PeerAdoption(BaseModel):
    tag_name: str
    peers_with_tag_in_top10: int
    peers_total: int
    adoption_pct: float
    avg_votes_among_peers: int

class GenericTagFlag(BaseModel):
    tag_name: str
    catalog_adoption_pct: float
    rank_in_dev_game: int

class TagDoctorData(BaseModel):
    appid: int
    name: str
    review_count: int
    positive_pct: float
    dev_top_tags: list[TagWithVotes]
    peers: list[PeerSummary]
    missing_from_dev: list[PeerAdoption]
    generic_in_top5: list[GenericTagFlag]
```

Compute:
- `missing_from_dev`: tags in >=40% of peers' top-10 that are NOT in
  the dev's top 20. Sort by adoption_pct desc, then avg_votes desc.
  Cap at 10.
- `generic_in_top5`: any of the dev's top-5 tags whose
  catalog_adoption_pct > 40%.

Persist `TagDoctorData` as the `_data.json` sidecar.

### 6. Render data report (markdown)

Always emit. Sections:

- `# Tag Doctor for {name} (appid {appid})`
- `Generated <utc_timestamp> against prod`
- `## Your top tags` (table of name + votes)
- `## High-performing peers` (table of name, review_count, positive_pct, overlap_score)
- `## Tags peers ride that you don't` (table of tag, peer adoption %, avg votes)
- `## Generic tags currently in your top 5` (with adoption % across catalog)
- `## Peer-by-peer tag breakdown` (collapsed list per peer)

Pure data, no LLM, deterministic output for the same input.

### 7. LLM narrative (skipped if --data-only)

Submit a single-request batch to the Anthropic batch API (50% discount;
the script just waits, that is fine). Model: `claude-opus-4-7`. Read
`ANTHROPIC_API_KEY` from env.

Steps:
- `client.messages.batches.create(...)` with one request.
- Poll `client.messages.batches.retrieve(batch_id)` every 30s, printing
  elapsed time, until `processing_status == "ended"`.
- Stream results via `client.messages.batches.results(batch_id)` and
  extract the message content.

System prompt:

```
You are a senior Steam tag strategist. You have one game's tag data plus
peer comparison data, all derived from the live Steam catalog.

Produce a tag wizard plan in markdown. Rules:

1. Lead with a one-paragraph verdict. State plainly whether the tag
   strategy is fine, has minor improvements, or is a significant drag
   on discovery.
2. Recommend at most 5 tag changes for this month, ordered by impact:
   add, drop, or reposition. Each must cite the data row that supports
   it (e.g. "12/15 peers carry Roguelite in their top 10").
3. If a recommendation is purely defensive (drop a generic), say so.
   If it is opportunistic (add a peer-popular niche tag), say so.
4. Do not invent tags that are not present in either the dev's tag
   list or the peers' tag lists.
5. Be blunt. No throat-clearing. No filler.
6. Close with one sentence on cadence: re-run Tag Doctor monthly.
```

User message: serialized `TagDoctorData` as JSON plus a one-line ask
("Produce the tag wizard plan").

Append the LLM's markdown to the data report under a leading
`## Verdict and Recommendations` section (placed before the data
sections so the dev sees recommendations first).

## Implementation Notes

- One file. No package structure for v1. Helpers inline.
- `psycopg` (v3), no SQLAlchemy. Open one read-only connection.
- One-line comments only. No multi-paragraph docstrings.
- pydantic.BaseModel for all data structures, no dataclasses.
- No field defaults that hide required-ness; every field explicit.
- No script tests (operator scripts).
- Output paths: create `reports/tag_doctor/` if missing, persist both
  the rendered .md and the _data.json sidecar with the same timestamp
  prefix.
- On any DB error, print a helpful message and exit non-zero.

## Reusable Surface for Page Doctor v2

Structure the script so the four data-extraction functions
(`fetch_dev_game`, `fetch_dev_tags`, `pick_peers`, `fetch_peer_tags`,
`compute_diagnostics`) are pure functions taking a connection and
returning pydantic models. Page Doctor v2 will lift these into the
library layer wholesale; keeping them pure here pays that future cost
down now.

## Out of Scope (v2 / Page Doctor)

- Vision (no images involved in tag analysis)
- Persistence to a `tag_doctor_reports` table
- Free vs Pro gating
- Trend analysis ("is this tag rising or falling")
- Tag categorization (theme vs gameplay vs setting)

## Verification

1. Run on the user's own appid. Read both the data and the narrative.
   Confirm the missing-tags-from-peers list contains tags that show up
   in the peer-by-peer breakdown.
2. Run `--data-only` on the same appid. Confirm the report is byte-
   identical except for the timestamp and the absent narrative section.
3. Run on one strong tag-strategy control (a known top-quartile game
   in the same niche). Confirm verdict admits the strategy is fine and
   the recommendation list is short or empty.
4. Run on one weak control (a game with "Indie" + "Singleplayer" +
   "Action" in top 5). Confirm at least one generic_in_top5 entry and
   a non-trivial recommendation list.
5. Re-run with the same appid one minute later. Confirm `_data.json`
   is identical (deterministic given DB snapshot).
