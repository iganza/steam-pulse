# Fix: English Review Counts, Review Field Expansion, and Raw Response Archival

## Background

Three issues to fix before restarting the full metadata crawl:

### 1. English vs All-Language Review Count Mismatch
`review_count` in the `games` table is populated from Steam's review summary API
using `language="all"` — it reflects total reviews across all languages. However,
`get_reviews` fetches with `language="english"` only. Eligibility thresholds check
`review_count` (all langs) but we only ever fetch English reviews. For games popular
in non-English markets, `review_count` is far higher than actual English reviews.

### 2. Missing Review Fields
The `reviews` table is missing useful fields that Steam provides in the same API
call. The `author_steamid` column exists in the schema but is never populated.

### 3. No Raw Response Archival
If we ever need to extract additional fields or rebuild data, we'd have to re-crawl
100k+ games. Archiving raw Steam API responses to S3 (gzip'd) eliminates this risk.

## Changes Required

### 1. Schema — `src/library-layer/library_layer/schema.py`

**`games` table** — add column:
```sql
review_count_english INTEGER,   -- English reviews only (drives eligibility)
```

**`reviews` table** — add columns:
```sql
language                VARCHAR(20),    -- review language code from Steam
votes_helpful           INTEGER DEFAULT 0,
votes_funny             INTEGER DEFAULT 0,
written_during_early_access BOOLEAN DEFAULT FALSE,
received_for_free       BOOLEAN DEFAULT FALSE
```

Note: `author_steamid` column already exists in schema — just needs to be populated.

### 2. Steam Source — `src/library-layer/library_layer/steam_source.py`

**`get_reviews`** — extract all new fields from each review:

```python
reviews.append({
    "review_text": r.get("review", ""),
    "voted_up": r.get("voted_up", False),
    "playtime_at_review": r.get("author", {}).get("playtime_at_review", 0),
    "timestamp_created": r.get("timestamp_created", 0),
    "language": r.get("language", ""),
    "author_steamid": r.get("author", {}).get("steamid", ""),
    "votes_helpful": r.get("votes_up", 0),
    "votes_funny": r.get("votes_funny", 0),
    "written_during_early_access": r.get("written_during_early_access", False),
    "received_for_free": r.get("received_for_free", False),
})
```

**`get_review_summary`** — change to `language="english"` so the returned count
matches what we actually fetch:

```python
resp = await self._get_with_retry(
    url, json="1", num_per_page="1", language="english", purchase_type="all"
)
```

**Also** make a second call with `language="all"` to get the all-language count
for display. Return both:
```python
return {
    "total_positive": ...,      # English
    "total_negative": ...,      # English
    "total_reviews": ...,       # English
    "total_reviews_all": ...,   # all languages (separate call)
    "review_score_desc": ...,
}
```

### 3. Crawl Service — `src/library-layer/library_layer/services/crawl_service.py`

Store both counts in `game_data`:
```python
"review_count": total_reviews_all,          # all languages, for display
"review_count_english": total_reviews,      # English only, for eligibility
```

Gate eligibility on `review_count_english`:
```python
is_eligible = review_count_english >= threshold
```

### 4. Review Repo — `src/library-layer/library_layer/repositories/review_repo.py`

Update `bulk_upsert` to include all new columns:

```sql
INSERT INTO reviews (appid, steam_review_id, author_steamid, voted_up,
                     playtime_hours, body, posted_at, language,
                     votes_helpful, votes_funny, written_during_early_access,
                     received_for_free)
VALUES %s
ON CONFLICT (steam_review_id) DO UPDATE SET ...
```

### 5. Game Repo — `src/library-layer/library_layer/repositories/game_repo.py`

Add `review_count_english` to the upsert SQL — both the INSERT column list
and the ON CONFLICT DO UPDATE SET clause.

### 6. Game Model — `src/library-layer/library_layer/models/game.py`

Add field with NULL coercion (same pattern as existing int fields):
```python
review_count_english: int = 0
```
Add to `coerce_int` validator field list.

### 7. Raw Response Archival — `src/library-layer/library_layer/services/crawl_service.py`

After each successful Steam API call (`get_app_details` and `get_reviews`),
archive the raw JSON response to S3:

- **Bucket**: `steampulse-raw-archive-v1` (us-west-2)
- **Key pattern for app details**: `app-details/{appid}/{YYYY-MM-DD}.json.gz`
- **Key pattern for reviews**: `reviews/{appid}/{YYYY-MM-DD}.json.gz`
- Multiple fetches of the same game on different dates are preserved as separate
  objects — never overwrite. This lets you track how review data changed over time
  and replay any specific snapshot.
- Reviews may need multiple pages — accumulate all raw page responses into a
  single JSON array and archive once per game.
- Use gzip compression before upload.
- The S3 client should be an **optional** dependency on `CrawlService` — when
  running locally without S3 access, archival is skipped with a warning (not
  an error). Use pattern: `archive_bucket: str | None = None` and
  `s3_client: Any | None = None` on the constructor.
- Add `ARCHIVE_BUCKET` to `SteamPulseConfig` with a default of `""` (this is
  a non-critical optional feature, not a required infrastructure field).
  Only archive when `ARCHIVE_BUCKET` is non-empty and `s3_client` is provided.

```python
import gzip
import json

def _archive_to_s3(self, key: str, data: dict | list) -> None:
    if not self._s3_client or not self._archive_bucket:
        return
    try:
        compressed = gzip.compress(json.dumps(data).encode())
        self._s3_client.put_object(
            Bucket=self._archive_bucket,
            Key=key,
            Body=compressed,
            ContentEncoding="gzip",
            ContentType="application/json",
        )
    except Exception:
        logger.warning("Failed to archive %s to S3", key)
```

### 8. Update `scripts/sp.py`

Wire up S3 archival in `_build_crawl_service` when running locally — pass
`s3_client` and `archive_bucket` so local crawls also archive:

```python
s3_client=boto3.client("s3"),
archive_bucket="steampulse-raw-archive-v1",
```

### 9. Update `SteamPulseConfig` — `src/library-layer/library_layer/config.py`

Add optional archive config:
```python
ARCHIVE_BUCKET: str = ""  # optional — empty means archival disabled
```

## Tests

All existing tests must still pass. Update:
- Any `_seed_game` helpers to include `review_count_english`
- Any test that checks review insertion to include new columns (`language`,
  `votes_helpful`, `votes_funny`, `written_during_early_access`, `received_for_free`)
- Populate `author_steamid` in review test data
- Add a test that eligibility is gated on `review_count_english`, not `review_count`
- S3 archival tests: mock S3 with moto, verify gzip'd JSON is written

Run: `poetry run pytest --tb=short -q`

## Clean Restart

**Do NOT truncate the database or restart the crawl.** The developer will handle
that manually after reviewing the changes.

After all code changes are implemented and tests pass, commit and push. The
developer will then truncate and restart the crawl.

## Notes

- `review_count` (all languages) is kept for display: "X total reviews on Steam"
- `review_count_english` is the authoritative count for eligibility and analysis
- `language` on reviews enables future multi-language support
- `votes_helpful` / `votes_funny` enable review quality weighting in analysis
- `written_during_early_access` and `received_for_free` provide review context
- `author_steamid` was always in the schema — just never populated (fix that)
- S3 archival bucket: `steampulse-raw-archive-v1` (already created, us-west-2)
  with lifecycle policy transitioning to Infrequent Access after 30 days
- We always fetch reviews with `language="english"` for analysis quality
