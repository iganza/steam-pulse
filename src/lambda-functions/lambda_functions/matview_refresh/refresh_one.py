"""Worker Lambda — REFRESH MATERIALIZED VIEW CONCURRENTLY for one view.

Invoked by the Step Functions Map state, once per view name. Returns
failure as *data* rather than raising, so Map aggregates partial
failures at Finalize instead of aborting under default retry behavior.
Lambda timeout: 15 minutes (3x the old aggregate Lambda's 5-min budget
applied to a single view).
"""

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.repositories.matview_repo import MatviewRepository
from library_layer.utils.db import get_conn
from pydantic import BaseModel

logger = Logger(service="matview-refresh-worker")

_repo = MatviewRepository(get_conn)


class WorkerEvent(BaseModel):
    name: str
    cycle_id: str


class WorkerResult(BaseModel):
    name: str
    success: bool
    duration_ms: int
    error: str = ""


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict:
    parsed = WorkerEvent.model_validate(event)
    try:
        duration_ms = _repo.refresh_one(parsed.name)
        logger.info(
            "Refreshed matview",
            extra={"matview": parsed.name, "duration_ms": duration_ms, "cycle_id": parsed.cycle_id},
        )
        return WorkerResult(
            name=parsed.name, success=True, duration_ms=duration_ms
        ).model_dump()
    except Exception as exc:
        logger.exception(
            "Failed to refresh matview",
            extra={"matview": parsed.name, "cycle_id": parsed.cycle_id},
        )
        return WorkerResult(
            name=parsed.name, success=False, duration_ms=0, error=str(exc)
        ).model_dump()
