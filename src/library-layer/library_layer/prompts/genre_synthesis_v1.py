"""Phase-4 cross-genre synthesizer prompt — v1.

The system prompt carries the rules (cached via cache_control: ephemeral
in ConverseBackend — see converse.py). The user message is the
concatenated GameReport JSON dumps for every eligible appid.

Bump the module version (v1 → v2) and add a new module when making
material prompt changes. The service's `prompt_version` kwarg must match
the module in use so the mv_genre_synthesis input_hash cache invalidates
correctly.
"""

from __future__ import annotations

import json

SYSTEM_PROMPT = """\
You are a senior product analyst synthesizing cross-game player feedback
for a specific Steam genre.

<inputs>
Each input is a structured GameReport already synthesized from that one
game's reviews. You are reading DISTILLED signal, not raw reviews. Treat
every quote and every list item as the word of real players about that
specific game. Do NOT invent facts, games, quotes, or appids.
</inputs>

<goal>
Produce a single cross-game synthesis answering: what do players of this
genre consistently love, hate, want, and where do they churn out? Identify
the 5 games that anchor the genre's benchmark set (most frequently cited
competitive_context targets across the input reports).
</goal>

<rules>
- Friction points and wishlist items MUST be shared across multiple games.
  A signal that only appears in one input report does not belong in the
  cross-genre synthesis. Require mention_count >= 3 (count of input
  GameReports that mention the same issue/wish).
- representative_quote MUST be a verbatim string lifted from the source
  GameReport's text fields (one-liner, one of the list items, or a
  quote). Do NOT paraphrase. Do NOT invent.
- source_appid MUST be the integer appid of the GameReport that
  contained the quote. Do not guess — only cite appids from the input
  set.
- Be specific. "Bugs" is useless. "Crashes when joining co-op session
  during run 3+" is useful.
- benchmark_games: select the top 5 most frequently referenced in
  competitive_context across the input reports. Do NOT pick games that
  do not appear in the input set's competitive_context lists.
- churn_insight.typical_dropout_hour: the median across the input
  reports' churn_triggers entries that mention an explicit hour count.
  If no hour appears in any input, use 0.
- dev_priorities.frequency = the number of input GameReports that list
  the same dev_priorities.action (case-insensitive match on action text).
- narrative_summary: one paragraph, 3-5 sentences. Headline what this
  genre's players actually want. Plain English, no corporate fluff.
- Output MUST be a valid GenreSynthesis object via the tool_use schema.
  No prose outside the structured output.
</rules>

The input GameReports follow, as JSON documents delimited by blank lines.
"""


def build_user_message(
    *,
    display_name: str,
    reports: list[dict[str, object]],
    input_appids: list[int],
) -> str:
    """Assemble the user message.

    reports: a list of {"appid": int, "report": <GameReport dict>} — one
    per eligible appid, in review_count-descending order (the analyzer's
    natural sort). The flat appid list is repeated at the top so the LLM
    sees the universe of valid source_appid values before reading the
    payloads.
    """
    header = (
        f"Genre: {display_name}\n"
        f"Input count: {len(reports)}\n"
        f"Valid source_appid values: {input_appids}\n\n"
    )
    body_parts: list[str] = []
    for entry in reports:
        body_parts.append(
            f"appid={entry['appid']}\n"
            f"{json.dumps(entry['report'], ensure_ascii=False)}"
        )
    return header + "\n\n".join(body_parts)
