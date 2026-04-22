"""BatchExecution domain model."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class BatchExecution(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    execution_id: str
    appid: int | None = None
    slug: str = ""
    phase: str
    backend: str
    batch_id: str
    model_id: str
    status: str
    submitted_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    request_count: int
    succeeded_count: int | None = None
    failed_count: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    estimated_cost_usd: Decimal | None = None
    failure_reason: str | None = None
    failed_record_ids: list[str] | None = None
    pipeline_version: str | None = None
    prompt_version: str | None = None
