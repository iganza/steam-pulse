# Landing Page Positioning & Messaging — Design Spec

What SteamPulse says about itself when someone first arrives.

---

## The Problem with "Discover Steam Games"

The current hero says "Discover Steam Games." This:

1. **Positions against Steam itself** — Steam is the discovery platform. Competing
   on discovery is like building a better Google homepage.
2. **Hides the unique value** — nobody else turns raw review data into structured
   intelligence at scale. The hero should lead with what's differentiated, not
   commodity.
3. **Speaks only to gamers** — developers, publishers, and marketing people (the
   paying audience) see "discover games" and bounce. It reads as a consumer browser,
   not a professional tool.
4. **Undersells the data** — SteamPulse has 100k+ games, 17 matviews, audience
   overlap analysis, revenue estimates, trend analytics, competitive positioning.
   "Discover" reduces all of that to "find a game to play."

---

## Brand Identity

**What SteamPulse is**: A game intelligence platform that tells you what players
actually think — and what that means for the market.

**What SteamPulse is NOT**: A game store, a game discovery engine, a review
aggregator, or a Steam replacement.

**One-line positioning**: "Steam game intelligence — from every review, for
every game."

**The insight both audiences share**: Everyone — gamers and developers alike — wants
to know what players *really* think, beyond star ratings and "Mostly Positive."
SteamPulse turns raw player data into structured intelligence so you don't have to
read 10,000 reviews yourself.

**Language rule**: Never use the word "AI." Use "intelligence", "analysis",
"insights", "structured", or describe the capability without naming the technology.
The product is about what it delivers, not how it works.

---

## How Competitors Position

| Platform | Hero / Tagline | Audience Signal |
|---|---|---|
| **VGInsights** | "Games industry data and analysis" | Industry professionals |
| **Gamalytic** | "An overview of Steam game prices, sales, ratings and much more!" | Researchers, developers |
| **GameDiscoverCo** | "How do players find, buy, and enjoy your games?" | Developers, publishers |
| **GG Insights** | "Your #1 tool for gathering insights from Steam" | Developers, researchers |
| **SteamDB** | (no tagline — pure data) | Enthusiasts, data nerds |
| **SteamPulse (current)** | "Discover Steam Games" | Gamers (accidentally) |

Every competitor that charges money leads with intelligence, data, or insights —
not discovery. SteamPulse should join this positioning.

**But none of them address gamers at all.** That's the dual-audience opportunity:
SteamPulse can be the only platform that serves both audiences from the same
landing page without forcing a fork.

---

## What Every Game Has at Launch (No Report Required)

This is critical for the hero promise. Even without a synthesized report, every
game page already delivers substantial intelligence:

| Feature | What It Shows | Audience |
|---|---|---|
| **Review sentiment timeline** | Weekly positive % over the game's lifetime | Both |
| **Playtime-sentiment analysis** | Sentiment by playtime bucket + churn wall detection | Both |
| **Review velocity** | Monthly review volume trend (24mo) + acceleration signal | Both |
| **Audience overlap** | Which games the same reviewers play + shared sentiment | Both |
| **Benchmarks** | Percentile ranking vs genre + year + price cohort | Dev |
| **Revenue estimates** | Estimated owners + gross revenue (Boxleiter v1) | Dev |
| **Early Access impact** | Sentiment delta between EA and post-launch reviews | Both |
| **Top reviews** | Most helpful/funny reviews with playtime + metadata | Gamer |
| **Genre/tag analytics** | Price positioning, release timing, platform gaps per genre | Dev |
| **Developer portfolio** | All games by developer with sentiment trajectory | Both |

The hero doesn't need to promise reports. It promises **understanding** — and the
structured data delivers on that for every single game. Reports make it deeper for
the games that have them; they don't define the product.

---

## The Dual-Audience Best Practice

**Don't make users self-select.** No "I'm a developer" / "I'm a gamer" buttons.
No split hero. No tabbed landing page.

Instead: **Lead with the universal value, then let the content naturally fork.**

The universal value is: **understanding what players think and what the market
looks like.**

- A gamer asks before buying: "Is this game actually good? What do people with
  100+ hours think? Where do players drop off? Is the community healthy?"
- A developer asks before building: "What do players in my genre hate? Where are
  my competitors weak? What price point works? When should I launch?"

Same data, different lens. The landing page serves both by surfacing the
intelligence prominently, then branching into audience-specific sections below
the fold.

---

## Recommended Page Structure

### 1. Hero (above the fold)

**Headline direction** — something in the territory of:
- "What players really think"
- "Steam game intelligence"
- "Beyond the rating"
- "Inside every Steam game"
- "The intelligence layer for Steam"

**Not**: "Discover Steam Games" — too generic, too consumer-only.
**Not**: Anything with "AI" — describe the value, not the technology.

The headline should communicate:
- This is about **understanding**, not browsing
- The source is **player data** (reviews, playtime, behavior)
- It covers the **whole Steam catalog**
- There's depth here beyond what Steam or any competitor shows

**Subheadline**: One sentence explaining what SteamPulse does.
Direction: "Player intelligence across 100,000+ Steam games. What players love.
What they hate. What they want next."

**Search bar**: Stays. It serves both audiences equally. A developer searches for
competitors. A gamer searches for a game they're considering.

**Proof bar** (below search): Small stats row showing scale at a glance.
- "X games tracked" · "X reviews analyzed" · "X market trends"
- Use real numbers, update dynamically as the catalog grows.
- These numbers should be honest — don't round up aggressively.

### 2. "What You Get" — Intelligence Preview Cards (3-4 cards)

What makes SteamPulse different from everything else, in scannable format.
Each card shows a real data point or mini-visualization, not just text.

**Card 1: "Player Sentiment Intelligence"**
- See what players actually think — structured by playtime, timeline, and behavior
- Mini-viz: a sentiment timeline or playtime-sentiment chart snippet
- Appeal: both audiences

**Card 2: "Competitive Intelligence"**
- See which games share your audience — real overlap from reviewer behavior
- Mini-viz: audience overlap snippet showing game names + overlap %
- Appeal: leans developer, but gamers find "players also played" interesting

**Card 3: "Market Intelligence"**
- Genre trends, pricing sweet spots, release timing, platform coverage
- Mini-viz: a trend line or price positioning scatter
- Appeal: leans developer/publisher

**Card 4: "Deep Review Reports"**
- Thousands of reviews distilled into structured intelligence — design strengths,
  friction points, what players want next
- Mini-viz: a report snippet showing one-liner + 2 strengths + 1 friction
- Appeal: both audiences
- Note: Frame as "available for X games and growing" — honest about coverage

### 3. Game Intelligence Showcase (Tabbed, 3 Games)

Show three well-known games from different genres in a tabbed view. The user
sees one game at a time and can click between tabs to explore different
examples. This demonstrates breadth — SteamPulse isn't just for one genre.

**Games** (hardcoded appids, chosen for SEO value + genre diversity):
- Baldur's Gate 3 (1086940) — RPG / fantasy
- Stardew Valley (413150) — indie / simulation
- Cyberpunk 2077 (1091500) — AAA / open-world

**Tab bar**: Game names as tabs at the top of the card. Active tab gets a teal
underline; inactive tabs are muted. Client-side switching — all data is
pre-fetched server-side, no loading on tab change.

**Each tab shows the full intelligence stack**:
- Review sentiment timeline (exists for every game)
- Audience overlap competitors (exists for every game)
- Report excerpt: one-liner + design strengths + gameplay friction (report-specific)

This section demonstrates: "This is what you get when you look up any game."
Games that fail to load (e.g. not yet analyzed) are silently excluded from the
tab bar — the section degrades from 3 → 2 → 1 → hidden.

**CTA**: "Explore this game →" (per-tab, links to the active game's page)

### 4. Market Trends Preview

Show 1-2 real charts from the analytics dashboard:
- A genre or tag trend (rising/falling)
- A price positioning scatter or release timing pattern

This signals: "This isn't just per-game — it's a market research platform."

Keep it minimal — just enough to show the capability exists. The /explore page
is where the full experience lives.

**CTA**: "Explore market trends →" (links to /explore)

### 5. Game Rows (existing functionality, repositioned)

Keep the current discovery rows:
- "Most Popular" — by review count
- "Top Rated" — by sentiment
- "Hidden Gems" — by hidden gem score (strong brand element, keep prominent)
- "New on Steam" — latest releases
- "Just Analyzed" — newest reports (signals the pipeline is active and growing)

These rows move DOWN from the hero position. They're still valuable for
engagement, SEO, and giving both audiences something to click — but they're
not the site's identity.

### 6. "For Game Developers" Section

A dedicated section that speaks directly to the professional audience.
Not a fork — a section within the same page flow.

**Headline**: "Built for the people who make games" or "Game intelligence for
developers"

**Three value props** (describe what EXISTS today, not future features):
- "Understand your players" — review intelligence, sentiment trends, playtime
  analysis, churn detection
- "Know your competition" — audience overlap shows which games your reviewers
  actually play
- "Read the market" — genre trends, pricing analysis, release timing, platform
  coverage

**CTA**: "Join the Pro waitlist →" (links to /pro)

**Important**: Only describe features that are live. Don't promise the 16
data-intelligence features from the roadmap until they ship. Credibility > hype.

### 7. Browse by Genre / Browse by Tag

Keep the existing genre grid and tag browser. These serve SEO (genre and tag pages
are high-value organic landing pages) and give both audiences a way to explore.

### 8. Footer CTA

Simple closing statement:
- "100,000+ games. Free to explore."
- Search bar repeat, or waitlist signup

---

## Meta Tags & SEO

**Title tag**: `SteamPulse — Steam Game Intelligence`

**Meta description**:
> "Player intelligence across 100,000+ Steam games. Sentiment analysis, competitive
> insights, market trends, and deep review reports — for gamers and game makers."

No "AI" in meta tags. Lead with "player intelligence" — it's descriptive and
differentiating without being buzzwordy.

**OpenGraph title**: Same as title tag.

**OpenGraph description**: Shorter version:
> "What players really think about every Steam game. Sentiment, trends, and
> competitive intelligence."

---

## Tone & Voice

**Current**: Clean, minimal, data-forward. This is correct — keep it.

**Shift**: From "browse and discover" to "understand and decide."

**Words to use**:
- "intelligence" not "data"
- "analysis" not "overview"
- "insights" not "stats"
- "understand" not "browse"
- "decide" not "discover"
- "structured" not "AI-powered"

**Words to never use**:
- "AI" (describe the value, not the technology)
- "revolutionary", "game-changing" (hype)
- "neural", "deep learning", "GPT", "LLM" (implementation details)
- "your next favorite game" (competing with Steam's own language)
- "discover" as the primary verb (commodity positioning)

**Words to use carefully**:
- "reports" — always pair with context about growing coverage
- "free" — don't lead with it (signals low value), mention it naturally

---

## What Changes vs Current Homepage

| Element | Current | New |
|---|---|---|
| **Hero headline** | "Discover Steam Games" | Intelligence-first (see direction above) |
| **Hero subheadline** | (none) | One sentence: what SteamPulse does |
| **Proof bar** | (none) | Games tracked + reviews analyzed + trends |
| **Intelligence cards** | (none) | 3-4 cards with mini-visualizations |
| **Game showcase** | (none) | Full intelligence stack for one game |
| **Market preview** | (none — buried in /explore) | 1-2 chart previews |
| **Discovery rows** | Position 1 (directly after hero) | Position 5 (still present, lower) |
| **For Developers** | (none — navbar link only) | Dedicated homepage section |
| **Genre/tag browse** | Present | Stays, same position |
| **Search bar** | In hero | Stays, same position |
| **Meta description** | "Deep review intelligence for 6,000+..." | Updated with "player intelligence" framing |

**What stays the same**: Search bar, discovery rows (reordered), genre/tag browse,
dark theme, design system, typography, overall aesthetic.

---

## Navigation Label Review

| Current | Suggestion | Reason |
|---|---|---|
| Browse | Keep | Clear, functional |
| Reports | "Reports" or "Game Reports" | Avoid "AI Reports" (no "AI") |
| New Releases | Keep | Clear |
| Trending | Keep or "Market Trends" | "Trending" is fine for both audiences |
| Explore | "Analytics" | Clearer for developers, still accessible to gamers |
| Compare | Keep | Clear |
| For Developers → | Keep | Good explicit audience signal |

---

## Implementation Notes

This is a **content and layout** change to `frontend/app/page.tsx`. No backend
changes. No new API endpoints needed — all data comes from existing endpoints:

- Intelligence cards: static content + mini chart components (Recharts sparklines)
- Game showcase: 3 games × (`GET /api/games/{appid}/report` + `/review-stats` +
  `/audience-overlap`) = 9 parallel calls. Tabbed client-side switching.
- Market preview: `GET /api/analytics/trends/sentiment` + `/trends/release-volume`
- Proof bar: `GET /api/games` for total count + genre count from existing fetch
- Discovery rows: existing code, just reordered in the page

**New components** (all in `frontend/components/home/`):
- `ProofBar` — stats row (games tracked, genres, trend history)
- `IntelligenceCards` — 4-card grid with mini Recharts sparklines
- `GameShowcase` — tabbed display cycling through 3 curated games
- `MiniSentimentChart` — 80px area chart sparkline (no axes)
- `MiniOverlapList` — top 3 audience overlap entries
- `MiniTrendLine` — 80px line sparkline (no axes)
- `MarketTrendsPreview` — 2 embedded trend charts (sentiment + releases)
- `ForDevelopers` — CTA section with 3 value props
- `FooterCTA` — closing search + "Free to explore"

**Existing components reused**:
- `HeroSearch` — stays as-is
- `GameCard` — stays for discovery rows
- `TagBrowser` — stays
- `SentimentTimeline` — used full-size inside GameShowcase tabs

---

## Success Criteria

The new homepage should pass these tests:

1. **A developer landing cold** understands within 5 seconds that this is a
   professional game intelligence tool, not just a game browser.
2. **A gamer landing cold** doesn't feel excluded — the search bar, game rows,
   and report showcase are obviously for them too.
3. **Neither audience has to self-select** — the page flows naturally from
   universal (hero + intelligence preview) → market-facing (trends + analytics)
   → consumer (discovery rows) → professional (for developers CTA).
4. **The unique value is above the fold** — structured player intelligence, not
   game browsing.
5. **A visitor can explain to someone else** what SteamPulse does after seeing
   only the hero + subheadline.
6. **No promise gaps** — every claim on the homepage is backed by a feature that
   works today. The hero doesn't promise reports for every game; it promises
   intelligence (which the structured data delivers universally).
7. **The word "AI" appears nowhere** on the page.
