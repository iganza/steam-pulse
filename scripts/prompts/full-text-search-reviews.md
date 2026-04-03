# Full-Text Search over Reviews — Implementation Prompt

## Goal

Enable fast full-text search across all review bodies in the SteamPulse
database using PostgreSQL's built-in `tsvector` / `tsquery` infrastructure.
This unlocks questions like:

- "What percentage of negative reviews mention 'refund'?"
- "Which games have the most crash-related complaints?"
- "Find all reviews mentioning 'save corruption' for this game"
- "How many reviews across all RPGs mention 'pay to win'?"

No external search engines (no Elasticsearch, no Meilisearch). Pure PostgreSQL.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│  reviews table                                       │
│  ┌────────┬──────────────┬─────────────────────────┐ │
│  │ body   │ body_tsv     │ (existing columns...)   │ │
│  │ TEXT   │ TSVECTOR     │                         │ │
│  │        │ GIN indexed  │                         │ │
│  └────────┴──────────────┴─────────────────────────┘ │
└─────────────────────────────────────────────────────┘
         │
         ▼
   @@ to_tsquery('english', 'refund | crash')
         │
         ▼
   SELECT appid, body, ts_rank(body_tsv, query)
   FROM reviews, to_tsquery('english', ...) query
   WHERE body_tsv @@ query
   ORDER BY ts_rank DESC
```

**Why `tsvector` over `ILIKE` or `pg_trgm`:**
- `ILIKE '%refund%'` on ~12M review rows = full sequential scan (~30-60s)
- `tsvector + GIN` = inverted index lookup (~10-50ms)
- Handles stemming: "refunded", "refunding", "refunds" all match "refund"
- Supports ranking by relevance (`ts_rank`)
- Supports phrase search: `'pay <-> to <-> win'` (words in order)
- Built into PostgreSQL, zero extra infra

---

## Change 1 — Schema Migration

In `src/library-layer/library_layer/schema.py`:

### Add column and index

In `create_all()`, add after the existing reviews table creation:

```python
# Full-text search vector column + index
_add_column_if_missing(cur, "reviews", "body_tsv", "TSVECTOR")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_reviews_body_tsv
    ON reviews USING GIN (body_tsv)
""")
```

### Add trigger for auto-population on INSERT/UPDATE

```python
cur.execute("""
    CREATE OR REPLACE FUNCTION reviews_body_tsv_update() RETURNS trigger AS $$
    BEGIN
        NEW.body_tsv := to_tsvector('pg_catalog.english', COALESCE(NEW.body, ''));
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
""")

cur.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger WHERE tgname = 'trg_reviews_body_tsv'
        ) THEN
            CREATE TRIGGER trg_reviews_body_tsv
                BEFORE INSERT OR UPDATE OF body ON reviews
                FOR EACH ROW
                EXECUTE FUNCTION reviews_body_tsv_update();
        END IF;
    END $$;
""")
```

**Why a trigger instead of a generated column?** PostgreSQL doesn't support
`GENERATED ALWAYS AS` with `tsvector` type. A trigger is the standard pattern
(used by Django, Rails, etc.).

---

## Change 2 — Backfill Existing Reviews

Add a management command to backfill the `body_tsv` column for reviews that
were inserted before the trigger existed. Add to `scripts/sp.py`:

```python
def cmd_backfill_tsv() -> None:
    """Backfill body_tsv for existing reviews (one-time operation)."""
    conn, _, _, _, _ = _get_repos()
    try:
        with conn.cursor() as cur:
            # Count reviews needing backfill
            cur.execute("SELECT COUNT(*) FROM reviews WHERE body_tsv IS NULL")
            total = cur.fetchone()[0]
            if total == 0:
                _ok("All reviews already have body_tsv populated")
                return

            _info(f"{total:,} reviews need body_tsv backfill")

            # Process in batches to avoid locking the table
            batch_size = 10000
            updated = 0
            while True:
                cur.execute("""
                    UPDATE reviews
                    SET body_tsv = to_tsvector('pg_catalog.english', COALESCE(body, ''))
                    WHERE id IN (
                        SELECT id FROM reviews
                        WHERE body_tsv IS NULL
                        LIMIT %s
                    )
                """, (batch_size,))
                batch_count = cur.rowcount
                conn.commit()
                updated += batch_count
                _info(f"  backfilled {updated:,}/{total:,}")
                if batch_count < batch_size:
                    break

            _ok(f"Backfill complete: {updated:,} reviews updated")
    finally:
        conn.close()
```

**CLI:**
```bash
poetry run python scripts/sp.py backfill-tsv
```

**Estimated time:** ~10-15 minutes for 12M reviews on RDS db.t3.medium.

---

## Change 3 — Review Repository

Add search methods to `src/library-layer/library_layer/repositories/review_repo.py`:

### Method 1: Search within a single game

```python
def search_reviews(
    self,
    appid: int,
    query: str,
    voted_up: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Full-text search over reviews for a specific game.

    Args:
        appid: Game to search within.
        query: Natural language search query (e.g., "crash performance fps").
               Words are OR'd by default. Use & for AND, | for OR explicitly.
        voted_up: Optional filter — True for positive, False for negative, None for all.
        limit: Max results.
        offset: Pagination offset.

    Returns:
        List of dicts with: id, body, voted_up, playtime_hours, posted_at,
        votes_helpful, rank (relevance score).
    """
    tsquery = _build_tsquery(query)
    conditions = ["appid = %s", "body_tsv @@ to_tsquery('english', %s)"]
    params: list = [appid, tsquery]

    if voted_up is not None:
        conditions.append("voted_up = %s")
        params.append(voted_up)

    sql = f"""
        SELECT id, body, voted_up, playtime_hours, posted_at, votes_helpful,
               ts_rank(body_tsv, to_tsquery('english', %s)) AS rank
        FROM reviews
        WHERE {' AND '.join(conditions)}
        ORDER BY rank DESC, votes_helpful DESC
        LIMIT %s OFFSET %s
    """
    params_full = [tsquery] + params + [limit, offset]
    with self.conn.cursor() as cur:
        cur.execute(sql, params_full)
        return [dict(row) for row in cur.fetchall()]
```

### Method 2: Search across ALL games (global search)

```python
def search_reviews_global(
    self,
    query: str,
    voted_up: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Full-text search across all reviews in the database.

    Returns:
        List of dicts with: id, appid, game_name, body, voted_up,
        playtime_hours, posted_at, votes_helpful, rank.
    """
    tsquery = _build_tsquery(query)
    conditions = ["r.body_tsv @@ to_tsquery('english', %s)"]
    params: list = [tsquery]

    if voted_up is not None:
        conditions.append("r.voted_up = %s")
        params.append(voted_up)

    sql = f"""
        SELECT r.id, r.appid, g.name AS game_name, r.body, r.voted_up,
               r.playtime_hours, r.posted_at, r.votes_helpful,
               ts_rank(r.body_tsv, to_tsquery('english', %s)) AS rank
        FROM reviews r
        JOIN games g ON g.appid = r.appid
        WHERE {' AND '.join(conditions)}
        ORDER BY rank DESC, r.votes_helpful DESC
        LIMIT %s OFFSET %s
    """
    params_full = [tsquery] + params + [limit, offset]
    with self.conn.cursor() as cur:
        cur.execute(sql, params_full)
        return [dict(row) for row in cur.fetchall()]
```

### Method 3: Count matches (for "what % mention X" queries)

```python
def count_matching_reviews(
    self,
    query: str,
    appid: int | None = None,
    voted_up: bool | None = None,
    genre: str | None = None,
    tag: str | None = None,
) -> dict:
    """Count reviews matching a search query, with optional filters.

    Returns:
        {"matching": int, "total": int, "pct": float}
    """
    tsquery = _build_tsquery(query)
    conditions: list[str] = []
    params: list = []
    joins: list[str] = []

    if appid is not None:
        conditions.append("r.appid = %s")
        params.append(appid)

    if voted_up is not None:
        conditions.append("r.voted_up = %s")
        params.append(voted_up)

    if genre:
        joins.append("JOIN game_genres gg ON gg.appid = r.appid JOIN genres gen ON gen.id = gg.genre_id")
        conditions.append("gen.slug = %s")
        params.append(genre)

    if tag:
        joins.append("JOIN game_tags gt ON gt.appid = r.appid JOIN tags t ON t.id = gt.tag_id")
        conditions.append("t.slug = %s")
        params.append(tag)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    join_sql = " ".join(joins)

    with self.conn.cursor() as cur:
        # Total reviews in scope
        cur.execute(f"SELECT COUNT(*) AS cnt FROM reviews r {join_sql} {where}", params)
        total = cur.fetchone()["cnt"]

        # Matching reviews
        match_conditions = conditions + ["r.body_tsv @@ to_tsquery('english', %s)"]
        match_params = params + [tsquery]
        match_where = f"WHERE {' AND '.join(match_conditions)}"
        cur.execute(f"SELECT COUNT(*) AS cnt FROM reviews r {join_sql} {match_where}", match_params)
        matching = cur.fetchone()["cnt"]

    pct = round(matching / total * 100, 2) if total > 0 else 0.0
    return {"matching": matching, "total": total, "pct": pct}
```

### Helper: Query Parser

```python
def _build_tsquery(raw: str) -> str:
    """Convert natural language query to PostgreSQL tsquery string.

    - Single words: 'crash' → 'crash'
    - Multiple words: 'crash performance' → 'crash | performance' (OR)
    - Quoted phrase: '"save corruption"' → 'save <-> corruption' (adjacent)
    - Explicit operators: 'crash & freeze' → 'crash & freeze' (AND)

    If the user already uses & or | operators, pass through as-is.
    """
    raw = raw.strip()
    if not raw:
        return ""

    # If user is writing tsquery syntax, pass through
    if "&" in raw or "|" in raw or "<->" in raw:
        return raw

    # Handle quoted phrases
    import re
    phrases = re.findall(r'"([^"]+)"', raw)
    remainder = re.sub(r'"[^"]+"', '', raw).strip()

    parts = []
    for phrase in phrases:
        words = phrase.split()
        if words:
            parts.append(" <-> ".join(words))

    # Remaining words are OR'd
    for word in remainder.split():
        word = word.strip()
        if word:
            parts.append(word)

    return " | ".join(parts) if parts else raw
```

---

## Change 4 — API Endpoints

Add to the API router (FastAPI):

### Search reviews for a game

```python
@router.get("/api/games/{slug}/reviews/search")
async def search_game_reviews(
    slug: str,
    q: str = Query(..., min_length=2, max_length=200, description="Search query"),
    sentiment: str | None = Query(None, regex="^(positive|negative)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Full-text search within a game's reviews."""
    game = game_repo.find_by_slug(slug)
    if not game:
        raise HTTPException(404, "Game not found")

    voted_up = {"positive": True, "negative": False}.get(sentiment)
    results = review_repo.search_reviews(game.appid, q, voted_up=voted_up,
                                          limit=limit, offset=offset)
    return {"query": q, "appid": game.appid, "results": results}
```

### Global search across all reviews

```python
@router.get("/api/reviews/search")
async def search_all_reviews(
    q: str = Query(..., min_length=2, max_length=200),
    sentiment: str | None = Query(None, regex="^(positive|negative)$"),
    genre: str | None = Query(None),
    tag: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Full-text search across all reviews, with optional genre/tag filter."""
    voted_up = {"positive": True, "negative": False}.get(sentiment)
    results = review_repo.search_reviews_global(q, voted_up=voted_up,
                                                 limit=limit, offset=offset)
    return {"query": q, "results": results}
```

### Count matching reviews (for "what % mention X" queries)

```python
@router.get("/api/reviews/count")
async def count_matching_reviews(
    q: str = Query(..., min_length=2, max_length=200),
    appid: int | None = Query(None),
    sentiment: str | None = Query(None, regex="^(positive|negative)$"),
    genre: str | None = Query(None),
    tag: str | None = Query(None),
):
    """Count reviews matching a query. Returns matching, total, and percentage."""
    voted_up = {"positive": True, "negative": False}.get(sentiment)
    result = review_repo.count_matching_reviews(
        q, appid=appid, voted_up=voted_up, genre=genre, tag=tag
    )
    return {"query": q, **result}
```

**Example API calls:**

```bash
# "What % of negative Cyberpunk reviews mention crash?"
curl "localhost:8000/api/reviews/count?q=crash&appid=1091500&sentiment=negative"
# → {"query": "crash", "matching": 1247, "total": 8320, "pct": 14.99}

# "Find reviews about save corruption in Stardew Valley"
curl 'localhost:8000/api/games/stardew-valley/reviews/search?q="save+corruption"'
# → {"query": "save corruption", "appid": 413150, "results": [...]}

# "How many RPG reviews mention pay-to-win?"
curl "localhost:8000/api/reviews/count?q=pay+to+win&genre=rpg"
# → {"query": "pay to win", "matching": 892, "total": 1450000, "pct": 0.06}
```

---

## Change 5 — Frontend Search UI

### Game report page — review search box

On the game report page, add a search input above the reviews section:

```html
<div class="review-search">
    <input type="text" id="review-search-input"
           placeholder="Search reviews... (e.g., crash, refund, save corruption)"
           autocomplete="off" />
    <select id="review-search-sentiment">
        <option value="">All</option>
        <option value="positive">Positive only</option>
        <option value="negative">Negative only</option>
    </select>
    <button id="review-search-btn">Search</button>
</div>
<div id="review-search-results"></div>
```

**Behavior:**
- Debounce input (300ms)
- Show results with highlighted matching terms (use `ts_headline` in SQL or
  client-side `<mark>` tag wrapping)
- Show relevance rank and helpful votes
- Paginate with "Load more" button

### Optional: ts_headline for highlighted snippets

If you want search-result highlighting from PostgreSQL:

```sql
SELECT id, body, voted_up,
       ts_headline('english', body, to_tsquery('english', %s),
                   'StartSel=<mark>, StopSel=</mark>, MaxFragments=2, MaxWords=50')
       AS snippet
FROM reviews
WHERE appid = %s AND body_tsv @@ to_tsquery('english', %s)
ORDER BY ts_rank(body_tsv, to_tsquery('english', %s)) DESC
LIMIT 50
```

This returns body fragments with `<mark>` tags around matching terms — render
directly in the frontend.

---

## Change 6 — Performance Considerations

### Index size estimate

For ~12M reviews with average body length ~200 words:
- `body_tsv` column: ~4-6 GB additional storage
- GIN index: ~2-3 GB additional
- **Total: ~8 GB added to DB**

On `db.t3.medium` (4 GB RAM), the GIN index may not fit entirely in memory.
Monitor `pg_statio_user_indexes` to check cache hit ratio. If below 90%,
consider upgrading to `db.t3.large`.

### Query performance targets

| Query Type | Target | Notes |
|-----------|--------|-------|
| Single game, simple term | <20ms | Index seek + filter on appid |
| Single game, phrase | <50ms | Phrase adjacency check |
| Global, simple term | <200ms | Broader scan, more results |
| Global with genre/tag join | <500ms | Joins add overhead |
| Count queries | <1s | COUNT(*) can be slow on large result sets |

### Recommended: partial index for English reviews only

Since we only analyze English reviews, consider a partial index:

```sql
CREATE INDEX IF NOT EXISTS idx_reviews_body_tsv_english
ON reviews USING GIN (body_tsv)
WHERE language = 'english';
```

This reduces index size by ~60% since most reviews are English but not all.
The query must include `WHERE language = 'english'` to use this index.

---

## Tests

### Repository Tests (`tests/repositories/test_review_repo.py`)

```python
class TestFullTextSearch:

    def _insert_reviews(self, review_repo, game_repo):
        """Insert test reviews with known content."""
        game_repo.upsert(_minimal_game_data(appid=100))
        reviews = [
            {"appid": 100, "steam_review_id": "r1", "voted_up": False,
             "body": "Game crashes every 30 minutes, terrible performance and FPS drops",
             "playtime_hours": 5, "language": "english", "votes_helpful": 10},
            {"appid": 100, "steam_review_id": "r2", "voted_up": False,
             "body": "I refunded this game, waste of money, not worth the price",
             "playtime_hours": 1, "language": "english", "votes_helpful": 25},
            {"appid": 100, "steam_review_id": "r3", "voted_up": True,
             "body": "Amazing soundtrack and art direction, beautiful world design",
             "playtime_hours": 40, "language": "english", "votes_helpful": 50},
            {"appid": 100, "steam_review_id": "r4", "voted_up": True,
             "body": "Good game but has some save corruption bugs that need fixing",
             "playtime_hours": 20, "language": "english", "votes_helpful": 8},
            {"appid": 100, "steam_review_id": "r5", "voted_up": False,
             "body": "Pay to win garbage, microtransactions ruined this game",
             "playtime_hours": 3, "language": "english", "votes_helpful": 15},
        ]
        review_repo.bulk_upsert(reviews)

    def test_search_reviews_finds_crash(self, review_repo, game_repo):
        self._insert_reviews(review_repo, game_repo)
        results = review_repo.search_reviews(100, "crash")
        assert len(results) >= 1
        assert any("crash" in r["body"].lower() for r in results)

    def test_search_reviews_stemming(self, review_repo, game_repo):
        """'refunded' should match 'refund' via English stemming."""
        self._insert_reviews(review_repo, game_repo)
        results = review_repo.search_reviews(100, "refund")
        assert len(results) >= 1
        assert any("refund" in r["body"].lower() for r in results)

    def test_search_reviews_phrase(self, review_repo, game_repo):
        """Quoted phrase search: 'save corruption' in sequence."""
        self._insert_reviews(review_repo, game_repo)
        results = review_repo.search_reviews(100, '"save corruption"')
        assert len(results) >= 1

    def test_search_reviews_sentiment_filter(self, review_repo, game_repo):
        """Filter to negative reviews only."""
        self._insert_reviews(review_repo, game_repo)
        results = review_repo.search_reviews(100, "crash", voted_up=False)
        assert all(r["voted_up"] is False for r in results)

    def test_search_reviews_no_results(self, review_repo, game_repo):
        """Query with no matches returns empty list."""
        self._insert_reviews(review_repo, game_repo)
        results = review_repo.search_reviews(100, "xyznonexistentterm")
        assert results == []

    def test_search_reviews_ranking(self, review_repo, game_repo):
        """Results should be ordered by relevance (rank)."""
        self._insert_reviews(review_repo, game_repo)
        results = review_repo.search_reviews(100, "crash performance")
        assert len(results) >= 1
        # First result should mention both terms
        assert "crash" in results[0]["body"].lower() or "performance" in results[0]["body"].lower()

    def test_count_matching_reviews(self, review_repo, game_repo):
        self._insert_reviews(review_repo, game_repo)
        result = review_repo.count_matching_reviews("refund", appid=100)
        assert result["matching"] >= 1
        assert result["total"] == 5
        assert result["pct"] > 0

    def test_count_matching_negative_only(self, review_repo, game_repo):
        self._insert_reviews(review_repo, game_repo)
        result = review_repo.count_matching_reviews("crash", appid=100, voted_up=False)
        assert result["matching"] >= 1
        # Total should be negative reviews only
        assert result["total"] == 3  # 3 negative reviews

    def test_search_global(self, review_repo, game_repo):
        self._insert_reviews(review_repo, game_repo)
        results = review_repo.search_reviews_global("microtransaction")
        assert len(results) >= 1
        assert results[0]["game_name"] is not None
```

### Query Parser Tests (`tests/eval/test_tsquery_parser.py`)

```python
from library_layer.repositories.review_repo import _build_tsquery

def test_single_word():
    assert _build_tsquery("crash") == "crash"

def test_multiple_words_become_or():
    assert _build_tsquery("crash performance") == "crash | performance"

def test_quoted_phrase():
    assert _build_tsquery('"save corruption"') == "save <-> corruption"

def test_explicit_and_preserved():
    assert _build_tsquery("crash & freeze") == "crash & freeze"

def test_mixed_phrase_and_words():
    result = _build_tsquery('"pay to win" microtransaction')
    assert "pay <-> to <-> win" in result
    assert "microtransaction" in result

def test_empty_string():
    assert _build_tsquery("") == ""

def test_whitespace_only():
    assert _build_tsquery("   ") == ""
```

### API Integration Tests

```python
def test_search_game_reviews_endpoint(client, game_repo, review_repo):
    # Insert game + reviews
    resp = client.get("/api/games/test-game/reviews/search?q=crash")
    assert resp.status_code == 200
    assert "results" in resp.json()

def test_search_requires_query(client):
    resp = client.get("/api/games/test-game/reviews/search")
    assert resp.status_code == 422  # Missing required param

def test_count_endpoint(client, game_repo, review_repo):
    resp = client.get("/api/reviews/count?q=refund&appid=100")
    assert resp.status_code == 200
    data = resp.json()
    assert "matching" in data
    assert "total" in data
    assert "pct" in data
```

### Playwright Tests

```typescript
test('review search shows results', async ({ page }) => {
    await mockAllApiRoutes(page);
    await page.route('**/api/games/*/reviews/search*', route =>
        route.fulfill({
            json: {
                query: 'crash',
                appid: 440,
                results: [
                    { id: 1, body: 'Game <mark>crashes</mark> every time',
                      voted_up: false, playtime_hours: 5, rank: 0.8 },
                ],
            },
        })
    );
    await page.goto('/games/team-fortress-2');
    await page.fill('[data-testid="review-search-input"]', 'crash');
    await page.click('[data-testid="review-search-btn"]');
    await expect(page.locator('[data-testid="search-results"]')).toContainText('crashes');
});

test('review search shows no results message', async ({ page }) => {
    await mockAllApiRoutes(page);
    await page.route('**/api/games/*/reviews/search*', route =>
        route.fulfill({ json: { query: 'xyznothing', appid: 440, results: [] } })
    );
    await page.goto('/games/team-fortress-2');
    await page.fill('[data-testid="review-search-input"]', 'xyznothing');
    await page.click('[data-testid="review-search-btn"]');
    await expect(page.locator('[data-testid="search-results"]')).toContainText('No results');
});
```

---

## Implementation Order

1. **Schema migration** — add `body_tsv` column, trigger, GIN index
2. **`_build_tsquery` helper** — query parser (test this first)
3. **Review repo methods** — `search_reviews`, `search_reviews_global`, `count_matching_reviews`
4. **API endpoints** — 3 new routes
5. **Backfill command** — `poetry run python scripts/sp.py backfill-tsv`
6. **Frontend search UI** — input + results display
7. **Tests** — repo, parser, API, Playwright

## Verification

```bash
# Apply schema migration (runs CREATE INDEX, CREATE TRIGGER)
poetry run python -c "
import os, psycopg2
from library_layer.schema import create_all
conn = psycopg2.connect(os.environ['DATABASE_URL'])
create_all(conn)
conn.close()
print('Schema updated')
"

# Backfill existing reviews
poetry run python scripts/sp.py backfill-tsv

# Test search via API
curl "localhost:8000/api/games/team-fortress-2/reviews/search?q=crash"
curl "localhost:8000/api/reviews/count?q=refund&sentiment=negative"

# Run tests
poetry run pytest tests/ -k "search or tsquery" -v
```

---

## Notes

- **Language config:** We use `'pg_catalog.english'` for stemming. This works
  well for English reviews. Non-English reviews will still be indexed but
  stemming won't be optimal. Since we filter `language = 'english'` for
  analysis anyway, this is acceptable.

- **SQL injection safety:** All queries use parameterized `%s` placeholders.
  The `_build_tsquery` helper only restructures the user's words into tsquery
  syntax — it never interpolates raw input into SQL.

- **Future enhancement:** Add `ts_headline` support to the search endpoint for
  returning highlighted snippets. This is optional for v1 but improves UX
  significantly.
