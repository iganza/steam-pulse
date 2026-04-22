"""Finalize Lambda — aggregate Map results into matview_refresh_log."""

import time

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.repositories.matview_repo import MatviewRepository
from library_layer.utils.db import get_conn
from pydantic import BaseModel

logger = Logger(service="matview-refresh-finalize")

_repo = MatviewRepository(get_conn)


class PerViewResult(BaseModel):
    name: str
    success: bool
    duration_ms: int
    error: str = ""


class FinalizeEvent(BaseModel):
    cycle_id: str
    start_time_ms: int
    results: list[PerViewResult]


class FinalizeResult(BaseModel):
    cycle_id: str
    status: str
    duration_ms: int
    success_count: int
    failure_count: int


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict:
    parsed = FinalizeEvent.model_validate(event)
    now_ms = int(time.time() * 1000)
    duration_ms = max(0, now_ms - parsed.start_time_ms)

    per_view: dict[str, dict] = {
        r.name: {"success": r.success, "duration_ms": r.duration_ms, "error": r.error}
        for r in parsed.results
    }

    _repo.complete_cycle(parsed.cycle_id, duration_ms, per_view)

    success_count = sum(1 for r in parsed.results if r.success)
    failure_count = len(parsed.results) - success_count

    if success_count == len(parsed.results):
        status = "complete"
    elif success_count == 0:
        status = "failed"
    else:
        status = "partial_failure"

    # Per-view failure log so CloudWatch Insights can pinpoint which views broke.
    for r in parsed.results:
        if not r.success:
            logger.error(
                "Matview refresh failed",
                extra={
                    "cycle_id": parsed.cycle_id,
                    "matview": r.name,
                    "error": r.error,
                },
            )

    logger.info(
        "Matview refresh cycle finalized",
        extra={
            "cycle_id": parsed.cycle_id,
            "status": status,
            "duration_ms": duration_ms,
            "success_count": success_count,
            "failure_count": failure_count,
        },
    )

    # Raise on any failure so the SFN execution is marked Failed (not Succeeded)
    # — otherwise a single 15-min timeout disappears into a green checkmark.
    if failure_count > 0:
        failed = [f"{r.name} ({r.error or 'no error captured'})" for r in parsed.results if not r.success]
        raise RuntimeError(
            f"Matview refresh {status} — {failure_count}/{len(parsed.results)} failed: {'; '.join(failed)}"
        )

    return FinalizeResult(
        cycle_id=parsed.cycle_id,
        status=status,
        duration_ms=duration_ms,
        success_count=success_count,
        failure_count=failure_count,
    ).model_dump()
