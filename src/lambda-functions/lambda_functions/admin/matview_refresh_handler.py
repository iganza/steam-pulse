"""Materialized view refresh Lambda — keeps catalog matviews up-to-date.

Triggered by:
- SQS messages from cache_invalidation_queue (report-ready, catalog-refresh-complete)
- EventBridge schedule (every 6 hours, as fallback)

Debounce: skips refresh if the last refresh was less than 5 minutes ago.
Reserved concurrency: 1 (set in CDK) to prevent concurrent refreshes.
"""

import time

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.repositories.matview_repo import MatviewRepository
from library_layer.utils.db import get_conn

logger = Logger(service="matview-refresh")

_DEBOUNCE_SECONDS = 300  # 5 minutes

_repo = MatviewRepository(get_conn)


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict:
    """Refresh all materialized views with debounce."""
    last_ts = _repo.get_last_refresh_time()
    now = time.time()

    if last_ts and (now - last_ts) < _DEBOUNCE_SECONDS:
        logger.info(
            "Skipping refresh — debounced",
            extra={"seconds_since_last": round(now - last_ts)},
        )
        return {"status": "skipped", "reason": "debounced"}

    start = time.monotonic()
    results = _repo.refresh_all()
    duration_ms = int((time.monotonic() - start) * 1000)

    failed = [name for name, ok in results.items() if not ok]
    if failed:
        # Don't log to debounce table — partial failure should allow retries.
        logger.warning(
            "Some matviews failed to refresh",
            extra={"failed": failed, "duration_ms": duration_ms},
        )
        raise RuntimeError(f"Failed to refresh materialized views: {', '.join(failed)}")

    _repo.log_refresh(duration_ms, list(results.keys()))

    logger.info(
        "All matviews refreshed",
        extra={"duration_ms": duration_ms, "count": len(results)},
    )

    return {"status": "refreshed", "duration_ms": duration_ms, "results": results}
