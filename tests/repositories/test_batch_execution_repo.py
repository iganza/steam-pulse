"""DB-backed tests for BatchExecutionRepository.

Covers the insert/mark_running/mark_completed/mark_failed lifecycle and
the query methods (find_active, find_by_execution_id, find_by_appid).
"""

from typing import Any

import pytest
from library_layer.repositories.batch_execution_repo import BatchExecutionRepository
from library_layer.repositories.game_repo import GameRepository


@pytest.fixture
def batch_exec_repo(db_conn: Any) -> BatchExecutionRepository:
    return BatchExecutionRepository(lambda: db_conn)


def _seed_game(game_repo: GameRepository, appid: int = 440) -> None:
    game_repo.upsert(
        {
            "appid": appid,
            "name": f"Game {appid}",
            "slug": f"game-{appid}",
            "type": "game",
            "developer": "Dev",
            "developer_slug": "dev",
            "publisher": "Pub",
            "publisher_slug": "pub",
            "developers": "[]",
            "publishers": "[]",
            "website": None,
            "release_date": None,
            "release_date_raw": None,
            "coming_soon": False,
            "price_usd": None,
            "is_free": True,
            "short_desc": None,
            "detailed_description": None,
            "about_the_game": None,
            "review_count": 100,
            "review_count_english": 100,
            "total_positive": 90,
            "total_negative": 10,
            "positive_pct": 90,
            "review_score_desc": "Very Positive",
            "header_image": None,
            "background_image": None,
            "required_age": 0,
            "platforms": "{}",
            "supported_languages": None,
            "achievements_total": 0,
            "metacritic_score": None,
            "deck_compatibility": None,
            "deck_test_results": None,
            "content_descriptor_ids": None,
            "content_descriptor_notes": None,
            "controller_support": None,
            "dlc_appids": None,
            "parent_appid": None,
            "capsule_image": None,
            "recommendations_total": None,
            "support_url": None,
            "support_email": None,
            "legal_notice": None,
            "requirements_windows": None,
            "requirements_mac": None,
            "requirements_linux": None,
            "data_source": "steam_direct",
        }
    )


def test_insert_and_find_by_execution_id(
    game_repo: GameRepository, batch_exec_repo: BatchExecutionRepository
) -> None:
    _seed_game(game_repo)
    row_id = batch_exec_repo.insert(
        execution_id="exec-test-1",
        appid=440,
        phase="chunk",
        backend="anthropic",
        batch_id="msgbatch_01abc",
        model_id="claude-haiku-4-5-20251001",
        request_count=10,
        pipeline_version="v3.0",
        prompt_version="chunk-v2.0",
    )
    assert row_id > 0

    rows = batch_exec_repo.find_by_execution_id("exec-test-1")
    assert len(rows) == 1
    assert rows[0]["batch_id"] == "msgbatch_01abc"
    assert rows[0]["status"] == "submitted"
    assert rows[0]["request_count"] == 10


def test_mark_running(game_repo: GameRepository, batch_exec_repo: BatchExecutionRepository) -> None:
    _seed_game(game_repo)
    batch_exec_repo.insert(
        execution_id="exec-run-1",
        appid=440,
        phase="chunk",
        backend="anthropic",
        batch_id="msgbatch_run",
        model_id="claude-haiku-4-5-20251001",
        request_count=5,
        pipeline_version="v3.0",
        prompt_version="chunk-v2.0",
    )
    batch_exec_repo.mark_running("msgbatch_run")

    rows = batch_exec_repo.find_by_execution_id("exec-run-1")
    assert rows[0]["status"] == "running"


def test_mark_completed(
    game_repo: GameRepository, batch_exec_repo: BatchExecutionRepository
) -> None:
    _seed_game(game_repo)
    batch_exec_repo.insert(
        execution_id="exec-done-1",
        appid=440,
        phase="synthesis",
        backend="anthropic",
        batch_id="msgbatch_done",
        model_id="claude-sonnet-4-6-20250514",
        request_count=1,
        pipeline_version="v3.0",
        prompt_version="chunk-v2.0",
    )
    batch_exec_repo.mark_completed(
        "msgbatch_done",
        succeeded_count=1,
        failed_count=0,
        input_tokens=5000,
        output_tokens=2000,
        cache_read_tokens=3000,
        cache_write_tokens=500,
        estimated_cost_usd=0.0125,
        failed_record_ids=[],
    )

    rows = batch_exec_repo.find_by_execution_id("exec-done-1")
    assert rows[0]["status"] == "completed"
    assert rows[0]["succeeded_count"] == 1
    assert rows[0]["input_tokens"] == 5000
    assert rows[0]["cache_read_tokens"] == 3000
    assert rows[0]["completed_at"] is not None
    assert rows[0]["duration_ms"] is not None


def test_mark_failed(game_repo: GameRepository, batch_exec_repo: BatchExecutionRepository) -> None:
    _seed_game(game_repo)
    batch_exec_repo.insert(
        execution_id="exec-fail-1",
        appid=440,
        phase="chunk",
        backend="bedrock",
        batch_id="arn:aws:bedrock:job/fail",
        model_id="anthropic.claude-haiku",
        request_count=20,
        pipeline_version="v3.0",
        prompt_version="chunk-v2.0",
    )
    batch_exec_repo.mark_failed("arn:aws:bedrock:job/fail", failure_reason="Job expired after 24h")

    rows = batch_exec_repo.find_by_execution_id("exec-fail-1")
    assert rows[0]["status"] == "failed"
    assert rows[0]["failure_reason"] == "Job expired after 24h"
    assert rows[0]["completed_at"] is not None


def test_find_active(game_repo: GameRepository, batch_exec_repo: BatchExecutionRepository) -> None:
    _seed_game(game_repo)
    batch_exec_repo.insert(
        execution_id="exec-active-1",
        appid=440,
        phase="chunk",
        backend="anthropic",
        batch_id="msgbatch_active1",
        model_id="claude-haiku-4-5-20251001",
        request_count=5,
        pipeline_version="v3.0",
        prompt_version="chunk-v2.0",
    )
    batch_exec_repo.insert(
        execution_id="exec-active-1",
        appid=440,
        phase="synthesis",
        backend="anthropic",
        batch_id="msgbatch_active2",
        model_id="claude-sonnet-4-6-20250514",
        request_count=1,
        pipeline_version="v3.0",
        prompt_version="chunk-v2.0",
    )
    # Complete one of them
    batch_exec_repo.mark_completed(
        "msgbatch_active2",
        succeeded_count=1,
        failed_count=0,
        input_tokens=None,
        output_tokens=None,
        cache_read_tokens=None,
        cache_write_tokens=None,
        estimated_cost_usd=None,
        failed_record_ids=[],
    )

    active = batch_exec_repo.find_active()
    active_batch_ids = [r["batch_id"] for r in active]
    assert "msgbatch_active1" in active_batch_ids
    assert "msgbatch_active2" not in active_batch_ids


def test_find_by_appid(
    game_repo: GameRepository, batch_exec_repo: BatchExecutionRepository
) -> None:
    _seed_game(game_repo)
    batch_exec_repo.insert(
        execution_id="exec-appid-1",
        appid=440,
        phase="chunk",
        backend="anthropic",
        batch_id="msgbatch_appid1",
        model_id="claude-haiku-4-5-20251001",
        request_count=10,
        pipeline_version="v3.0",
        prompt_version="chunk-v2.0",
    )
    rows = batch_exec_repo.find_by_appid(440, limit=10)
    assert len(rows) >= 1
    assert all(r["appid"] == 440 for r in rows)
