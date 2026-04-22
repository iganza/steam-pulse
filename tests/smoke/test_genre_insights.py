"""Smoke test — /api/tags/{slug}/insights endpoint reachable + shape valid.

The synthesis row may or may not exist for a given slug depending on
whether the weekly scan has run and whether Phase-3 has analyzed enough
games under that tag. Both 200 and 404 are legitimate responses — this
test asserts the endpoint is wired correctly, not that data is seeded.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.smoke


@pytest.mark.parametrize("slug", ["roguelike-deckbuilder"])
def test_tag_insights_endpoint_responds(api: httpx.Client, slug: str) -> None:
    r = api.get(f"/api/tags/{slug}/insights")
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        body = r.json()
        # Shape check: top-level row fields + nested GenreSynthesis.
        assert body["slug"] == slug
        assert "synthesis" in body
        s = body["synthesis"]
        assert "narrative_summary" in s
        assert "friction_points" in s and isinstance(s["friction_points"], list)
        assert "wishlist_items" in s and isinstance(s["wishlist_items"], list)
        assert "benchmark_games" in s and isinstance(s["benchmark_games"], list)
        assert "churn_insight" in s
        assert "dev_priorities" in s and isinstance(s["dev_priorities"], list)

        # Editorial columns (migration 0052) — API contract check. Asserts
        # the endpoint's response shape always includes these fields, even
        # when the DB column is unset (the Pydantic model defaults to "").
        # This does NOT catch a silently-dropped SELECT in the repo: that
        # regression would still return defaults via Pydantic — cover it
        # with a repository-level test instead (see
        # tests/repositories/test_genre_synthesis_repo.py).
        assert "editorial_intro" in body
        assert isinstance(body["editorial_intro"], str)
        assert "churn_interpretation" in body
        assert isinstance(body["churn_interpretation"], str)


# The "PDF delivers more than the free preview" promise is an editorial
# contract, not a runtime invariant — the synthesizer's Pydantic schema
# accepts lists as short as 1 (tolerant for sparse cohorts), and hard
# smoke thresholds are flaky against the weekly re-synthesis. Verify
# this promise manually before publishing a new genre page instead.


def test_tag_insights_unknown_slug_returns_404(api: httpx.Client) -> None:
    r = api.get("/api/tags/this-slug-will-never-exist-xyz123/insights")
    assert r.status_code == 404
