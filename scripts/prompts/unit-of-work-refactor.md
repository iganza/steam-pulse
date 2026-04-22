# Unit-of-Work Refactor — Read / Process / Write Phases

## Context

Today every repository write method ends in `self.conn.commit()`, so a single ingest message commits 3–6 times, each an `fsync`. Beyond the fsync cost, the bigger problem is shape: code interleaves DB chatter with in-memory work, so the connection sits in an active transaction while Python does `json.loads`, dict assembly, event diffing, etc. That's the textbook **"idle in transaction"** anti-pattern — it holds row locks, bloats TOAST/MVCC, and keeps the conn from being useful to anyone else.

Goal: restructure every business operation into three explicit phases — **read → process → write** — where:

1. **Read:** all DB data the operation needs is loaded up front over a short autocommit window, then the connection is effectively released (autocommit on, no open txn).
2. **Process:** pure Python. No DB access. Assembles the final write plan in memory.
3. **Write:** a single transaction opens, replays all staged writes in order, commits once.

The service layer **must not know** any of this is happening. Services get a `UnitOfWork` that exposes repositories. Reads on the UoW return data; writes on the UoW stage into an in-memory command list. On context exit, the UoW flushes atomically. Everything about autocommit, staging, fsync coalescing, and event publishing lives inside the UoW — invisible to the service.

This prompt **supersedes** `scripts/prompts/commit-boundary-ownership.md`, which is a narrower version of this idea. Implement this one instead.

---

## Theory / background

### The pattern is Unit of Work (Fowler, PoEAA)

Canonical Python reference is the "Cosmic Python" book, chapters 6–7 (Unit of Work) and 12 (CQRS). The write-side UoW is:

- A context manager.
- Owns the connection / transaction boundary.
- Exposes repositories scoped to itself.
- Flushes all staged changes on commit; rolls back on exception.

The refinement we're adding — **reads are live, writes are staged** — is a pragmatic shortcut. The full UoW pattern stages everything behind an "identity map" so repeated reads hit cache and writes are visible to same-UoW reads. That's expensive to build and unnecessary here: our services naturally follow a read-first-then-write shape. We codify that as a discipline and skip the identity map.

### Idle in transaction is real

psycopg2's default is `autocommit=False`. The moment any cursor issues a statement, a transaction begins and stays open until `commit()` / `rollback()`. Any Python work done between the first `SELECT` and the final `COMMIT` is time the connection holds locks and prevents the bgwriter/autovacuum from reclaiming tuples on touched rows. Our current pattern (read → `commit()` inside the repo → process → write → `commit()` again) accidentally does the right thing on the boundary but at the cost of 3–6 commits per message. The UoW should explicitly enter **autocommit mode during reads** and only switch to transactional mode for the flush.

### Transactional outbox (bonus, related)

The codebase currently publishes SNS events **outside** the DB commit (`crawl_service.py:_publish_crawl_app_events`). If the Lambda dies between the DB commit and the SNS publish, the state change persists but the event is lost. The full remedy is the **Transactional Outbox Pattern**: write events into an `outbox` table inside the same txn as the state change, then a separate process forwards them to SNS. Out of scope for this prompt — but the UoW we build should **stage SNS publishes too**, firing them only after the DB commit succeeds. That's the "light outbox" — gives atomic-to-txn semantics without a durable outbox table. Durable outbox is a follow-up if event loss shows up in practice.

### CQRS — not this

Not the right pattern here. CQRS splits reads from writes at the data-store level (e.g., a read replica serving all queries, a write master taking all commands). We're nowhere near that scale, and a single-instance Postgres with denormalized matviews already plays the same role. Mentioning to rule it out.

---

## The design

### UnitOfWork skeleton

```python
# library_layer/uow.py
from dataclasses import dataclass
from typing import Any, Callable

@dataclass
class Command:
    """A staged write. Replayed inside the flush transaction."""
    sql: str
    params: tuple | list | dict
    page_size: int | None = None       # if set, emit via execute_values
    on_result: Callable[[Any], None] | None = None   # handle RETURNING

@dataclass
class PendingEvent:
    topic_arn: str
    event: Any     # pydantic event model

class UnitOfWork:
    def __init__(self, get_conn, sns_client):
        self._get_conn = get_conn
        self._sns = sns_client
        self._writes: list[Command] = []
        self._events: list[PendingEvent] = []
        # repos constructed here — each takes self so it can stage
        self.games    = _GameRepo(self)
        self.reviews  = _ReviewRepo(self)
        self.catalog  = _CatalogRepo(self)
        self.tags     = _TagRepo(self)
        # ...

    def __enter__(self):
        conn = self._get_conn()
        conn.autocommit = True    # reads don't open a txn
        return self

    def __exit__(self, exc_type, exc_val, tb):
        conn = self._get_conn()
        if exc_type is not None:
            # Processing failed — nothing to roll back at DB level (autocommit was on)
            self._writes.clear()
            self._events.clear()
            return False
        try:
            self._flush(conn)
        except Exception:
            # Flush failed mid-txn — conn.rollback() happens inside _flush
            raise
        # Only fire events after commit succeeds
        self._publish_events()
        return False

    def _flush(self, conn) -> None:
        if not self._writes:
            return
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                for cmd in self._writes:
                    if cmd.page_size is not None:
                        from psycopg2.extras import execute_values
                        execute_values(cur, cmd.sql, cmd.params,
                                       page_size=cmd.page_size,
                                       fetch=cmd.on_result is not None)
                        if cmd.on_result:
                            cmd.on_result(cur.fetchall())
                    else:
                        cur.execute(cmd.sql, cmd.params)
                        if cmd.on_result:
                            cmd.on_result(cur.fetchall())
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.autocommit = True
            self._writes.clear()

    def _publish_events(self) -> None:
        for evt in self._events:
            try:
                publish_event(self._sns, evt.topic_arn, evt.event)
            except EventPublishError:
                # Post-commit event loss — log + flag for outbox follow-up
                logger.warning("Post-commit event publish failed", ...)
        self._events.clear()

    # Internal API used by repos
    def _stage(self, cmd: Command) -> None:
        self._writes.append(cmd)

    def _stage_event(self, topic_arn: str, event: Any) -> None:
        self._events.append(PendingEvent(topic_arn, event))

    def _live_conn(self):
        return self._get_conn()
```

### Repositories under the UoW

Two method families, clearly distinguished:

**Read methods — execute immediately (live):**

```python
class _ReviewRepo:
    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def find_by_appid(self, appid: int, limit: int = 100) -> list[Review]:
        with self._uow._live_conn().cursor() as cur:
            cur.execute("SELECT ... WHERE appid = %s LIMIT %s", (appid, limit))
            rows = cur.fetchall()
        return [Review.model_validate(dict(r)) for r in rows]
```

**Write methods — stage a Command (deferred):**

```python
    def bulk_upsert(self, reviews: list[dict]) -> None:
        if not reviews:
            return
        rows = [(r["appid"], r["steam_review_id"], ...) for r in reviews]
        self._uow._stage(Command(
            sql="INSERT INTO reviews (...) VALUES %s ON CONFLICT ... DO UPDATE SET ...",
            params=rows,
            page_size=500,
        ))
```

Naming convention enforces discipline: method names starting with `find_`, `get_`, `count_` are live reads; everything else (`upsert`, `set_`, `mark_`, `delete_`, `bulk_*`) is a staged write. A linter rule or test can enforce this.

### Service code before / after

**Before (today):**

```python
def ingest_spoke_metadata(self, appid: int, raw: dict) -> bool:
    existing = self._game_repo.find_by_appid(appid)          # commits implicitly
    game_data = self._build_game_data(appid, raw)
    self._game_repo.upsert(game_data)                         # commit #1
    self._tag_repo.upsert_genres(appid, genres)               # commit #2
    self._tag_repo.upsert_categories(appid, categories)       # commit #3
    self._catalog_repo.set_meta_status(appid, "done", ...)    # commit #4
    self._publish_crawl_app_events(appid, game_data, existing)  # SNS (outside txn)
```

**After (UoW):**

```python
def ingest_spoke_metadata(self, appid: int, raw: dict) -> bool:
    with self._uow_factory() as uow:
        existing = uow.games.find_event_snapshot(appid)        # live read
        game_data = self._build_game_data(appid, raw)          # pure Python
        uow.games.upsert(game_data)                            # staged
        uow.tags.upsert_genres(appid, genres)                  # staged
        uow.tags.upsert_categories(appid, categories)          # staged
        uow.catalog.set_meta_status(appid, "done", ...)        # staged
        uow.events.stage_metadata_ready(appid, game_data, existing)  # staged
    # ← exactly one DB commit happens here, then SNS publishes fire
```

The service became cleaner, *not* more complex. It has no idea what the UoW does internally. `self._uow_factory` is injected at construction time (just like any other dependency); tests pass a fake.

### Coalescing writes (optional, later)

`_flush` can detect adjacent Commands with identical SQL shapes and merge them — e.g., 10 separate `set_meta_status` calls in a batch become one `execute_values`. Not required for v1; the current gains come from "one commit, not six" before we worry about "one INSERT, not ten". Punt on this until metrics justify it.

### Connection lifecycle in Lambda

```
Lambda invocation
  ↓
  get_conn()   # warm-start cached
  ↓
  with UnitOfWork(get_conn, sns) as uow:
      conn.autocommit = True
      # Read phase: reads execute, each in its own autocommit "mini-txn"
      existing = uow.games.find_...(...)
      # Process phase: no DB access
      ...
      # Write phase (all staged so far):
      uow.xxx.upsert(...)
      uow.yyy.set_status(...)
  # ← __exit__:
      conn.autocommit = False
      BEGIN
      <replay staged writes>
      COMMIT
      conn.autocommit = True
      <fire staged events>
```

Between the read phase and the flush, the conn is in **autocommit mode with no active txn**. No locks held. If RDS Proxy is added later, the conn is genuinely returnable to the pool between phases. Today it just sits idle — still a correctness win.

### Rollback / exception semantics

- Exception during read phase: autocommit mode, so no txn to roll back. Staged writes cleared. Events cleared. Propagate.
- Exception during process phase: same as above.
- Exception during flush: single `conn.rollback()` inside `_flush`, staged events cleared, exception propagates. No partial state.
- SNS publish failure (post-commit): logged, event lost (until durable outbox is built). DB state intact.

---

## Service-layer invariants (the "don't leak" discipline)

Services **may**:

- Call `with self._uow_factory() as uow:` to start a business transaction.
- Call `uow.<repo>.<read_method>(...)` to get data.
- Call `uow.<repo>.<write_method>(...)` to stage a change.
- Call `uow.events.stage_<event_name>(...)` to stage an SNS publish.

Services **may not**:

- Import `psycopg2`, `execute_values`, connection objects, or cursors.
- Call `conn.commit()` / `conn.rollback()` / `conn.autocommit = ...`.
- Construct repositories themselves. They come off the UoW only.
- Interleave reads and staged writes where the read depends on the staged write's effect (a read always reflects committed state — read-before-write is the rule).

Tests enforce these invariants:

- A grep test asserts no `conn.commit()` / `conn.rollback()` / `psycopg2` imports appear in `src/library-layer/library_layer/services/`.
- A lint rule: if a service method takes a `conn` parameter, it's a bug.

---

## Migration plan

Total blast radius: ~14 repos × ~5 methods, ~8 services, ~5 handlers, ~all write-touching tests. This is a multi-PR refactor.

Do it incrementally. Don't flip everything at once.

### Phase 0 — scaffold (1 PR, zero behavior change)

1. Create `src/library-layer/library_layer/uow.py` with `UnitOfWork`, `Command`, `PendingEvent`.
2. Create `src/library-layer/library_layer/utils/db.py::transaction` context manager as a stepping-stone — keeps the middle ground viable during migration.
3. Add `tests/test_uow.py` — unit tests for stage/flush/rollback/event ordering against `steampulse_test` DB.
4. No repos or services changed yet.

### Phase 1 — port ingest hot path (1 PR, real behavior change)

The biggest CPU-credit bleeder. Port `_handle_metadata`, `_handle_tags`, `_handle_reviews` in `ingest_handler.py` end-to-end:

1. Build UoW-native versions of `GameRepository`, `TagRepository`, `CatalogRepository`, `ReviewRepository` — one file each, or a new `uow_repos/` subdir until migration finishes.
2. Port `CrawlService.ingest_spoke_metadata`, `ingest_spoke_tags`, `ingest_spoke_reviews` to use `with self._uow_factory() as uow:`.
3. Move SNS publishes into `uow.events.stage_*` calls.
4. Update the three `_handle_*` functions in `ingest_handler.py` to construct a UoW factory once at module scope and pass it to the service.
5. Remove `_catalog_repo`, `_review_repo`, `_tag_repo`, `_crawl_service` module-level singletons that still do per-method commits — or leave them temporarily for the non-ingest code paths.
6. Run `tests/handlers/test_ingest_handler.py` + `tests/services/test_crawl_service.py` + integration smoke against `steampulse_test`.
7. Deploy to staging, watch `Duration.Avg` on `SpokeIngestFn` + RDS `CommitLatency` / `WriteIOPS`.

### Phase 2 — port remaining write paths

One PR per handler, in order of write volume:

- `analysis/handler.py` (Step Function tasks: chunk/merge/synthesize write paths)
- `admin/handler.py` (operator actions)
- `api/handler.py` (waitlist signup, analysis-request ingest)

Each PR: port the relevant service methods, their repos' write methods, and the handler's entry point. Remove that service's `conn.commit()` callsites.

### Phase 3 — cleanup

- Delete any remaining `self.conn.commit()` calls in repo source files.
- Delete the interim `transaction()` helper if still present.
- Delete the old per-method repo constructors that took `get_conn` directly — if any remain.
- Update `scripts/sp.py` and any `scripts/*.py` admin tooling that called repo write methods directly to use a UoW.
- Mark `scripts/prompts/commit-boundary-ownership.md` as superseded (move to `completed/` with a note, or delete).

### Phase 4 — coalescing (optional, metrics-gated)

If PI still shows repeated identical-shape commands being slow, add adjacent-command coalescing in `UnitOfWork._flush`. Until then, don't.

### Phase 5 — durable outbox (optional, incident-gated)

If event-publish failures show up in logs and cause customer-visible inconsistency, build a real `outbox` table + poller Lambda. Until then, the light outbox (fire-after-commit) is sufficient.

---

## Critical files

- **New:** `src/library-layer/library_layer/uow.py` — UoW class, Command, PendingEvent.
- **New:** `src/library-layer/library_layer/uow_repos/*.py` (or rewrite in place) — per-repo classes with `_uow` handle.
- **Modify:** `src/library-layer/library_layer/utils/db.py` — add `transaction` helper (interim).
- **Modify:** every service in `src/library-layer/library_layer/services/*.py` — gradually, phase by phase.
- **Modify:** every handler in `src/lambda-functions/lambda_functions/*/handler.py` — gradually.
- **Modify:** tests in `tests/repositories/`, `tests/services/`, `tests/handlers/` — fixture updates to use UoW.
- **Delete / supersede:** `scripts/prompts/commit-boundary-ownership.md`.

---

## Interactions with in-flight work

- **`scripts/prompts/db-performance-optimizations-v1.md`**: T1-A (TUI `pg_class.reltuples`), T1-B / T1-C (genres/categories N+1 → `execute_values`), T1-D (narrow event-snapshot SELECT) are **independent** of this prompt and can ship first. They reduce round-trip count; UoW reduces commit count. Both wins compound. **T2-A (merge two UPDATEs)** becomes obsolete under UoW — drop it.
- **`scripts/prompts/commit-boundary-ownership.md`**: **superseded by this prompt.** The old prompt is a partial solution (handlers own commits) without the staging + autocommit-between-phases discipline. Don't implement it; implement this instead.
- **`scripts/prompts/delta-gated-review-crawl.md`**: orthogonal. Reduces *how many* ingest messages fire, not *how efficiently* each one executes. Can proceed in parallel.
- **`scripts/prompts/upgrade-rds-instance-class.md`**: downstream of all of the above. If v1 + UoW land and PI still shows I/O-bound DBLoad, then upgrade. Otherwise, defer.

---

## Out of scope

- **Identity map** (same-UoW write-then-read visibility). Read-before-write discipline sidesteps the need.
- **Durable outbox table.** Light outbox (fire-after-commit) is enough until we see loss.
- **CQRS read-replica split.** Single-instance Postgres is fine at current scale.
- **SQLAlchemy migration.** Still psycopg2. Much bigger lift with uncertain gain.
- **psycopg3.** Same argument — bigger lift, not now.
- **Multi-service UoW** (one UoW across multiple services per message). Each service owns its own UoW; nesting is a smell.

---

## Verification

### Unit / integration

- `tests/test_uow.py`: stage-and-flush round-trips data correctly; exception during process phase produces zero writes; exception during flush rolls back atomically; events fire only after successful commit.
- `tests/handlers/test_ingest_handler.py` + `tests/services/test_crawl_service.py`: existing assertions still green against the UoW-ported service.
- New integration test: inject an exception after N staged writes; assert DB state is unchanged AND no SNS publish fired.

### Lint / invariants

- CI check: `grep -r "psycopg2\|conn.commit\|conn.rollback" src/library-layer/library_layer/services/` returns empty.
- CI check: all service method signatures contain no `conn` parameter.

### Post-deploy

- `AWS/Lambda` `Duration.Avg` on `SpokeIngestFn` drops meaningfully on review-heavy batches. Conservative estimate: 10–20%.
- RDS `CommitLatency` and `WriteIOPS` drop proportional to commit-count reduction.
- PI top-SQL: `COMMIT` disappears as a top entry (currently ~0.04 AAS); explicit `BEGIN` may appear but that's fine.
- No increase in SQS DLQ arrivals on `spoke-results-production`.
- `idle in transaction` session count in `pg_stat_activity` stays at zero for SteamPulse roles. (Quick way to verify the autocommit-between-phases is actually working.)

---

## Open questions for the implementer

1. **Multi-PR, multi-week refactor appetite** vs. a cheaper middle-ground (do just the `commit-boundary-ownership` prompt first, then revisit the full UoW later)?
2. **Events-after-commit**: is "light outbox" (fire after commit, best-effort) acceptable, or do you want a durable outbox table as part of Phase 1?
3. **Write-coalescing** (adjacent identical-shape commands): pragmatic skip for v1, or build it in?
