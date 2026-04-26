"""PrepareGenreSynthesis Lambda — resolve inputs and submit one Anthropic batch.

Shell around ``GenreSynthesisService.prepare_batch``. Step Functions
threads the output into the Wait → CheckStatus → Collect chain.

Input:
    {
        "slug": "roguelike-deckbuilder",
        "prompt_version": "v1",
        "execution_id": "..."
    }

Output (cache hit):
    {
        "slug": "...", "skip": true, "prompt_version": "...",
        "execution_id": "...", "job_id": ""
    }

Output (batch submitted):
    {
        "slug": "...", "skip": false, "job_id": "msgbatch_...",
        "display_name": "...", "selected_appids": [...],
        "avg_positive_pct": 85.0, "median_review_count": 3000,
        "input_hash": "...", "prompt_version": "...",
        "execution_id": "..."
    }
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

logger = Logger(service="batch-genre-synthesis-prepare")

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
    prompt_version: str = event["prompt_version"]
    execution_id: str = event["execution_id"]
    logger.append_keys(slug=slug, prompt_version=prompt_version, execution_id=execution_id)

    result = _service.prepare_batch(
        slug=slug,
        prompt_version=prompt_version,
        execution_id=execution_id,
        backend=_backend_for(execution_id),
    )
    return result.model_dump(mode="json")
