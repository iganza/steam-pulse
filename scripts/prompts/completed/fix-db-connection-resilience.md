# Fix DB Connection Resilience — Connection Factory Pattern

## Problem

All Lambda handlers store `_conn = get_conn()` at module level (cold start) and pass that connection
object to repositories. When the connection dies (RDS maintenance, failover, Lambda freeze/thaw, idle
timeout), repositories still hold the dead connection object and every subsequent invocation fails with
`psycopg2.InterfaceError: connection already closed`.

This is the #1 cause of messages landing in the spoke-results-dlq.

## Best Practice (from AWS docs + standard Lambda patterns)

Pass a **connection factory** (callable) to repositories, not a connection object. The factory validates
and reconnects transparently. Repositories call it on every operation — no stale references.

## Implementation

### Step 1: Harden `get_conn()` in db.py

Add TCP keepalive params to detect dead connections faster, and add a catch-and-reconnect wrapper.

**File:** `src/library-layer/library_layer/utils/db.py`

```python
def get_conn(
    cursor_factory=psycopg2.extras.RealDictCursor,
) -> psycopg2.extensions.connection:
    """Return a cached psycopg2 connection, reconnecting if stale."""
    if "conn" in _state and not _state["conn"].closed:
        try:
            # Detect server-side disconnects (RDS maintenance, failover)
            _state["conn"].cursor().execute("SELECT 1")
            _state["conn"].commit()
            return _state["conn"]
        except Exception:
            try:
                _state["conn"].close()
            except Exception:
                pass

    _state["conn"] = psycopg2.connect(
        get_db_url(),
        cursor_factory=cursor_factory,
        connect_timeout=5,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
    )
    return _state["conn"]
```

### Step 2: Change BaseRepository to accept a connection factory

**File:** `src/library-layer/library_layer/repositories/base.py`

```python
class BaseRepository:
    """Common psycopg2 helpers. Subclasses never open connections themselves."""

    def __init__(self, get_conn: Callable[[], psycopg2.extensions.connection]) -> None:
        self._get_conn = get_conn

    @property
    def conn(self) -> psycopg2.extensions.connection:
        """Get a validated connection — reconnects transparently if stale."""
        return self._get_conn()
```

The `conn` property means all existing code (`self.conn.cursor()`, etc.) keeps working with zero
changes to repository methods or services. The only change is in the constructor signature.

### Step 3: Update all handlers — pass `get_conn` not `get_conn()`

**All handler files** (8 files listed below):

```python
# BEFORE:
_conn = get_conn()
_catalog_repo = CatalogRepository(_conn)
_review_repo = ReviewRepository(_conn)

# AFTER:
_catalog_repo = CatalogRepository(get_conn)
_review_repo = ReviewRepository(get_conn)
```

Remove all `_conn = get_conn()` lines. Repos and services no longer need a shared `_conn` variable.

For services that take repos (like CrawlService), nothing changes — they already receive repo
objects, not connections.

For services that take a `conn` directly (check if any do), change them to take a factory too.

### Handler files to update:

```
src/lambda-functions/lambda_functions/crawler/ingest_handler.py    ← critical
src/lambda-functions/lambda_functions/crawler/handler.py
src/lambda-functions/lambda_functions/api/handler.py
src/lambda-functions/lambda_functions/admin/handler.py
src/lambda-functions/lambda_functions/admin/matview_refresh_handler.py
src/lambda-functions/lambda_functions/batch_analysis/prepare_pass1.py
src/lambda-functions/lambda_functions/batch_analysis/prepare_pass2.py
src/lambda-functions/lambda_functions/batch_analysis/process_results.py
```

### Step 4: Fix rollback calls

The ingest handler has `_conn.rollback()` in the except block (line 140). Since there's no `_conn`
variable anymore, change it to:

```python
except Exception:
    logger.exception("Record processing failed", extra={"appid": appid, "task": task})
    try:
        get_conn().rollback()
    except Exception:
        pass  # connection may be dead — that's why we're here
    raise
```

### Step 5: Update tests

Any tests that construct repositories with a connection object need to be updated:

```python
# BEFORE:
repo = GameRepository(mock_conn)

# AFTER:
repo = GameRepository(lambda: mock_conn)
```

## Files to modify (summary)

| File | Change |
|------|--------|
| `library_layer/utils/db.py` | Add keepalives + SELECT 1 health check |
| `library_layer/repositories/base.py` | `__init__` takes callable, `conn` becomes property |
| 8 handler files | Pass `get_conn` not `get_conn()`, remove `_conn` variable |
| Test files using repos | Pass `lambda: conn` instead of `conn` |

## What NOT to change

- Repository method bodies — `self.conn` still works via the property
- Service constructors — they take repos, not connections
- psycopg2 → psycopg3 migration — not needed, factory pattern works with psycopg2
- No connection pooling — one connection per Lambda container is correct
- No RDS Proxy — not needed at current scale

## Verification

1. `poetry run pytest -v` — all tests pass with the factory pattern
2. Deploy to staging
3. Kill connections: `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = 'postgres' AND pid != pg_backend_pid()`
4. Send a test message to ingest queue — should reconnect and succeed
5. Monitor spoke-results-dlq — should stop growing from "connection closed" errors
