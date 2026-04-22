"""Start Lambda — debounce gate + cycle bookkeeping for matview refresh.

First step of the Step Functions workflow. Decides whether to run the
cycle (based on a 5-minute debounce against the most recent `complete`
row in `matview_refresh_log`) and, if so, inserts a `running` row keyed
by the SFN execution name and returns the list of views to fan out.
"""

import time

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.repositories.matview_repo import MATVIEW_NAMES, MatviewRepository
from library_layer.utils.db import get_conn
from pydantic import BaseModel

logger = Logger(service="matview-refresh-start")

DEBOUNCE_SECONDS = 300

_repo = MatviewRepository(get_conn)


class StartEvent(BaseModel):
    force: bool = False
    cycle_id: str


class StartResult(BaseModel):
    skip: bool
    cycle_id: str
    views: list[str] = []
    start_time_ms: int = 0


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict:
    parsed = StartEvent.model_validate(event)
    last_ts = _repo.get_last_refresh_time()
    now = time.time()

    if not parsed.force and last_ts and (now - last_ts) < DEBOUNCE_SECONDS:
        logger.info(
            "Skipping refresh — debounced",
            extra={"seconds_since_last": round(now - last_ts), "cycle_id": parsed.cycle_id},
        )
        return StartResult(skip=True, cycle_id=parsed.cycle_id).model_dump()

    _repo.start_cycle(parsed.cycle_id)
    logger.info(
        "Starting matview refresh cycle",
        extra={"cycle_id": parsed.cycle_id, "force": parsed.force, "view_count": len(MATVIEW_NAMES)},
    )
    return StartResult(
        skip=False,
        cycle_id=parsed.cycle_id,
        views=list(MATVIEW_NAMES),
        start_time_ms=int(now * 1000),
    ).model_dump()
