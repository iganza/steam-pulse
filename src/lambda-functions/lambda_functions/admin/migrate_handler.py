"""Migration Lambda — applies pending yoyo migrations against the RDS database.

Invoked directly (RequestResponse) from the CDK pipeline post-deployment step.
Never triggered by SQS or EventBridge — schema changes must be deliberate.
Reserved concurrency: 1 (set in CDK) so migrations never run concurrently.
"""

import logging
from pathlib import Path

from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.utils.db import get_db_url
from yoyo import get_backend, read_migrations

logger = logging.getLogger("migration")
logger.setLevel(logging.INFO)

# Resolve DB URL at cold start — fails loud if DB_SECRET_NAME / DATABASE_URL missing.
_db_url: str = get_db_url()

# migrations/ lives at the root of the Lambda bundle (/var/task/migrations/ at runtime).
_MIGRATIONS_DIR: str = str(Path(__file__).parent.parent.parent / "migrations")


def handler(event: dict, context: LambdaContext) -> dict:
    """Apply all pending yoyo migrations and return a summary."""
    logger.info("Applying migrations from %s", _MIGRATIONS_DIR)
    backend = get_backend(_db_url)
    migrations = read_migrations(_MIGRATIONS_DIR)
    with backend.lock():
        pending = list(backend.to_apply(migrations))
        logger.info("Pending migrations: %d", len(pending))
        backend.apply_migrations(pending)
    applied = [m.id for m in pending]
    logger.info("Applied: %s", applied)
    return {"status": "ok", "applied": applied, "count": len(applied)}
