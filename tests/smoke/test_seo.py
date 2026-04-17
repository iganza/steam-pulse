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
    saw_url = saw_domain = saw_games = saw_genre = False
    for url_el in root.iterfind("sm:url", ns):
        saw_url = True
        loc = url_el.findtext("sm:loc", default="", namespaces=ns)
        if "steampulse.io" in loc:
            saw_domain = True
        if "/games/" in loc:
            saw_games = True
        if "/genre/" in loc:
            saw_genre = True
        if saw_domain and saw_games and saw_genre:
            break
    assert saw_url, "expected at least one <url> entry in sitemap.xml"
    assert saw_domain, "expected steampulse.io in at least one <loc>"
    assert saw_games, "expected /games/ URL in sitemap"
    assert saw_genre, "expected /genre/ URL in sitemap"


def test_ai_crawler_not_blocked(api: httpx.Client) -> None:
    """GPTBot and peers must receive 200 on the homepage — no UA-based blocking."""
    r = api.get("/", headers={"User-Agent": "GPTBot/1.0"})
    assert r.status_code == 200, f"GPTBot got {r.status_code}"
