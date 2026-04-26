"""CollectGenreSynthesis Lambda — collect Anthropic batch output and persist.

Shell around ``GenreSynthesisService.collect_batch``. Runs after the
status poller reports ``Completed``. Writes ``mv_genre_synthesis`` and
marks the ``batch_executions`` row completed with token usage + cost.

Input is the merged PrepareSynthesis output plus the status_result:
    {
        "slug": "...", "skip": false, "job_id": "msgbatch_...",
        "display_name": "...", "selected_appids": [...],
        "avg_positive_pct": 85.0, "median_review_count": 3000,
        "input_hash": "...", "prompt_version": "...",
        "execution_id": "...",
        "status": "Completed"
    }

Output:
    {"slug": "...", "phase": "genre_synthesis", "done": true}
"""

import psycopg2.extensions
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.analyzer import PIPELINE_VERSION
from library_layer.config import SteamPulseConfig
from library_layer.llm import resolve_anthropic_api_key
from library_layer.llm.anthropic_batch import AnthropicBatchBackend
from library_layer.repositories.batch_execution_repo import BatchExecutionRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.genre_synthesis_repo import GenreSynthesisRepository
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.services.genre_synthesis_service import GenreSynthesisService
from library_layer.utils.db import get_conn

logger = Logger(service="batch-genre-synthesis-collect")

_config = SteamPulseConfig()

_BATCH_CONNECT_TIMEOUT = 60


def _get_batch_conn() -> psycopg2.extensions.connection:
    return get_conn(connect_timeout=_BATCH_CONNECT_TIMEOUT, max_connect_attempts=3)


_report_repo = ReportRepository(_get_batch_conn)
_tag_repo = TagRepository(_get_batch_conn)
_game_repo = GameRepository(_get_batch_conn)
_synthesis_repo = GenreSynthesisRepository(_get_batch_conn)
_batch_exec_repo = BatchExecutionRepository(_get_batch_conn)

_service = GenreSynthesisService(
    report_repo=_report_repo,
    tag_repo=_tag_repo,
    game_repo=_game_repo,
    synthesis_repo=_synthesis_repo,
    batch_exec_repo=_batch_exec_repo,
    config=_config,
    required_pipeline_version=PIPELINE_VERSION,
)


def _backend_for(execution_id: str) -> AnthropicBatchBackend:
    return AnthropicBatchBackend(
        _config,
        api_key=resolve_anthropic_api_key(_config),
        execution_id=execution_id,
    )


def handler(event: dict, context: LambdaContext) -> dict:
    slug: str = event["slug"]
    job_id: str = event["job_id"]
    execution_id: str = event["execution_id"]
    logger.append_keys(slug=slug, job_id=job_id, execution_id=execution_id)

    _service.collect_batch(
        slug=slug,
        job_id=job_id,
        selected_appids=[int(a) for a in event["selected_appids"]],
        display_name=event["display_name"],
        avg_positive_pct=float(event["avg_positive_pct"]),
        median_review_count=int(event["median_review_count"]),
        input_hash=event["input_hash"],
        prompt_version=event["prompt_version"],
        backend=_backend_for(execution_id),
    )
    return {"slug": slug, "phase": "genre_synthesis", "done": True}
