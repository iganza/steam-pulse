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
            "publisher_slug": None,
            "developers": "[]",
            "publishers": "[]",
            "website": None,
            "release_date": None,
            "release_date_raw": None,
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


def test_upsert_genres_removes_stale(game_repo: GameRepository, tag_repo: TagRepository) -> None:
    _seed_game(game_repo)
    tag_repo.upsert_genres(
        440,
        [
            {"id": "1", "description": "Action"},
            {"id": "70", "description": "Early Access"},
        ],
    )
    # Simulate EA graduation — genre 70 removed upstream
    tag_repo.upsert_genres(440, [{"id": "1", "description": "Action"}])
    names = [r["name"] for r in tag_repo.find_genres_for_game(440)]
    assert names == ["Action"]


def test_upsert_genres_empty_clears_all(game_repo: GameRepository, tag_repo: TagRepository) -> None:
    _seed_game(game_repo)
    tag_repo.upsert_genres(440, [{"id": "1", "description": "Action"}])
    tag_repo.upsert_genres(440, [])
    assert tag_repo.find_genres_for_game(440) == []


def test_upsert_categories_removes_stale(
    game_repo: GameRepository, tag_repo: TagRepository
) -> None:
    _seed_game(game_repo)
    tag_repo.upsert_categories(
        440,
        [
            {"id": 1, "description": "Multi-player"},
            {"id": 22, "description": "Steam Achievements"},
        ],
    )
    tag_repo.upsert_categories(440, [{"id": 22, "description": "Steam Achievements"}])
    with game_repo.conn.cursor() as cur:
        cur.execute("SELECT category_id FROM game_categories WHERE appid = 440")
        ids = [r["category_id"] for r in cur.fetchall()]
    assert ids == [22]


def test_upsert_tags_removes_stale(game_repo: GameRepository, tag_repo: TagRepository) -> None:
    _seed_game(game_repo)
    tag_repo.upsert_tags(
        [
            {"appid": 440, "name": "Action", "votes": 100},
            {"appid": 440, "name": "FPS", "votes": 200},
            {"appid": 440, "name": "Co-op", "votes": 50},
        ]
    )
    # Re-crawl with a smaller set — Co-op should be removed
    tag_repo.upsert_tags(
        [
            {"appid": 440, "name": "Action", "votes": 110},
            {"appid": 440, "name": "FPS", "votes": 210},
        ]
    )
    names = {t["name"] for t in tag_repo.find_tags_for_game(440)}
    assert names == {"Action", "FPS"}


def test_upsert_tags_batch_across_appids_removes_stale_per_appid(
    game_repo: GameRepository, tag_repo: TagRepository
) -> None:
    """A multi-appid batch must delete each appid's stale tags independently,
    without touching tags of appids not in the batch.
    """
    _seed_game(game_repo, appid=440)
    _seed_game(game_repo, appid=441)
    _seed_game(game_repo, appid=442)

    # Seed initial tags for 440 and 441; give 442 a tag that must NOT be touched.
    tag_repo.upsert_tags(
        [
            {"appid": 440, "name": "Action", "votes": 100},
            {"appid": 440, "name": "Shooter", "votes": 90},
            {"appid": 441, "name": "RPG", "votes": 80},
            {"appid": 441, "name": "Fantasy", "votes": 70},
        ]
    )
    tag_repo.upsert_tags([{"appid": 442, "name": "Puzzle", "votes": 60}])

    # Re-crawl a batch covering 440 and 441 with trimmed-down tag sets.
    # Shooter drops off 440; Fantasy drops off 441. 442's Puzzle must survive.
    tag_repo.upsert_tags(
        [
            {"appid": 440, "name": "Action", "votes": 105},
            {"appid": 441, "name": "RPG", "votes": 85},
        ]
    )

    names_440 = {t["name"] for t in tag_repo.find_tags_for_game(440)}
    names_441 = {t["name"] for t in tag_repo.find_tags_for_game(441)}
    names_442 = {t["name"] for t in tag_repo.find_tags_for_game(442)}
    assert names_440 == {"Action"}
    assert names_441 == {"RPG"}
    assert names_442 == {"Puzzle"}
