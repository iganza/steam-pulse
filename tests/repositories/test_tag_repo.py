"""Tests for TagRepository."""

from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.tag_repo import TagRepository


def _seed_game(game_repo: GameRepository, appid: int = 440) -> None:
    game_repo.upsert(
        {
            "appid": appid,
            "name": f"App {appid}",
            "slug": f"app-{appid}",
            "type": "game",
            "developer": None,
            "developer_slug": None,
            "publisher": None,
            "developers": "[]",
            "publishers": "[]",
            "website": None,
            "release_date": None,
            "coming_soon": False,
            "price_usd": None,
            "is_free": False,
            "short_desc": None,
            "detailed_description": None,
            "about_the_game": None,
            "review_count": 1000,
            "review_count_english": 1000,
            "total_positive": 900,
            "total_negative": 100,
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
            "data_source": "steam_direct",
        }
    )


def test_upsert_genres(game_repo: GameRepository, tag_repo: TagRepository) -> None:
    _seed_game(game_repo)
    genres = [
        {"id": "1", "description": "Action"},
        {"id": "37", "description": "Free To Play"},
    ]
    tag_repo.upsert_genres(440, genres)
    result = tag_repo.find_genres_for_game(440)
    names = [r["name"] for r in result]
    assert "Action" in names
    assert "Free To Play" in names


def test_upsert_genres_idempotent(game_repo: GameRepository, tag_repo: TagRepository) -> None:
    _seed_game(game_repo)
    genres = [{"id": "1", "description": "Action"}]
    tag_repo.upsert_genres(440, genres)
    tag_repo.upsert_genres(440, genres)  # second call — no error
    result = tag_repo.find_genres_for_game(440)
    assert len(result) == 1


def test_upsert_categories(game_repo: GameRepository, tag_repo: TagRepository) -> None:
    _seed_game(game_repo)
    categories = [
        {"id": 1, "description": "Multi-player"},
        {"id": 22, "description": "Steam Achievements"},
    ]
    tag_repo.upsert_categories(440, categories)
    # Verify via direct DB query (no find_categories_for_game needed in repo API)
    with game_repo.conn.cursor() as cur:
        cur.execute(
            "SELECT category_name FROM game_categories WHERE appid = 440 ORDER BY category_id"
        )
        rows = cur.fetchall()
    names = [r["category_name"] for r in rows]
    assert "Multi-player" in names
    assert "Steam Achievements" in names


def test_upsert_tags(game_repo: GameRepository, tag_repo: TagRepository) -> None:
    _seed_game(game_repo)
    items = [
        {"appid": 440, "name": "Action", "votes": 100},
        {"appid": 440, "name": "FPS", "votes": 200},
    ]
    tag_repo.upsert_tags(items)
    tags = tag_repo.find_tags_for_game(440)
    names = [t["name"] for t in tags]
    assert "Action" in names
    assert "FPS" in names


def test_upsert_tags_updates_votes(game_repo: GameRepository, tag_repo: TagRepository) -> None:
    _seed_game(game_repo)
    tag_repo.upsert_tags([{"appid": 440, "name": "Action", "votes": 50}])
    tag_repo.upsert_tags([{"appid": 440, "name": "Action", "votes": 150}])
    tags = tag_repo.find_tags_for_game(440)
    action_tag = next(t for t in tags if t["name"] == "Action")
    assert action_tag["votes"] == 150
