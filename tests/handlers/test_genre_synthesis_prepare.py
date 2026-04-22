"""Handler-shell tests for genre_synthesis/prepare.py.

The Lambda is a thin wrapper around GenreSynthesisService.prepare_batch.
These tests verify the Step-Functions-payload → service-kwargs wiring and
that the PrepareResult is serialized correctly for downstream states.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


def test_prepare_handler_routes_event_to_service(monkeypatch: Any) -> None:
    import lambda_functions.genre_synthesis.prepare as mod

    fake_service = MagicMock()
    fake_backend = MagicMock()
    fake_result = MagicMock()
    fake_result.model_dump.return_value = {
        "slug": "roguelike-deckbuilder",
        "skip": False,
        "job_id": "msgbatch_test_001",
        "prompt_version": "v1",
        "execution_id": "exec-abc",
        "display_name": "Roguelike Deckbuilder",
        "selected_appids": [1001, 1002, 1003],
        "avg_positive_pct": 85.0,
        "median_review_count": 3000,
        "input_hash": "hash-abc",
    }
    fake_service.prepare_batch.return_value = fake_result
    monkeypatch.setattr(mod, "_service", fake_service)
    monkeypatch.setattr(mod, "_backend_for", lambda _execution_id: fake_backend)

    event = {
        "slug": "roguelike-deckbuilder",
        "prompt_version": "v1",
        "execution_id": "exec-abc",
    }

    result = mod.handler(event, MagicMock())

    assert result["slug"] == "roguelike-deckbuilder"
    assert result["job_id"] == "msgbatch_test_001"
    fake_service.prepare_batch.assert_called_once_with(
        slug="roguelike-deckbuilder",
        prompt_version="v1",
        execution_id="exec-abc",
        backend=fake_backend,
    )
