# Denormalize sentiment_score & hidden_gem_score onto games table

## Problem

The `list_games()` catalog query does `LEFT JOIN reports` solely to extract two floats from a
5-20KB JSONB column. PostgreSQL must deTOAST the entire JSONB blob for each `->>'key'`
extraction — no partial deTOAST exists. On a t4g.micro with ~256MB shared_buffers, TOAST chunks
evict games table pages from the buffer cache, causing DataFileRead/BufferIO waits.

## Solution

Denormalize `sentiment_score` and `hidden_gem_score` onto the `games` table. Eliminate the
`LEFT JOIN reports` from the catalog query entirely. This follows the existing codebase pattern:
`games` already has denormalized computed values (`review_velocity_lifetime`, `positive_pct`,
`review_count`).

## Why not alternatives

| Alternative | Why not |
|-------------|---------|
| Expression index on JSONB | Cannot do index-only scans for SELECT projections — deTOAST still happens |
| Covering index with INCLUDE | INCLUDE doesn't support expressions |
| Generated columns on reports | LEFT JOIN remains — still reads reports pages |
| Generated columns on games | Cannot reference other tables |
| Separate scores table | Still requires a JOIN |
| Redis/ElastiCache | $12+/month, overkill at 160k rows |

## Changes

1. **Migration 0017**: `ALTER TABLE games ADD COLUMN sentiment_score REAL` + `hidden_gem_score REAL` + backfill from reports
2. **Migration 0018**: `CREATE INDEX CONCURRENTLY` on both score columns
3. **report_repo.py**: Sync scores to games on upsert (same transaction)
4. **game_repo.py**: Drop `LEFT JOIN reports`, use `g.sentiment_score` / `g.hidden_gem_score` directly
5. **schema.py**: Update reference DDL
6. **Tests**: Update sentiment filter tests

## Expected result

Catalog query becomes a pure `games`-only indexed scan — no JOIN, no JSONB, no TOAST. Instant
even on cold cache.

## Sources

- PostgreSQL TOAST: full decompression required for any `->>'key'` access
- JSONB extraction performance: 5-12x buffer amplification for TOAST (pganalyze)
- Expression index limitations: cannot do index-only scans for projections
- Citus Data: pre-compute expensive derivations for catalog queries
