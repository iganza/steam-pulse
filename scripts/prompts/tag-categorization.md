# Group Player Tags into Categories

## Problem

SteamPulse has ~446 unique player tags from Steam store pages. They're displayed as flat
lists with small hard-coded limits — 8 in the navbar, 10 on Browse > Tags, 50 on the home
page. Users can't discover or browse tags effectively.

## Goal

Group all tags into 8 categories and update the UI to display them as organized,
browsable category sections. Every tag gets classified — none left as "Other" if avoidable.

## UX Research — Industry Patterns

Research into how Steam, GOG, itch.io, Amazon, Etsy, Spotify, and UX literature (NN/g,
Baymard Institute) handle large tag taxonomies:

**What works:**
- **Faceted category groups** with 5-7 visible items per group, "Show all" for the rest
  (Amazon, GOG sidebar pattern). Topical clustering outperforms flat lists for both casual
  browsing and purposeful searching.
- **Popularity sort** within categories, not alphabetical — users find useful tags faster.
- **Game counts on every tag pill** — critical for user confidence (Baymard).
- **Search/type-to-filter** input above the tag grid — with 446 tags, even well-grouped
  accordions won't help the user looking for "Sokoban". Steam, GOG both provide this.
- **Mix categories in flat navbar/filter lists** — top-10 by raw count would all be Genre
  tags. Show 2-3 from Genre, 2-3 from Theme, 2-3 from Gameplay for better discovery.

**What to avoid:**
- **Tag clouds** — research consistently shows users ignore them. Do not use.
- **All 446 tags visible at once** — even grouped, that's overwhelming. Cap per category.
- **Alphabetical sort** within categories — popularity is proven more useful.

**Pattern choices per location:**

| Location | Pattern | Details |
|---|---|---|
| Home page "Browse by Tag" | **Accordion categories** | Top 3 expanded (Genre, Sub-Genre, Theme). 5-7 pills per group. "Show all N" expands. |
| Dedicated tag browse page | **Tabbed categories** or **all-expanded accordion** | Users come here to explore — don't hide content. 8 horizontal tabs (Genre \| Sub-Genre \| ...) showing all tags in the active tab. |
| Navbar Browse dropdown | **Flat top-10, mixed categories** | 2-3 Genre + 2-3 Theme + 2-3 Gameplay. No hierarchy. |
| FilterBar / Search filters | **Flat top-20 + searchable** | Horizontal pills or scrollable list. Optional type-to-filter input. |

**Key NN/g finding on accordions:** They work when users need 1-2 sections, not most/all.
On the dedicated browse page, prefer tabs or default-all-expanded over collapsed accordions.

## Current State

**Database:** `tags(id, name, slug, steam_tag_id)` — flat, no category column.

**API:** `GET /api/tags/top?limit=N` returns flat list from `GameRepository.list_tags()`:
```sql
SELECT t.id, t.name, t.slug, COUNT(gt.appid) AS game_count
FROM tags t LEFT JOIN game_tags gt ON gt.tag_id = t.id
GROUP BY t.id, t.name, t.slug
ORDER BY game_count DESC, t.name LIMIT %s
```

**Frontend consumers (all use flat lists):**
- Home page `app/page.tsx:187-213`: `getTopTags(50)` → pill buttons
- Navbar `components/layout/Navbar.tsx:112-128`: `fetch("/api/tags/top?limit=10")`
- FilterBar `components/toolkit/FilterBar.tsx:344-364`: `fetch("/api/tags/top?limit=20")`
- Search `app/search/SearchClient.tsx`: `fetch("/api/tags/top?limit=30")`
- Tag page `app/tag/[slug]/page.tsx:40-49`: `getTopTags(50)` → top 8 related

**Frontend types** (`lib/types.ts:128-134`):
```typescript
export interface Tag {
  id: number; name: string; slug: string;
  game_count?: number; analyzed_count?: number;
}
```

---

## Categories

8 categories. Display order matters — this is the order they appear in the UI:

| # | Category | Description |
|---|---|---|
| 1 | **Genre** | Core game genres — what kind of game is it |
| 2 | **Sub-Genre** | Specific genre variants and cross-genre hybrids |
| 3 | **Theme & Setting** | World, era, narrative flavor |
| 4 | **Gameplay** | Core mechanics, systems, and design patterns |
| 5 | **Player Mode** | How many players, what kind of multiplayer |
| 6 | **Visuals & Viewpoint** | Art style, camera perspective, graphics |
| 7 | **Mood & Tone** | Emotional quality, difficulty feel, atmosphere |
| 8 | **Other** | Software tools, meta-tags, niche tags |

---

## Full Tag Classification (all 446 tags)

### Genre
Action, Adventure, RPG, Strategy, Simulation, Puzzle, Platformer, Racing, Sports,
Shooter, Fighting, Card Game, Board Game, Rhythm, Trivia, Pinball, Word Game

### Sub-Genre
Action-Adventure, Action Roguelike, Action RPG, Action RTS, Arcade, Arena Shooter,
Auto Battler, Battle Royale, Beat 'em up, Boomer Shooter, Boss Rush, Bullet Hell,
Card Battler, Character Action Game, City Builder, Clicker, Colony Sim, CRPG,
Dating Sim, Deckbuilding, Dungeon Crawler, Escape Room, Extraction Shooter, FPS,
God Game, Grand Strategy, Hack and Slash, Hero Shooter, Hidden Object, Idler,
Immersive Sim, Interactive Fiction, JRPG, Life Sim, Looter Shooter, Match 3,
Metroidvania, MMORPG, MOBA, Musou, Mystery Dungeon, On-Rails Shooter, Open World
Survival Craft, Otome, Party-Based RPG, Point & Click, Precision Platformer,
Puzzle Platformer, Real Time Tactics, Roguelike, Roguelike Deckbuilder, Roguelite,
Roguevania, RPGMaker, RTS, Runner, Shoot 'Em Up, Side Scroller, Sokoban, Solitaire,
Souls-like, Space Sim, Spectacle fighter, Strategy RPG, Survival Horror, Tabletop,
Tactical RPG, Third-Person Shooter, Top-Down Shooter, Tower Defense, Trading Card Game,
Traditional Roguelike, Turn-Based Combat, Turn-Based Strategy, Turn-Based Tactics,
Twin Stick Shooter, Visual Novel, Walking Simulator, Wargame, 2D Fighter, 2D Platformer,
3D Fighter, 3D Platformer, 4X, Automobile Sim, Farming Sim, Hobby Sim, Job Simulator,
Medical Sim, Outbreak Sim, Political Sim, Shop Keeper

### Theme & Setting
Aliens, Alternate History, America, Anime, Assassination (Assassin), Capitalism,
Cats, Cold War, Comic Book, Conspiracy, Crime, Cyberpunk, Dark Fantasy, Demons,
Dinosaurs, Dog, Dragons, Dungeons & Dragons, Dwarf, Dystopian, Elf, Faith, Fantasy,
Foreign, Fox, Futuristic, Games Workshop, Gothic, Hacking, Heist, Historical,
Horses, Illuminati, LEGO, Lovecraftian, Magic, Mars, Martial Arts, Mechs, Medieval,
Military, Modern, Mythology, Nature, Naval, Ninja, Noir, Nostalgia, Parkour, Pirates,
Post-apocalyptic, Psychedelic, Robots, Rome, Romance, Sailing, Sci-fi, Science,
Snow, Space, Spaceships, Steampunk, Submarine, Superhero, Supernatural, Surreal,
Swordplay, Tanks, Time Travel, Trains, Transhumanism, Underground, Underwater,
Vampire, Vikings, Warhammer 40K, War, Werewolves, Western, World War I, World War II,
Zombies, Birds, Lemmings

### Gameplay
Base Building, Building, Choices Matter, Choose Your Own Adventure, Co-op,
Co-op Campaign, Combat, Combat Racing, Competitive, Controller, Cooking, Crafting,
Creature Collector, Deckbuilding, Destruction, Dice, Diplomacy, Driving, Dynamic
Narration, Economy, Exploration, Farming, Fishing, Flight, Gambling, Grid-Based Movement,
Gun Customization, Hex Grid, Hunting, Inventory Management, Investigation, Level Editor,
Loot, Management, Mining, Mod, Moddable, Multiple Endings, Narration, Narrative,
Naval Combat, Nonlinear, Open World, Perma Death, Physics, Procedural Generation,
Programming, PvE, PvP, Quick-Time Events, Real-Time, Real-Time with Pause,
Resource Management, Sandbox, Score Attack, Shoot 'Em Up (if not sub-genre), Social
Deduction, Stealth, Survival, Team-Based, Time Attack, Time Management, Time
Manipulation, Touch-Friendly, Trading, Turn-Based, Typing, Vehicular Combat,
Voice Control, Character Customization, Class-Based, Collectathon, Archery, Bowling,
Boxing, Cricket, Cycling, Golf, Hockey, Mini Golf, Pool, Skateboarding, Skating,
Skiing, Snooker, Snowboarding, Tennis, Volleyball, Wrestling, Baseball, Basketball,
Football (American), Football (Soccer), Rugby, Offroad, Motocross, Motorbike, BMX,
ATV, Bikes, Jet, Sniper, Bullet Time

### Player Mode
Singleplayer, Multiplayer, Local Co-Op, Local Multiplayer, Online Co-Op,
Massively Multiplayer, Split Screen, Asynchronous Multiplayer, 4 Player Local,
Party Game, Party, eSports

### Visuals & Viewpoint
2D, 2.5D, 3D, First-Person, Third Person, Top-Down, Isometric, Pixel Graphics,
Voxel, Hand-drawn, Cartoon, Cartoony, Colorful, Minimalist, Realistic, Stylized,
Cinematic, Beautiful, Abstract, VR, Asymmetric VR, 360 Video, 3D Vision, 6DOF,
FMV, TrackIR, Mouse only, Text-Based

### Mood & Tone
Atmospheric, Casual, Cozy, Cute, Dark, Dark Comedy, Dark Humor, Difficult,
Drama, Emotional, Epic, Experimental, Family Friendly, Fast-Paced, Funny,
Comedy, Gore, Blood, Great Soundtrack, Horror, Immersive, Jump Scare, Linear,
Lore-Rich, Mature, Memes, NSFW, Nudity, Sexual Content, Hentai, Parody,
Philosophical, Political, Politics, Psychedelic, Psychological, Psychological Horror,
Relaxing, Replay Value, Retro, Satire, Short, Silent Protagonist, Story Rich,
Thriller, Unforgiving, Villain Protagonist, Violent, Well-Written, Wholesome,
Addictive, Classic, Cult Classic, Intentionally Awkward Controls, Old School,
LGBTQ+, Female Protagonist, Sequel, Remake, Reboot

### Other
Animation & Modeling, Audio Production, Benchmark, Coding, Crowdfunded, Design &
Illustration, Documentary, Early Access, Education, Electronic, Electronic Music,
Episodic, Experience, Feature Film, Free to Play, Game Development, GameMaker,
Gaming, Hardware, Indie, Instrumental Music, Kickstarter, Movie, Music, Music-Based
Procedural Generation, Photo Editing, Rock Music, Software, Software Training,
Soundtrack, Steam Machine, Tutorial, Utilities, Video Production, Web Publishing,
8-bit Music, Ambient, Agriculture, Spelling, Transportation, Mahjong, Chess, Logic

---

## What to Build

### 1. Migration `0014_add_tag_category.sql`

**File:** `src/lambda-functions/migrations/0014_add_tag_category.sql`

```sql
-- depends: 0013_add_steam_tag_id

ALTER TABLE tags ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'Other';
```

Then one `UPDATE` statement per category, using `WHERE name IN (...)` with the full
tag lists above. Use exact tag names from the DB (case-sensitive).

```sql
UPDATE tags SET category = 'Genre' WHERE name IN ('Action', 'Adventure', 'RPG', ...);
UPDATE tags SET category = 'Sub-Genre' WHERE name IN ('Action-Adventure', ...);
UPDATE tags SET category = 'Theme & Setting' WHERE name IN ('Aliens', ...);
UPDATE tags SET category = 'Gameplay' WHERE name IN ('Base Building', ...);
UPDATE tags SET category = 'Player Mode' WHERE name IN ('Singleplayer', ...);
UPDATE tags SET category = 'Visuals & Viewpoint' WHERE name IN ('2D', ...);
UPDATE tags SET category = 'Mood & Tone' WHERE name IN ('Atmospheric', ...);
-- 'Other' is the column default — no UPDATE needed for that category.

CREATE INDEX IF NOT EXISTS idx_tags_category ON tags(category);
```

**Important:** Some tags appear in multiple lists above (ambiguous classification).
Choose one category per tag — the most intuitive one. Cross-reference the full 446-tag
list from production DB to ensure every tag is covered.

### 2. Update `schema.py`

**File:** `src/library-layer/library_layer/schema.py`

- Add `category TEXT DEFAULT 'Other'` to the `tags` CREATE TABLE block
- Add ALTER TABLE stub at bottom: `"ALTER TABLE tags ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'Other'"`

### 3. Update Tag Model

**File:** `src/library-layer/library_layer/models/tag.py`

Add field:
```python
category: str = "Other"
```

### 4. Update `game_repo.py` — `list_tags()` + new `list_tags_grouped()`

**File:** `src/library-layer/library_layer/repositories/game_repo.py`

**Modify `list_tags()`** (line 352): Add `t.category` to SELECT and GROUP BY.

**Add `list_tags_grouped()`:**
```python
def list_tags_grouped(self, limit_per_category: int = 20) -> list[dict]:
    """Return tags grouped by category, ordered by game_count within each group."""
    rows = self._fetchall(
        """
        SELECT t.category, t.id, t.name, t.slug, COUNT(gt.appid) AS game_count
        FROM tags t
        LEFT JOIN game_tags gt ON gt.tag_id = t.id
        GROUP BY t.category, t.id, t.name, t.slug
        HAVING COUNT(gt.appid) > 0
        ORDER BY t.category, game_count DESC, t.name
        """,
    )
    from itertools import groupby
    grouped = []
    for category, group_rows in groupby(rows, key=lambda r: r["category"]):
        tags = [dict(r) for r in group_rows][:limit_per_category]
        grouped.append({"category": category, "tags": tags})
    # Sort by display order
    order = ["Genre", "Sub-Genre", "Theme & Setting", "Gameplay",
             "Player Mode", "Visuals & Viewpoint", "Mood & Tone", "Other"]
    grouped.sort(key=lambda g: order.index(g["category"]) if g["category"] in order else 99)
    return grouped
```

### 5. Update `tag_repo.py` — include `category` in reads

**File:** `src/library-layer/library_layer/repositories/tag_repo.py`

Add `t.category` to the SELECT in:
- `find_tags_for_game()` (line 148)
- `find_tags_for_appids()` (line 175)

### 6. API Endpoint

**File:** `src/lambda-functions/lambda_functions/api/handler.py`

Add new endpoint:
```python
@app.get("/api/tags/grouped")
async def list_tags_grouped(limit_per_category: int = 20) -> list[dict]:
    limit_per_category = min(limit_per_category, 50)
    return _game_repo.list_tags_grouped(limit_per_category=limit_per_category)
```

Existing `GET /api/tags/top` automatically gains `category` field — no change needed.

### 7. Frontend Types

**File:** `frontend/lib/types.ts`

Add to `Tag` interface:
```typescript
category?: string;
```

Add new interface:
```typescript
export interface TagGroup {
  category: string;
  tags: Tag[];
}
```

### 8. Frontend API Function

**File:** `frontend/lib/api.ts`

Add:
```typescript
export async function getTagsGrouped(limitPerCategory = 20): Promise<TagGroup[]> {
  return apiFetch<TagGroup[]>(`/api/tags/grouped?limit_per_category=${limitPerCategory}`, {
    next: { revalidate: 86400 },
  });
}
```

### 9. Home Page — Grouped Tag Display

**File:** `frontend/app/page.tsx`

Replace the flat "Browse by Tag" section (lines 187-213) with grouped, expandable
category sections. Call `getTagsGrouped()` instead of `getTopTags(50)`.

Layout:
```
Browse by Tag                                    [🔍 Search tags...]
  Genre ▾
    [Action 12,340] [RPG 8,920] [Strategy 7,100] [Puzzle 5,400] [Platformer 4,800] ... Show all 17 →
  Sub-Genre ▾
    [Roguelike 3,400] [Metroidvania 2,100] [City Builder 1,800] [FPS 9,200] ...       Show all 85 →
  Theme & Setting ▾
    [Fantasy 6,100] [Sci-Fi 5,200] [Horror 4,300] [Medieval 2,900] ...                Show all 72 →
  Gameplay ▸  (collapsed)
  Player Mode ▸  (collapsed)
  ...
```

**UX requirements (from research):**
- Top 3 categories expanded by default (Genre, Sub-Genre, Theme & Setting)
- **5-7 tag pills visible per category**, not 20. "Show all N →" link expands inline.
- **Game counts on every pill** — critical for user confidence
- Sort by game_count DESC within each category (not alphabetical)
- Add a **search/type-to-filter input** above the tag grid that filters across all
  categories as you type (high-impact for 446 tags — users looking for "Sokoban" or
  "Submarine" won't find it by browsing)
- "See all tags" link to dedicated browse page

### 10. Tag Page — Same-Category Related Tags

**File:** `frontend/app/tag/[slug]/page.tsx`

The "Related Tags" section currently shows arbitrary top-8. Instead, show tags from
the **same category** as the current tag. The `category` field is now on each tag
from the API response.

### 11. Navbar — Mixed-Category Top Tags

**File:** `frontend/components/layout/Navbar.tsx`

Currently fetches top-10 by raw game_count, which skews heavily toward Genre tags.
**Mix categories**: show 2-3 from Genre, 2-3 from Theme, 2-3 from Gameplay for better
discovery surface. Can either:
- Use `GET /api/tags/grouped?limit_per_category=3` and flatten client-side
- Or add a `GET /api/tags/top?diverse=true` mode that picks top N across categories

Keep the flat pill layout — no hierarchy in the navbar.

### 12. FilterBar / Search — Unchanged + Optional Search

These keep using `GET /api/tags/top` with flat lists — they gain the `category` field
which they can ignore for now:
- FilterBar tag popover (`components/toolkit/FilterBar.tsx`)
- Search page tag filter (`app/search/SearchClient.tsx`)

Optional enhancement: add a type-to-filter input in the FilterBar popover to let users
search across all tags, not just the visible top-20.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `src/lambda-functions/migrations/0014_add_tag_category.sql` | Create — add column + classify all 446 tags |
| `src/library-layer/library_layer/schema.py` | Add `category` to tags table + ALTER stub |
| `src/library-layer/library_layer/models/tag.py` | Add `category` field |
| `src/library-layer/library_layer/repositories/game_repo.py` | Add `t.category` to `list_tags()`, add `list_tags_grouped()` |
| `src/library-layer/library_layer/repositories/tag_repo.py` | Add `t.category` to read queries |
| `src/lambda-functions/lambda_functions/api/handler.py` | Add `GET /api/tags/grouped` |
| `frontend/lib/types.ts` | Add `category` to Tag, add TagGroup |
| `frontend/lib/api.ts` | Add `getTagsGrouped()` |
| `frontend/app/page.tsx` | Replace flat tag section with grouped display |
| `frontend/app/tag/[slug]/page.tsx` | Show same-category related tags |

## Testing

- `poetry run pytest -v` — all existing tests pass
- `poetry run ruff check . && poetry run ruff format .` — clean
- Verify migration locally: `bash scripts/dev/migrate.sh`
- Check: `SELECT category, COUNT(*) FROM tags GROUP BY category ORDER BY category;` — all 446 classified
- Check: `SELECT * FROM tags WHERE category = 'Other';` — should be minimal (software/meta tags only)
- Hit `GET /api/tags/grouped` locally — verify 8 categories with tags sorted by game_count
- Frontend: verify home page shows grouped tags, tag page shows same-category related tags

## UX Sources Consulted

**Game platform references:**
- Steam tag browse: https://store.steampowered.com/tag/browse/
- Steam tags documentation: https://partner.steamgames.com/doc/store/tags
- GOG catalog filtering: https://www.gog.com/en/news/introducing_new_ways_to_browse_and_filter_game_catalog
- itch.io enhanced tagging: https://itch.io/updates/enhanced-itchio-tagging-system
- Steam page optimization: https://presskit.gg/field-guides/steam-page-optimization-guide

**UX research & best practices:**
- NN/g — Accordions on desktop: https://www.nngroup.com/articles/accordions-on-desktop/
- NN/g — Accordions for complex content: https://www.nngroup.com/articles/accordions-complex-content/
- NN/g — Filter categories and values: https://www.nngroup.com/articles/filter-categories-values/
- Algolia — Search filter best practices: https://www.algolia.com/blog/ux/search-filter-ux-best-practices
- LogRocket — Filtering UX/UI patterns: https://blog.logrocket.com/ux-design/filtering-ux-ui-design-patterns-best-practices/
- Shopify — Faceted navigation: https://www.shopify.com/blog/faceted-navigation
- Fact Finder — Faceted search practices: https://www.fact-finder.com/blog/faceted-search/
- Tag cloud critique: https://medium.com/design-bootcamp/semantic-scramble-the-tag-cloud-dilemma-fae3998d5c6d
- Tags UX to implementation: https://schof.co/tags-ux-to-implementation/

## Constraints

- Backwards-compatible migration (new column has DEFAULT)
- No new tables — single TEXT column on existing `tags` table
- Existing `GET /api/tags/top` unchanged (gains field, no breaks)
- `upsert_tags()` does not need changes — new tags get 'Other' from column default
- Some tags listed above may appear ambiguous — pick one category. The classification
  can be refined later with a simple UPDATE statement.
