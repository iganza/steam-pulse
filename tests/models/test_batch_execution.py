"""Tests for the BatchExecution domain model — NULL-slug coercion."""

from __future__ import annotations

from datetime import datetime

from library_layer.models.batch_execution import BatchExecution


def _base_row() -> dict[str, object]:
    return {
        "id": 1,
        "execution_id": "exec-1",
        "phase": "chunk",
        "backend": "anthropic",
        "batch_id": "msgbatch_1",
        "model_id": "claude-sonnet-4-6",
        "status": "submitted",
        "submitted_at": datetime.fromisoformat("2026-04-22T00:00:00+00:00"),
        "request_count": 1,
    }


def test_batch_execution_coerces_null_slug_to_empty() -> None:
    """Phase 1-3 rows have slug NULL — validator maps None → '' so the
    domain model stays no-optionality without a separate `| None` type."""
    row = _base_row() | {"appid": 440, "slug": None}
    model = BatchExecution.model_validate(row)
    assert model.slug == ""
    assert model.appid == 440


def test_batch_execution_keeps_explicit_slug() -> None:
    row = _base_row() | {"appid": None, "slug": "roguelike-deckbuilder", "phase": "genre_synthesis"}
    model = BatchExecution.model_validate(row)
    assert model.slug == "roguelike-deckbuilder"
    assert model.appid is None
