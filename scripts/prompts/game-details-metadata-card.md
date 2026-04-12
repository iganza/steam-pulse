# Game Details Metadata Card

## Problem

The game detail page (`/games/{appid}/{slug}`) shows very little context about the
game itself. For unanalyzed games, there's a short description and then mostly empty
space. Even for analyzed games, there's no structured metadata about platforms,
controller support, achievements, etc. — information that helps users understand
the game at a glance.

We store rich metadata from Steam's API in the `games` table that is never surfaced
to the frontend.

## Research

Reviewed SteamDB, HowLongToBeat, PCGamingWiki, IsThereAnyDeal, ProtonDB,
OpenCritic, and Metacritic. Key findings:

- **No site renders Steam's full HTML description** (`about_the_game` /
  `detailed_description`). These contain embedded videos, GIFs, promotional
  banners, and custom formatting. Every site uses `short_desc` or their own
  summary instead.
- All sites show **structured metadata badges** — platforms, controller support,
  achievements, external scores.
- SteamDB-style compact metadata is the standard pattern for game intelligence sites.

## What to Add

A **"Game Details" card** on the game page showing structured metadata. Rendered
below the hero area, visible on both analyzed and unanalyzed game pages.

### Fields to expose (all already stored in `games` table)

| Field | DB Column | Type | Display |
|---|---|---|---|
| Platforms | `platforms` | JSONB `{windows, mac, linux}` | OS icon badges (Win/Mac/Linux) |
| Controller support | `controller_support` | TEXT `"full"/"partial"/NULL` | Badge: "Full Controller" / "Partial" / omit if null |
| Achievements | `achievements_total` | INTEGER | "142 Achievements" or omit if null/0 |
| Metacritic score | `metacritic_score` | INTEGER | Score badge with color (green/yellow/red) or omit if null |
| Website | `website` | TEXT | External link icon, or omit if null |
| Supported languages | `supported_languages` | TEXT | Language count + expandable list, or omit if null |
| Required age | `required_age` | INTEGER | "Mature 18+" badge if > 0, omit otherwise |

### Fields NOT to add

| Field | Why skip |
|---|---|
| `about_the_game` | HTML with embedded images/videos — rendering nightmare, no other site does it |
| `detailed_description` | Same issue as above |
| `requirements_windows/mac/linux` | Also HTML, niche interest |
| `dlc_appids` | Low value for effort |
| `content_descriptor_ids/notes` | Redundant with `required_age` |
| `support_url/support_email` | Low value — users go to Steam for support |

## Implementation

### 1. Backend — add fields to `/api/games/{appid}/report` response

**File:** `src/lambda-functions/lambda_functions/api/handler.py`

Add to the `game_meta` dict in `get_game_report()`:

```python
"platforms": game.platforms,              # JSONB {windows, mac, linux}
"controller_support": game.controller_support,  # "full" | "partial" | None
"achievements_total": game.achievements_total,  # int | None
"metacritic_score": game.metacritic_score,      # int | None
"website": game.website,                        # str | None
"supported_languages": game.supported_languages, # str | None
"required_age": game.required_age,              # int (default 0)
```

### 2. Frontend types — extend the game report response type

**File:** `frontend/lib/api.ts`

Add to the `game?` type in `getGameReport()`:

```typescript
platforms?: { windows?: boolean; mac?: boolean; linux?: boolean } | null;
controller_support?: string | null;
achievements_total?: number | null;
metacritic_score?: number | null;
website?: string | null;
supported_languages?: string | null;
required_age?: number | null;
```

### 3. Frontend — new `GameDetailsCard` component

**File:** `frontend/components/game/GameDetailsCard.tsx`

Compact card with horizontal badge layout. Design guidelines:

- Use the existing design system (mono font for labels, muted-foreground colors)
- Horizontal flow of badges/chips, wrapping on mobile
- Platform badges: small OS icons (lucide: `Monitor`, `Apple`, `Laptop` or similar)
- Controller badge: `Gamepad2` icon
- Metacritic: colored circle (green >= 75, yellow >= 50, red < 50)
- Achievements: `Trophy` icon + count
- Languages: show count, tooltip or expandable for full list
- Website: `ExternalLink` icon, opens in new tab
- Mature badge: only if `required_age > 0`
- Omit any badge where the data is null/0 — no empty placeholders

### 4. Wire into game page

**File:** `frontend/app/games/[appid]/[slug]/page.tsx`

Pass the new fields through `gameData` to `GameReportClient`.

**File:** `frontend/app/games/[appid]/[slug]/GameReportClient.tsx`

Render `<GameDetailsCard>` below the hero / Steam Facts area. Show on both
analyzed and unanalyzed pages — this is game context, not analysis.

### 5. Update frontend tests

**File:** `frontend/tests/fixtures/mock-data.ts`

Add the new fields to mock game data.

**File:** `frontend/tests/fixtures/api-mock.ts`

Update API mock to return the new fields.

## Verification

1. Run API locally, hit `/api/games/440/report` (TF2) — confirm new fields present
2. Load `/games/440/team-fortress-2` in browser — confirm badges render
3. Load a game with null metacritic / no achievements — confirm those badges are omitted
4. Load a game with controller support — confirm badge shows
5. Check mobile layout — badges should wrap cleanly
6. Run `cd frontend && npm run test:e2e` — confirm no regressions
7. Run `poetry run pytest tests/ -v` — confirm backend tests pass
