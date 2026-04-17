"""Smoke tests for site-wide SEO surfaces: robots.txt, sitemap.xml, AI crawler access."""

import xml.etree.ElementTree as ET

import httpx
import pytest

pytestmark = pytest.mark.smoke


def test_robots_txt(api: httpx.Client) -> None:
    r = api.get("/robots.txt")
    assert r.status_code == 200
    body = r.text
    for ua in ("Googlebot", "GPTBot", "ClaudeBot", "PerplexityBot", "Twitterbot"):
        assert ua in body, f"missing User-agent rule for {ua}"
    assert "Disallow: /api/" in body
    assert "Sitemap:" in body
    assert "sitemap.xml" in body


def test_sitemap_xml(api: httpx.Client) -> None:
    r = api.get("/sitemap.xml")
    assert r.status_code == 200
    root = ET.fromstring(r.text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = root.findall("sm:url", ns)
    assert len(urls) > 1000, f"expected >1000 <url> entries, got {len(urls)}"
    locs = [u.findtext("sm:loc", default="", namespaces=ns) for u in urls]
    assert any("steampulse.io" in loc for loc in locs)
    assert any("/games/" in loc for loc in locs)


def test_ai_crawler_not_blocked(api: httpx.Client) -> None:
    """GPTBot and peers must receive 200 on the homepage — no UA-based blocking."""
    r = api.get("/", headers={"User-Agent": "GPTBot/1.0"})
    assert r.status_code == 200, f"GPTBot got {r.status_code}"
