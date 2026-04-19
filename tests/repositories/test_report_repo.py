"""Tests for ReportRepository."""

import pytest
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.tag_repo import TagRepository


def _seed_game(
    game_repo: GameRepository, appid: int = 440, *, type_: str = "game"
) -> None:
    game_repo.upsert(
        {
            "appid": appid,
            "name": "Team Fortress 2",
            "slug": f"team-fortress-2-{appid}",
            "type": type_,
            "developer": "Valve",
            "developer_slug": "valve",
            "publisher": "Valve",
            "publisher_slug": "valve",
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
            "review_count": 188000,
            "review_count_english": 188000,
            "total_positive": 182000,
            "total_negative": 6000,
            "positive_pct": 96,
            "review_score_desc": "Overwhelmingly Positive",
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


def _report(appid: int = 440) -> dict:
    return {
        "appid": appid,
        "game_name": "Team Fortress 2",
        "one_liner": "The gold standard of team shooters.",
        "total_reviews_analyzed": 2000,
        "pipeline_version": "3.0",
        "chunk_count": 10,
        "merged_summary_id": 1,
        "design_strengths": ["Class variety"],
        "gameplay_friction": ["Bot problem"],
    }


def test_upsert_and_find(game_repo: GameRepository, report_repo: ReportRepository) -> None:
    _seed_game(game_repo)
    report_repo.upsert(_report())
    result = report_repo.find_by_appid(440)
    assert result is not None
    assert result.appid == 440
    assert result.reviews_analyzed == 2000
    assert result.report_json["game_name"] == "Team Fortress 2"


def test_upsert_updates_existing(game_repo: GameRepository, report_repo: ReportRepository) -> None:
    _seed_game(game_repo)
    report_repo.upsert(_report())
    updated = _report()
    updated["total_reviews_analyzed"] = 3000
    report_repo.upsert(updated)
    result = report_repo.find_by_appid(440)
    assert result is not None
    assert result.reviews_analyzed == 3000


def test_find_public(game_repo: GameRepository, report_repo: ReportRepository) -> None:
    _seed_game(game_repo, 440)
    _seed_game(game_repo, 441)
    report_repo.upsert({**_report(440)})
    report_repo.upsert({**_report(441)})
    # Default is_public=True
    public = report_repo.find_public()
    appids = [r.appid for r in public]
    assert 440 in appids
    assert 441 in appids


def test_find_by_appid_returns_none_for_missing(
    report_repo: ReportRepository,
) -> None:
    assert report_repo.find_by_appid(9999999) is None


def test_upsert_syncs_hidden_gem_to_games(
    game_repo: GameRepository, report_repo: ReportRepository
) -> None:
    """upsert() denormalizes hidden_gem_score (but not sentiment_score) onto games."""
    _seed_game(game_repo)
    report_repo.upsert({**_report(), "hidden_gem_score": 0.42})
    game = game_repo.find_by_appid(440)
    assert game is not None
    assert float(game.hidden_gem_score) == pytest.approx(0.42, abs=0.01)


def test_upsert_updated_hidden_gem_syncs_to_games(
    game_repo: GameRepository, report_repo: ReportRepository
) -> None:
    """A second upsert with a changed hidden_gem updates the games row."""
    _seed_game(game_repo)
    report_repo.upsert({**_report(), "hidden_gem_score": 0.42})
    report_repo.upsert({**_report(), "hidden_gem_score": 0.71})
    game = game_repo.find_by_appid(440)
    assert game is not None
    assert float(game.hidden_gem_score) == pytest.approx(0.71, abs=0.01)


def test_has_current_report_returns_true_when_version_matches(
    game_repo: GameRepository, report_repo: ReportRepository
) -> None:
    _seed_game(game_repo)
    report_repo.upsert(_report())
    assert report_repo.has_current_report(440, "3.0") is True


def test_has_current_report_returns_false_for_different_version(
    game_repo: GameRepository, report_repo: ReportRepository
) -> None:
    _seed_game(game_repo)
    report_repo.upsert(_report())
    assert report_repo.has_current_report(440, "4.0") is False


def test_has_current_report_returns_false_when_no_report(
    report_repo: ReportRepository,
) -> None:
    assert report_repo.has_current_report(9999999, "3.0") is False


def test_find_related_analyzed_ranks_by_tag_overlap(
    game_repo: GameRepository,
    report_repo: ReportRepository,
    tag_repo: TagRepository,
) -> None:
    # Target (440) has three tags. Candidate 500 shares all three, 501 shares
    # two, 502 shares one, 503 shares zero. All candidates are analyzed.
    for appid in (440, 500, 501, 502, 503):
        _seed_game(game_repo, appid)
        report_repo.upsert(_report(appid))
    target_tags = [
        {"appid": 440, "name": "Action", "votes": 100},
        {"appid": 440, "name": "FPS", "votes": 100},
        {"appid": 440, "name": "Multiplayer", "votes": 100},
    ]
    tag_repo.upsert_tags(target_tags)
    tag_repo.upsert_tags([
        {"appid": 500, "name": "Action", "votes": 100},
        {"appid": 500, "name": "FPS", "votes": 100},
        {"appid": 500, "name": "Multiplayer", "votes": 100},
    ])
    tag_repo.upsert_tags([
        {"appid": 501, "name": "Action", "votes": 100},
        {"appid": 501, "name": "FPS", "votes": 100},
    ])
    tag_repo.upsert_tags([{"appid": 502, "name": "Action", "votes": 100}])
    tag_repo.upsert_tags([{"appid": 503, "name": "Puzzle", "votes": 100}])

    rows = report_repo.find_related_analyzed(440, limit=6)
    appids = [row["appid"] for row in rows]
    # Target itself is always excluded. Zero-overlap (503) never appears.
    assert 440 not in appids
    assert 503 not in appids
    # Ordered by descending overlap.
    assert appids[:3] == [500, 501, 502]
    # one_liner surfaces from report_json.
    assert rows[0]["one_liner"] == "The gold standard of team shooters."


def test_find_related_analyzed_falls_back_when_overlap_thin(
    game_repo: GameRepository,
    report_repo: ReportRepository,
    tag_repo: TagRepository,
) -> None:
    # Target has tags that overlap only one candidate — below the 3-row floor
    # that triggers the "latest analyzed reports" fallback.
    for appid in (440, 500, 600, 601, 602):
        _seed_game(game_repo, appid)
        report_repo.upsert(_report(appid))
    tag_repo.upsert_tags([{"appid": 440, "name": "Action", "votes": 100}])
    tag_repo.upsert_tags([{"appid": 500, "name": "Action", "votes": 100}])
    # 600/601/602 have no tags — unreachable via overlap.

    rows = report_repo.find_related_analyzed(440, limit=6)
    appids = {row["appid"] for row in rows}
    # Fallback returned — every analyzed game except the target.
    assert 440 not in appids
    assert appids == {500, 600, 601, 602}


def test_find_related_analyzed_weights_by_votes(
    game_repo: GameRepository,
    report_repo: ReportRepository,
    tag_repo: TagRepository,
) -> None:
    # Overlap is weighted by game_tags.votes: a candidate with one strongly-
    # voted shared tag outranks a candidate with multiple weakly-voted shared
    # tags when the vote sum is lower.
    for appid in (440, 500, 501, 502):
        _seed_game(game_repo, appid)
        report_repo.upsert(_report(appid))
    tag_repo.upsert_tags([
        {"appid": 440, "name": "Action", "votes": 100},
        {"appid": 440, "name": "FPS", "votes": 100},
        {"appid": 440, "name": "Multiplayer", "votes": 100},
    ])
    # 500: one tag, heavily voted → score 1000
    tag_repo.upsert_tags([{"appid": 500, "name": "Action", "votes": 1000}])
    # 501: two tags, lightly voted → score 20
    tag_repo.upsert_tags([
        {"appid": 501, "name": "Action", "votes": 10},
        {"appid": 501, "name": "FPS", "votes": 10},
    ])
    # 502: three tags, moderately voted → score 150
    tag_repo.upsert_tags([
        {"appid": 502, "name": "Action", "votes": 50},
        {"appid": 502, "name": "FPS", "votes": 50},
        {"appid": 502, "name": "Multiplayer", "votes": 50},
    ])

    rows = report_repo.find_related_analyzed(440, limit=6)
    assert [row["appid"] for row in rows] == [500, 502, 501]


def test_find_related_analyzed_excludes_non_public_reports(
    db_conn, game_repo: GameRepository, report_repo: ReportRepository,
    tag_repo: TagRepository,
) -> None:
    # Reports flagged is_public=FALSE must not surface on public pages —
    # neither via the overlap path nor the recent-reports fallback.
    for appid in (440, 500, 501):
        _seed_game(game_repo, appid)
        report_repo.upsert(_report(appid))
    with db_conn.cursor() as cur:
        cur.execute("UPDATE reports SET is_public = FALSE WHERE appid = %s", (501,))
    db_conn.commit()
    tag_repo.upsert_tags([
        {"appid": 440, "name": "Action", "votes": 100},
        {"appid": 500, "name": "Action", "votes": 100},
        {"appid": 501, "name": "Action", "votes": 100},
    ])

    # Overlap path: private 501 is filtered out despite sharing tags.
    rows = report_repo.find_related_analyzed(440, limit=6)
    assert {row["appid"] for row in rows} == {500}

    # Fallback path: private 501 still excluded when overlap is thin.
    tag_repo.upsert_tags([{"appid": 440, "name": "Puzzle", "votes": 100}])
    rows = report_repo.find_related_analyzed(440, limit=6)
    assert 501 not in {row["appid"] for row in rows}


def test_find_related_analyzed_filters_non_game_types(
    game_repo: GameRepository,
    report_repo: ReportRepository,
    tag_repo: TagRepository,
) -> None:
    # The endpoint is explicitly "games like this" — analyzed DLC/demo/tool
    # rows that share tags with the target must not surface.
    _seed_game(game_repo, 440)
    _seed_game(game_repo, 500)  # type='game' — should appear
    _seed_game(game_repo, 501, type_="dlc")  # should be filtered out
    for appid in (440, 500, 501):
        report_repo.upsert(_report(appid))
    shared = [
        {"appid": 440, "name": "Action", "votes": 100},
        {"appid": 500, "name": "Action", "votes": 100},
        {"appid": 501, "name": "Action", "votes": 100},
    ]
    tag_repo.upsert_tags(shared)

    # Overlap path: DLC excluded despite sharing tags.
    rows = report_repo.find_related_analyzed(440, limit=6)
    assert {row["appid"] for row in rows} == {500}

    # Fallback path: DLC still excluded when overlap is thin.
    tag_repo.upsert_tags([{"appid": 440, "name": "Puzzle", "votes": 100}])
    rows = report_repo.find_related_analyzed(440, limit=6)
    assert 501 not in {row["appid"] for row in rows}
