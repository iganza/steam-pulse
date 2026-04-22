"""Start Lambda — debounce + in-flight gate for the matview-refresh SFN."""

import time

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.repositories.matview_repo import (
    MATVIEW_NAMES,
    REPORT_DEPENDENT_VIEWS,
    MatviewRepository,
)
from library_layer.utils.db import get_conn
from pydantic import BaseModel

logger = Logger(service="matview-refresh-start")

DEBOUNCE_SECONDS = 300
# Cutoff past which a stuck 'running' row is treated as crashed.
RUNNING_STALE_SECONDS = 3600

_repo = MatviewRepository(get_conn)


class StartEvent(BaseModel):
    force: bool = False
    cycle_id: str
    trigger_event: str = ""


class StartResult(BaseModel):
    skip: bool
    cycle_id: str
    views: list[str] = []
    start_time_ms: int = 0


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict:
    parsed = StartEvent.model_validate(event)
    now = time.time()

    if not parsed.force:
        running_cycle_id = _repo.get_running_cycle_id(RUNNING_STALE_SECONDS)
        if running_cycle_id:
            logger.info(
                "Skipping refresh — cycle already running",
                extra={"cycle_id": parsed.cycle_id, "running_cycle_id": running_cycle_id},
            )
            return StartResult(skip=True, cycle_id=parsed.cycle_id).model_dump()

        last_ts = _repo.get_last_refresh_time()
        if last_ts and (now - last_ts) < DEBOUNCE_SECONDS:
            logger.info(
                "Skipping refresh — debounced",
                extra={
                    "seconds_since_last": round(now - last_ts),
                    "cycle_id": parsed.cycle_id,
                },
            )
            return StartResult(skip=True, cycle_id=parsed.cycle_id).model_dump()

    # `report-ready` invalidates only the 4 report-dependent views — everything
    # else (batch/catalog/EB cron/CLI) gets the full refresh.
    if parsed.trigger_event == "report-ready":
        views = list(REPORT_DEPENDENT_VIEWS)
    else:
        views = list(MATVIEW_NAMES)

    _repo.start_cycle(parsed.cycle_id)
    logger.info(
        "Starting matview refresh cycle",
        extra={
            "cycle_id": parsed.cycle_id,
            "force": parsed.force,
            "trigger_event": parsed.trigger_event,
            "view_count": len(views),
        },
    )
    return StartResult(
        skip=False,
        cycle_id=parsed.cycle_id,
        views=views,
        start_time_ms=int(now * 1000),
    ).model_dump()
