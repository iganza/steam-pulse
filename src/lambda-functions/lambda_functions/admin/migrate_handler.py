"""Migration Lambda — applies pending yoyo migrations against the RDS database.

Invoked directly (RequestResponse) from the CDK pipeline post-deployment step.
Never triggered by SQS or EventBridge — schema changes must be deliberate.
Reserved concurrency: 1 (set in CDK) so migrations never run concurrently.
"""

import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import psycopg2
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.utils.db import get_db_url
from yoyo import get_backend, read_migrations
from yoyo.exceptions import BadMigration

logger = Logger(service="migration")


def _add_connect_timeout(url: str, timeout: int = 30) -> str:
    """Merge connect_timeout into the DB URL without duplicating query params."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["connect_timeout"] = [str(timeout)]
    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))


# Resolve DB URL at cold start — fails loud if DB_SECRET_NAME / DATABASE_URL missing.
# connect_timeout=30 gives Aurora Serverless v2 time to wake from 0 ACU.
_db_url: str = _add_connect_timeout(get_db_url())

# migrations/ lives at the root of the Lambda bundle (/var/task/migrations/ at runtime).
_MIGRATIONS_DIR: str = str(Path(__file__).parent.parent.parent / "migrations")

_MAX_RETRIES = 4
_RETRY_DELAY_S = 15


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict:
    """Apply all pending yoyo migrations and return a summary."""
    logger.info("Applying migrations", extra={"migrations_dir": _MIGRATIONS_DIR})

    # Retry loop — Aurora Serverless v2 at min=0 ACU can take up to 30-60s to wake.
    last_err: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            backend = get_backend(_db_url)
            migrations = read_migrations(_MIGRATIONS_DIR)
            with backend.lock():
                pending = backend.to_apply(migrations)
                logger.info("Pending migrations", extra={"count": len(pending), "attempt": attempt})
                backend.apply_migrations(pending)
            applied = [m.id for m in pending]
            logger.info("Migrations applied", extra={"applied": applied})
            return {"status": "ok", "applied": applied, "count": len(applied)}
        except (OSError, psycopg2.OperationalError, BadMigration) as exc:
            last_err = exc
            if attempt < _MAX_RETRIES:
                logger.warning(
                    "DB not ready, retrying",
                    extra={"attempt": attempt, "delay_s": _RETRY_DELAY_S, "error": str(exc)},
                )
                time.sleep(_RETRY_DELAY_S)
            else:
                logger.error("Migration failed after retries", extra={"error": str(exc)})

    raise RuntimeError(f"Migration failed after {_MAX_RETRIES} attempts: {last_err}")
