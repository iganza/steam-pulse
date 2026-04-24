"""Start Lambda — records the cycle row and returns the full matview list."""

import time

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.repositories.matview_repo import MATVIEW_NAMES, MatviewRepository
from library_layer.utils.db import get_conn
from pydantic import BaseModel

logger = Logger(service="matview-refresh-start")

_repo = MatviewRepository(get_conn)


class StartEvent(BaseModel):
    cycle_id: str


class StartResult(BaseModel):
    cycle_id: str
    views: list[str]
    start_time_ms: int


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict:
    parsed = StartEvent.model_validate(event)
    _repo.start_cycle(parsed.cycle_id)
    logger.info(
        "Starting matview refresh cycle",
        extra={"cycle_id": parsed.cycle_id, "view_count": len(MATVIEW_NAMES)},
    )
    return StartResult(
        cycle_id=parsed.cycle_id,
        views=list(MATVIEW_NAMES),
        start_time_ms=int(time.time() * 1000),
    ).model_dump()
