"""Slug generation utility."""

import re


def slugify(text: str, suffix: str | int | None = None) -> str:
    """Convert text to a URL-safe slug.

    Args:
        text: The text to slugify.
        suffix: Optional suffix appended with a dash (e.g. appid for uniqueness).

    Returns:
        A lowercase, hyphen-separated slug.

    Examples:
        slugify("Team Fortress 2", 440)  -> "team-fortress-2-440"
        slugify("Hello, World!")          -> "hello-world"
        slugify("", 440)                  -> "app-440"
    """
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if suffix is not None:
        return f"{base}-{suffix}" if base else f"app-{suffix}"
    return base or ""
