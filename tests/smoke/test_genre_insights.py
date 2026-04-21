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

        # Editorial columns (migration 0052) are always present as strings —
        # may be empty when the row hasn't been curated yet.
        assert isinstance(body.get("editorial_intro", ""), str)
        assert isinstance(body.get("churn_interpretation", ""), str)


@pytest.mark.parametrize("slug", ["roguelike-deckbuilder"])
def test_tag_insights_delivers_pdf_worthy_depth(api: httpx.Client, slug: str) -> None:
    """The free /genre/[slug]/ page shows a curated preview (5 friction,
    3 wishlist, 3 benchmarks, 2 dev priorities). The extra depth beyond
    that preview is what the paid PDF delivers, so the underlying row
    must carry enough material to back that promise.
    """
    r = api.get(f"/api/tags/{slug}/insights")
    if r.status_code == 404:
        pytest.skip(f"no synthesis row for {slug} yet")
    assert r.status_code == 200
    body = r.json()
    s = body["synthesis"]
    assert body["narrative_summary"].strip() != ""
    assert len(s["friction_points"]) >= 10, "free preview takes top 5; PDF needs 5+ more"
    assert len(s["wishlist_items"]) >= 10, "free preview takes top 3; PDF needs 7+ more"
    assert len(s["benchmark_games"]) >= 5, "free preview takes top 3; PDF needs 2+ more"
    assert len(s["dev_priorities"]) >= 3, "teaser shows 2; full table needs more"


def test_tag_insights_unknown_slug_returns_404(api: httpx.Client) -> None:
    r = api.get("/api/tags/this-slug-will-never-exist-xyz123/insights")
    assert r.status_code == 404
