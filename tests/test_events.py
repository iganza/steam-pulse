"""Tests for SteamPulse event models (tests 1-16 from spec)."""

import json

import pytest
from library_layer.events import (
    BaseEvent,
    BatchCompleteEvent,
    CatalogRefreshCompleteEvent,
    GameDelistedEvent,
    GameDiscoveredEvent,
    GameMetadataReadyEvent,
    GamePriceChangedEvent,
    GameReleasedEvent,
    GameUpdatedEvent,
    ReportReadyEvent,
    ReviewMilestoneEvent,
    ReviewsReadyEvent,
)
from pydantic import ValidationError

ALL_EVENT_CLASSES = [
    GameDiscoveredEvent,
    GameMetadataReadyEvent,
    GameReleasedEvent,
    GameDelistedEvent,
    GamePriceChangedEvent,
    GameUpdatedEvent,
    ReviewMilestoneEvent,
    ReviewsReadyEvent,
    ReportReadyEvent,
    BatchCompleteEvent,
    CatalogRefreshCompleteEvent,
]


# 1. GameDiscoveredEvent round-trip
def test_game_discovered_event_valid() -> None:
    e = GameDiscoveredEvent(appid=440)
    assert e.event_type == "game-discovered"
    assert e.version == 1
    assert e.appid == 440
    data = json.loads(e.model_dump_json())
    restored = GameDiscoveredEvent.model_validate(data)
    assert restored == e


# 2. GameMetadataReadyEvent round-trip
def test_game_metadata_ready_event_valid() -> None:
    e = GameMetadataReadyEvent(appid=440, review_count=1000, is_eligible=True)
    assert e.event_type == "game-metadata-ready"
    data = json.loads(e.model_dump_json())
    restored = GameMetadataReadyEvent.model_validate(data)
    assert restored.review_count == 1000
    assert restored.is_eligible is True


# 3. GameReleasedEvent round-trip
def test_game_released_event_valid() -> None:
    e = GameReleasedEvent(appid=440, game_name="TF2", release_date="2007-10-10")
    assert e.event_type == "game-released"
    data = json.loads(e.model_dump_json())
    restored = GameReleasedEvent.model_validate(data)
    assert restored.game_name == "TF2"


# 4. GameDelistedEvent round-trip
def test_game_delisted_event_valid() -> None:
    e = GameDelistedEvent(appid=440, game_name="TF2")
    assert e.event_type == "game-delisted"
    data = json.loads(e.model_dump_json())
    assert data["game_name"] == "TF2"


# 5. GamePriceChangedEvent round-trip
def test_game_price_changed_event_valid() -> None:
    e = GamePriceChangedEvent(appid=440, old_price=29.99, new_price=19.99, is_free=False)
    assert e.event_type == "game-price-changed"
    data = json.loads(e.model_dump_json())
    restored = GamePriceChangedEvent.model_validate(data)
    assert restored.old_price == 29.99
    assert restored.new_price == 19.99


# 6. ReviewMilestoneEvent round-trip
def test_review_milestone_event_valid() -> None:
    e = ReviewMilestoneEvent(appid=440, milestone=500, review_count=523)
    assert e.event_type == "review-milestone"
    assert e.milestone == 500


# 7. ReviewsReadyEvent round-trip
def test_reviews_ready_event_valid() -> None:
    e = ReviewsReadyEvent(appid=440, game_name="TF2", reviews_crawled=150)
    assert e.event_type == "reviews-ready"
    data = json.loads(e.model_dump_json())
    assert data["reviews_crawled"] == 150


# 8. ReportReadyEvent round-trip
def test_report_ready_event_valid() -> None:
    e = ReportReadyEvent(appid=440, game_name="TF2", sentiment="Positive")
    assert e.event_type == "report-ready"
    data = json.loads(e.model_dump_json())
    assert data["sentiment"] == "Positive"


# 9. BatchCompleteEvent round-trip
def test_batch_complete_event_valid() -> None:
    e = BatchCompleteEvent(batch_job_id="job-123", games_processed=50, status="completed")
    assert e.event_type == "batch-complete"
    data = json.loads(e.model_dump_json())
    assert data["games_processed"] == 50


# 10. CatalogRefreshCompleteEvent round-trip
def test_catalog_refresh_complete_event_valid() -> None:
    e = CatalogRefreshCompleteEvent(new_games=100, total_games=5000)
    assert e.event_type == "catalog-refresh-complete"
    assert e.new_games == 100
    assert e.total_games == 5000


# 11. All events inherit from BaseEvent
def test_all_events_inherit_base_event() -> None:
    for cls in ALL_EVENT_CLASSES:
        assert issubclass(cls, BaseEvent), f"{cls.__name__} must inherit BaseEvent"


# 12. Literal event_type enforced
def test_event_type_literal_enforced() -> None:
    with pytest.raises(ValidationError):
        GameDiscoveredEvent(event_type="wrong", appid=440)


# 13. Missing required field raises ValidationError
def test_event_rejects_missing_required_field() -> None:
    with pytest.raises(ValidationError):
        GameDiscoveredEvent()  # type: ignore[call-arg]


# 14. Wrong type raises ValidationError
def test_event_rejects_wrong_type() -> None:
    with pytest.raises(ValidationError):
        GameDiscoveredEvent(appid="abc")  # type: ignore[arg-type]


# 15. Version defaults to 1
def test_event_version_defaults_to_1() -> None:
    e = GameDiscoveredEvent(appid=440)
    assert e.version == 1


# 16. event_type present in serialized JSON
def test_event_type_in_serialized_json() -> None:
    e = GameDiscoveredEvent(appid=440)
    data = json.loads(e.model_dump_json())
    assert "event_type" in data
    assert data["event_type"] == "game-discovered"
