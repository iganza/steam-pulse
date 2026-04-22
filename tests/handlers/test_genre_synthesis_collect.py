"""Handler-shell tests for genre_synthesis/collect.py.

The Lambda is a thin wrapper around GenreSynthesisService.collect_batch.
These tests verify the Step-Functions-payload → service-kwargs wiring:
  - numeric fields coerced (avg_positive_pct: str-or-int → float,
    median_review_count → int, selected_appids → list[int])
  - service called exactly once with the expected arguments
  - handler returns the {slug, phase, done} contract
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


def _get_module() -> Any:
    import lambda_functions.genre_synthesis.collect as mod

    return mod


def test_collect_handler_coerces_payload_and_returns_done_shape(
    monkeypatch: Any,
) -> None:
    mod = _get_module()

    fake_service = MagicMock()
    fake_backend = MagicMock()
    monkeypatch.setattr(mod, "_service", fake_service)
    monkeypatch.setattr(mod, "_backend_for", lambda _execution_id: fake_backend)

    event = {
        "slug": "roguelike-deckbuilder",
        "job_id": "msgbatch_test_001",
        "execution_id": "exec-abc",
        # Step Functions will pass numeric values from JSONPath — accept
        # both numeric and string forms to match real event shapes.
        "selected_appids": [1001, 1002, "1003"],
        "display_name": "Roguelike Deckbuilder",
        "avg_positive_pct": "85.0",
        "median_review_count": "3000",
        "input_hash": "hash-abc",
        "prompt_version": "v1",
    }

    result = mod.handler(event, MagicMock())

    assert result == {
        "slug": "roguelike-deckbuilder",
        "phase": "genre_synthesis",
        "done": True,
    }
    fake_service.collect_batch.assert_called_once()
    kwargs = fake_service.collect_batch.call_args.kwargs
    assert kwargs["slug"] == "roguelike-deckbuilder"
    assert kwargs["job_id"] == "msgbatch_test_001"
    assert kwargs["selected_appids"] == [1001, 1002, 1003]
    assert kwargs["display_name"] == "Roguelike Deckbuilder"
    assert kwargs["avg_positive_pct"] == 85.0
    assert kwargs["median_review_count"] == 3000
    assert kwargs["input_hash"] == "hash-abc"
    assert kwargs["prompt_version"] == "v1"
    assert kwargs["backend"] is fake_backend
