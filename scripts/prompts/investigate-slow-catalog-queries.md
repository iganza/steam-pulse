# Investigate: Catalog Query Performance + DB Connection Pooling

## Background

Production PostgreSQL (RDS, us-west-2) is showing 20+ active connections with multiple
connections stuck on `BufferIO` waits for 2-3 minutes. Two root causes have been identified:

1. **Missing indexes** — catalog/genre browse queries are slow due to per-row EXISTS subquery scans
2. **Connection saturation** — Lambda warm instances each hold a persistent psycopg2 connection
   (module-level caching). With 12 spokes + ingest + API Lambda all running concurrently, the
   connection count hits 40-60+. RDS t4g.micro `max_connections` is ~85.

The DB tunnel is open at:
```
host=127.0.0.1 port=5433 dbname=production_steampulse user=postgres sslmode=require
PGPASSWORD=8uzRYfsrDD1B
```

---

## Part 1: Index Investigation & Fixes

### The slow queries (from the catalog/genre browse API endpoint)

```sql
-- Query 1: catalog listing (runs on every page load)
SELECT g.appid, g.name, g.slug, g.developer, g.header_image,
       g.review_count, g.review_count_english, g.positive_pct, g.price_usd, g.is_free,
       g.release_date, g.deck_compatibility,
       r.report_json->>'hidden_gem_score' AS hidden_gem_score,
       r.report_json->>'sentiment_score'  AS sentiment_score,
       EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70) AS is_early_access
FROM games g
LEFT JOIN reports r ON r.appid = g.appid
WHERE ... [genre/tag/sort filters]
ORDER BY ... LIMIT 24 OFFSET ...;

-- Query 2: catalog count for pagination (also runs every page load, separately)
SELECT COUNT(*) AS cnt
FROM games g
LEFT JOIN reports r ON r.appid = g.appid
WHERE 1=1
  AND EXISTS (
    SELECT 1 FROM game_genres gg
    JOIN genres gn ON gg.genre_id = gn.id
    WHERE gg.appid = g.appid AND gn.slug = 'indie'
  )
  AND g.review_count >= 200;
```

### What to do

1. Run `EXPLAIN (ANALYZE, BUFFERS)` on both queries against production to confirm the bottleneck.

2. Check existing indexes:
   ```sql
   SELECT tablename, indexname, indexdef
   FROM pg_indexes
   WHERE tablename IN ('game_genres', 'genres', 'reports', 'games', 'game_tags', 'tags')
   ORDER BY tablename, indexname;
   ```

3. Find the repository/service running these queries:
   - `src/library-layer/library_layer/repositories/` — likely `game_repo.py` or `catalog_repo.py`
   - Also check `src/lambda-functions/lambda_functions/api/` for route handlers

4. Check existing migration files in `src/library-layer/library_layer/migrations/` to understand
   what indexes were already created and what the next migration number should be.

5. **Implement fixes:**
   - Add a new yoyo migration file with `CREATE INDEX CONCURRENTLY` statements for any missing indexes.
     Candidates: `game_genres(appid)`, `game_genres(genre_id)`, `genres(slug)`, `reports(appid)`,
     `game_tags(appid)`, `game_tags(tag_id)`, `tags(slug)`.
   - Consider rewriting the double count+list query into a single query using `COUNT(*) OVER ()` window
     function to eliminate one round-trip per page load.
   - Consider adding a partial index on `games(review_count)` if range filters are common.

6. Run `EXPLAIN (ANALYZE, BUFFERS)` again after adding indexes to confirm improvement.

**Constraint:** Follow the project migration conventions — migrations live in
`src/library-layer/library_layer/migrations/`, use yoyo-migrations format, are numbered sequentially.
No ORM — raw SQL only. Use `CREATE INDEX CONCURRENTLY` so production isn't locked during index builds.

---

## Part 2: RDS Proxy for Connection Pooling

### The problem

Each warm Lambda invocation holds a persistent psycopg2 connection at module level (this is
intentional for warm reuse). Under concurrent load — bulk review ingest (12 spokes) + API traffic —
connections pile up. RDS `max_connections` on a small instance is limited.

### The fix: AWS RDS Proxy

RDS Proxy sits between Lambda and RDS. Lambda connects to the Proxy endpoint (same interface,
same psycopg2 code — just a different hostname). The Proxy maintains a small real connection pool
to RDS and multiplexes many Lambda connections through it.

**Benefits:**
- Lambda can have 100+ warm instances; only 5-10 real DB connections are needed
- Proxy handles connection draining on RDS failover (improves availability)
- Cost: ~$0.015/connection-hour (~$11/month for a small proxy)
- Zero code changes required — just update the DB hostname in the secret

### What to do

1. Read `infra/stacks/data_stack.py` to understand the current RDS setup (instance type, VPC,
   security groups, subnet group, secret name).

2. Read `infra/stacks/compute_stack.py` to understand which Lambda roles need DB access.

3. Add `DatabaseProxy` construct to `data_stack.py`:
   - Attach to the existing RDS instance
   - Use the existing `db_secret` for IAM auth or Secrets Manager auth
   - Place in the same VPC/subnets as RDS
   - Output the proxy endpoint to SSM Parameter Store at
     `/steampulse/{env}/data/db-proxy-endpoint`

4. The Lambda functions currently resolve DB credentials from `DB_SECRET_NAME` env var and build
   a connection string. After adding the proxy, the connection string hostname should point to the
   proxy endpoint instead of the RDS instance endpoint. Check `src/library-layer/library_layer/utils/db.py`
   to see how the connection string is built and update accordingly.

5. Update IAM roles to allow `rds-db:connect` on the proxy (required for IAM auth), OR keep
   using Secrets Manager auth (simpler — no IAM change needed, proxy just forwards credentials).

6. Staging environment: add proxy there too so it's tested before production.

**Constraint:** Follow CDK rules in CLAUDE.md — no physical resource names unless cross-region,
use `grant_*` methods for IAM, `termination_protection` is already set on `data_stack`.
The proxy should be added to `DataStack`, not a new stack.

---

## Table sizes for context
- `games`: ~159k rows
- `reviews`: ~3.6M rows
- `reports`: ~7.3k rows
- `game_genres`: unknown (estimate ~500k rows)
- `game_tags`: unknown (estimate ~2M rows)

## Success criteria
- Catalog page query completes in <50ms with EXPLAIN output showing index scans, not seq scans
- No `BufferIO` waits under normal concurrent API load
- Connection count stays below 20 even with 10+ warm Lambda instances (via RDS Proxy)
