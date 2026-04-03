# SteamPulse Intelligence Platform — Prompt Execution Roadmap

See full strategic analysis at `/Users/iganza/.claude/plans/crispy-beaming-lovelace.md`.

---

## Core UI Architecture

Every page is a pre-configured toolkit state. The same shell, different lens + filter presets:

```
/genre/action                →  filter(genre=action)  + Market Map lens
/games/440/team-fortress-2   →  filter(appid=440)     + Sentiment Drill lens
/tag/roguelike               →  filter(tag=roguelike) + Explorer lens
/analytics                   →  no filter             + Trends lens
/compare?games=440,892970    →  filter(appids=[...])  + Compare lens
```

URL encodes all state: `?genre=action&lens=compare&games=440,892970&price_max=20`

Free users get the lens pre-selected. Pro users can switch lenses, add filters, export.

```
[Sentiment Drill ✓] [Compare 🔒 Pro] [Explorer 🔒 Pro] [Market Map 🔒 Pro]
```

---

## Tier Boundary

**Free:** Single game experience — LLM report, Sentiment Drill lens, Promise Gap preview, basic charts, search/browse. Every game page is an SEO landing page + acquisition funnel.

**Pro ($29-49/mo):** Cross-game intelligence — Compare lens (conversion trigger), Explorer, Benchmark, Market Map, Trends, full analytics hub controls, revenue estimates, full sentiment drill, Saturation Index.

**Pro+ (post-launch, ~$99/mo):** AI assistant layer — RAG chat, semantic search, saved boards, alerts, API access, team seats.

---

## Conversion Funnel

```
DISCOVERY    → Free game page (SEO, social share)
                "Have you seen what SteamPulse says about your game?"

ENGAGEMENT   → User browses 5-10 game pages, sees locked lens tabs every time:
                Promise Gap blurred after row 2, revenue hidden, Compare locked

TRIGGER      → User clicks Compare on their game vs. a competitor → paywall
                → 14-day Pro trial

PRO USE      → Builds comp sets, checks revenue, uses analytics hub
                Switching cost accumulates

PRO+ UPSELL  → "What's the biggest unmet need in my genre?"
                → sees chat box → upgrades
```

---

## MVP / Go-Live (execute in order)

### 1. Backend Intelligence Foundation
| # | Prompt                                                  | Status | Delivers                                                                          |
|---|---------------------------------------------------------|--------|-----------------------------------------------------------------------------------|
| 1 | `scripts/prompts/game-temporal-intelligence.md`         | Done  | Temporal context (age, velocity, trajectory) in LLM reports + API                 |
| 2 | `scripts/prompts/game-metadata-analysis-enhancement.md` | Done  | Promise vs. Reality (`store_page_alignment`) in every report                      |
| 3 | `scripts/prompts/analytics-dashboard.md`                | Done  | 9 catalog-wide API endpoints (release volume, sentiment dist., genre share, etc.) |

### 2. Per-Game Frontend (Free tier — existing pages)
| # | Prompt                                         | Status | Delivers                                              |
|---|------------------------------------------------|--------|-------------------------------------------------------|
| 4 | `scripts/prompts/analytics-engine-frontend.md` | Done  | 11 chart components on game/genre/tag/developer pages |

### 3. Toolkit Shell — the shared UI foundation ⚡ write this before any remaining prompts
| # | Prompt                             | Status | Delivers                                                                                                                                                                             |
|---|------------------------------------|--------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 5 | `scripts/prompts/toolkit-shell.md` | Done   | Shared layout: filter bar, lens tab switcher, URL state (`?lens=&genre=&appids=`), `usePro()` integration, Pro lock pattern. All subsequent prompts plug a new lens into this shell. |

### 4. Lenses & Pages (plug into shell)
| # | Prompt                                             | Status            | Delivers                                                                                  |
|---|----------------------------------------------------|-------------------|-------------------------------------------------------------------------------------------|
| 6 | `scripts/prompts/store-page-alignment-frontend.md` | **Needs writing** | Promise Gap tab within Sentiment Drill lens (teaser free, full Pro)                       |
| 7 | `scripts/prompts/analytics-dashboard-frontend.md`  | **Needs writing** | Trends lens preset — `/analytics` page, 9 charts, granularity + genre filter              |
| 8 | `scripts/prompts/toolkit-compare.md`               | **Needs writing** | **Compare lens — Pro conversion trigger.** Game picker, side-by-side metrics, radar chart |

### 5. Pro Data & Monetization
| #  | Prompt                                 | Status            | Delivers                                                                              |
|----|----------------------------------------|-------------------|---------------------------------------------------------------------------------------|
| 9  | `scripts/prompts/revenue-estimates.md` | **Needs writing** | Boxleiter ratio, genre-calibrated `estimated_owners` + `estimated_revenue` — Pro only |
| 10 | `scripts/prompts/pro-gating.md`        | **Needs writing** | `usePro()` context, Free + Pro tiers, Stripe, `/pro` pricing page, blur/lock pattern  |

---

## Post-Launch — Build in Public

### Phase 2A — Full Toolkit (Pro)
| #  | Prompt                                       | Delivers                                                                               |
|----|----------------------------------------------|----------------------------------------------------------------------------------------|
| 11 | `scripts/prompts/toolkit-filter-explorer.md` | Explorer lens — sortable games table, all computed metrics as columns, full filter bar |
| 12 | `scripts/prompts/toolkit-benchmark.md`       | Benchmark lens — auto comp-set + percentile ranks vs. comps                            |
| 13 | `scripts/prompts/full-text-search.md`        | tsvector on games + reviews, instant search with autocomplete                          |

### Phase 2B — Market Intelligence (Pro)
| #  | Prompt                                  | Delivers                                                                  |
|----|-----------------------------------------|---------------------------------------------------------------------------|
| 14 | `scripts/prompts/toolkit-market-map.md` | Market Map lens — aggregate distributions by tag/genre/price/developer    |
| 15 | `scripts/prompts/toolkit-trends.md`     | Trends lens (enhanced) — time-series for any metric, configurable windows |
| 16 | `scripts/prompts/saturation-index.md`   | Niche saturation index — release density vs. median reviews per tag combo |

### Phase 2C — AI Assistant Layer (Pro+)
| #  | Prompt                                   | Delivers                                                               |
|----|------------------------------------------|------------------------------------------------------------------------|
| 17 | `scripts/prompts/semantic-search.md`     | pgvector embeddings on topics/quotes, concept-based search             |
| 18 | `scripts/prompts/rag-chat.md`            | Conversational query interface with tool-use over toolkit primitives   |
| 19 | `scripts/prompts/saved-boards-alerts.md` | Saved boards, watchlists, email alerts                                 |
| 20 | `scripts/prompts/api-access.md`          | REST API with API keys for programmatic toolkit access                 |
| 21 | `scripts/prompts/pro-plus-tier.md`       | Pro+ tier launch — gate RAG chat/API/team seats behind new price point |

---

## Key Architectural Decisions

1. **Toolkit shell first** — write `toolkit-shell.md` before any remaining frontend prompts. Everything else is a lens that plugs into it.
2. **URL-encoded state from day one** — `?lens=compare&genre=action&appids=440,892970`. Makes every view shareable; the toolkit can reuse existing pages as presets.
3. **Pro gating is frontend-only** — backend serves all data; `usePro()` context controls blur/lock. Free users generate the full dataset.
4. **Compare lens before Explorer** — Compare triggers Pro conversion (indie dev use case). Explorer serves analysts and comes post-launch.
5. **SEO pages are lens presets** — `/genre/[slug]` = Market Map preset, `/games/[appid]/[slug]` = Sentiment Drill preset. They stay as SSR pages for SEO; the shell hydrates client-side.
6. **No re-analysis needed** — no games analyzed yet; LLM pipeline picks up temporal + metadata enrichment from day one.
7. **Revenue estimates via `index_insights`** — pre-computed on a refresh schedule, not real-time SQL.
