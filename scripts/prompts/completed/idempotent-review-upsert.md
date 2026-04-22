# Plan: Make review upsert a no-op when nothing changed

## Context

The tiered review-refresh schedule (`RefreshReviewsRule`, from
`tiered-refresh-scheduling.md`) was disabled in production because enabling it
drained the `t4g.small` RDS CPU credit budget. Dispatch volume is not the
problem — the tiered design caps enqueues at ~500/hr and per-game fetch at
10k reviews. The problem is how much work each individual row-write does.

Root cause in `src/library-layer/library_layer/repositories/review_repo.py:51-60`:

```sql
ON CONFLICT (steam_review_id) DO UPDATE SET
    voted_up                    = EXCLUDED.voted_up,
    playtime_hours              = EXCLUDED.playtime_hours,
    body                        = EXCLUDED.body,
    ... (6 more columns)
```

There is no `WHERE` guard on the `DO UPDATE`. Every conflicting row gets
rewritten even when every column is byte-identical to what's already stored.
Postgres writes a new MVCC tuple, a new WAL record, and updates every B-tree
on the table (PK + 6 secondary indexes on `appid`, `playtime_hours`,
`votes_helpful`, `votes_funny`, etc. — `0001_initial_schema.sql:82-97`).

Steam returns reviews newest-first, ~100 per page. Each refresh dispatch
fetches (up to) one page before early-stop fires (`ingest_handler.py:239-248`).
On a game that hasn't grown, ~100% of that page is already in the DB verbatim.
With 6 concurrent ingest Lambdas (`compute_stack.py:448-488`) and a t4g.small's
small credit budget, even modest refresh traffic exhausts credits — not because
we're writing too many genuinely-new reviews, but because we're rewriting rows
that didn't change.

---

## Goal

Make `bulk_upsert` a true no-op at the Postgres level when Steam's current
snapshot of a review matches what's already stored. Unblock re-enabling
`RefreshReviewsRule` without needing to resize RDS.

---

## Design

Add a `WHERE` clause to the `DO UPDATE` that guards on `IS DISTINCT FROM`
across all mutable columns. When the `WHERE` fails, Postgres skips the
update entirely — no tuple write, no WAL, no index maintenance.

This is the standard Postgres idiom for idempotent upserts.

- **Identical rows** (the ~80-90% case on refresh): zero cost beyond the
  index lookup to detect the conflict. Credit-neutral.
- **Rows whose vote counts / playtime genuinely changed**: one UPDATE,
  same as today.
- **Genuinely new rows**: one INSERT, same as today.

Columns in the guard: all nine mutable columns in the current `DO UPDATE SET`
(`voted_up`, `playtime_hours`, `body`, `author_steamid`, `language`,
`votes_helpful`, `votes_funny`, `written_during_early_access`, `received_for_free`).
`posted_at` is append-only per review (Steam never rewrites it) and is
excluded from the guard; `appid` and `steam_review_id` are identity.

---

## Changes

### 1. `src/library-layer/library_layer/repositories/review_repo.py`

Replace the SQL body in `bulk_upsert` (lines 46-60) with:

```sql
INSERT INTO reviews (
    appid, steam_review_id, author_steamid, voted_up, playtime_hours,
    body, posted_at, language, votes_helpful, votes_funny,
    written_during_early_access, received_for_free
) VALUES %s
ON CONFLICT (steam_review_id) DO UPDATE SET
    voted_up                    = EXCLUDED.voted_up,
    playtime_hours              = EXCLUDED.playtime_hours,
    body                        = EXCLUDED.body,
    author_steamid              = EXCLUDED.author_steamid,
    language                    = EXCLUDED.language,
    votes_helpful               = EXCLUDED.votes_helpful,
    votes_funny                 = EXCLUDED.votes_funny,
    written_during_early_access = EXCLUDED.written_during_early_access,
    received_for_free           = EXCLUDED.received_for_free
WHERE (
    reviews.voted_up,
    reviews.playtime_hours,
    reviews.body,
    reviews.author_steamid,
    reviews.language,
    reviews.votes_helpful,
    reviews.votes_funny,
    reviews.written_during_early_access,
    reviews.received_for_free
) IS DISTINCT FROM (
    EXCLUDED.voted_up,
    EXCLUDED.playtime_hours,
    EXCLUDED.body,
    EXCLUDED.author_steamid,
    EXCLUDED.language,
    EXCLUDED.votes_helpful,
    EXCLUDED.votes_funny,
    EXCLUDED.written_during_early_access,
    EXCLUDED.received_for_free
)
```

The column list in the row-wise comparison matches the `DO UPDATE SET` list
exactly — easier to keep in sync than nine paired `OR` clauses.

No other code change in this file; the method signature and return value are
unchanged. Callers are unaffected.

### 2. Tests

`tests/repositories/test_review_repo.py` (per `feedback_test_db.md`, against
`steampulse_test`).

Two integration tests:

- **`test_bulk_upsert_identical_rows_is_noop`** — insert one review, capture
  its `ctid` and `xmin` via `SELECT ctid, xmin FROM reviews WHERE
  steam_review_id = %s`, call `bulk_upsert` again with the identical payload,
  assert `ctid` and `xmin` unchanged. That is the Postgres-level proof that
  no tuple write happened.
- **`test_bulk_upsert_vote_change_updates_row`** — insert one review, call
  `bulk_upsert` with the same row but `votes_helpful` incremented, assert
  new value is visible and `ctid` changed. Regression guard that the `WHERE`
  doesn't over-skip.

Existing inserts-only tests for `bulk_upsert` remain valid.

---

## Out of scope

- **Delta-gated dispatch** (`scripts/prompts/delta-gated-review-crawl.md`).
  Still a good follow-up — it saves the Steam fetch and the round-trip for
  games with no growth — and composes cleanly with this change. Worth doing
  after `RefreshReviewsRule` has been re-enabled and observed stable. Not
  needed to unblock the schedule, because with the no-op guard in place, a
  dispatch against an unchanged game is nearly free end-to-end.
- **RDS resize / parameter tuning.** Not needed once the write amplifier is
  removed.
- **Reducing ingest Lambda concurrency** (currently 6). Keep as-is; the
  credit drain was a work-per-write problem, not a concurrency problem.
- **`DO NOTHING` instead of guarded `DO UPDATE`**. Considered and rejected:
  we genuinely need vote-count and playtime updates to propagate for active
  games.

---

## Files to modify

- `src/library-layer/library_layer/repositories/review_repo.py` — SQL edit
  in `bulk_upsert`.
- `tests/repositories/test_review_repo.py` — add the two tests above.

No migration. No infra change. No config change.

---

## Verification

### Local

```bash
poetry run pytest tests/repositories/test_review_repo.py -v
poetry run pytest tests/repositories/ -v
```

### Production sanity check (after deploy, before re-enabling the rule)

1. Pick a Tier-S wedge game. Note its `reviews_completed_at` and row count.
2. `poetry run python scripts/sp.py refresh-reviews <appid>` — force a
   re-crawl while the schedule is still disabled.
3. In psql:
   ```sql
   SELECT n_tup_ins, n_tup_upd, n_tup_hot_upd
   FROM pg_stat_user_tables WHERE relname = 'reviews';
   ```
   Compare before vs. after: `n_tup_ins` grows only by the count of
   genuinely new reviews; `n_tup_upd` grows only by the count of reviews
   whose votes actually changed. Neither should grow by the full batch size.

### Re-enable `RefreshReviewsRule`

Once the sanity check confirms a clean refresh, flip
`enabled=True` on the rule in `infra/stacks/compute_stack.py`, deploy, and
watch for 48h:

- **CloudWatch → RDS → `CPUCreditBalance`**: should stay flat or trend up
  during off-hours instead of decaying.
- **`oldest_due_age_hours`** in the `refresh_reviews enqueued` log line
  (from `tiered-refresh-scheduling.md` §5): should stay within the tier's
  window (1 / 3 / 14 days) and not drift upward.

If both look healthy, the unblock is complete and the delta-gated-crawl
follow-up becomes optional rather than urgent.
