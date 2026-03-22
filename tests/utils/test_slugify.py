"""Tests for library_layer.utils.slugify."""

from library_layer.utils.slugify import slugify


def test_basic_slug() -> None:
    """Standard game name with spaces and numbers → clean slug with suffix."""
    assert slugify("Team Fortress 2", 440) == "team-fortress-2-440"


def test_slug_with_special_chars() -> None:
    """Unicode/punctuation is stripped, leaving only a-z0-9 and hyphens."""
    result = slugify("Hello, World! — Game®", 1)
    assert result == "hello-world-game-1"


def test_slug_empty_name() -> None:
    """Empty string with suffix falls back to 'app-{suffix}'."""
    assert slugify("", 440) == "app-440"


def test_slug_uniqueness() -> None:
    """Same name with different suffix → different slug."""
    s1 = slugify("Doom", 1)
    s2 = slugify("Doom", 2)
    assert s1 != s2
    assert s1.endswith("-1")
    assert s2.endswith("-2")


def test_slug_no_suffix() -> None:
    """Without suffix, returns base slug only."""
    assert slugify("Portal 2") == "portal-2"


def test_slug_consecutive_specials() -> None:
    """Multiple consecutive special chars collapse to single hyphen."""
    result = slugify("A...B---C")
    assert result == "a-b-c"
