# RDB launch spec

The concrete specification for Step 1 of the Active Launch Plan in `steam-pulse.org`. RDB-specific numbers and field mappings that downstream implementation prompts (Step 2 PDF formatter, Step 3 Stripe + Resend backend, Step 5 genre buy block, Step 5 per-game preview frontend) consume without further clarification.

The pricing and packaging model lives in `scripts/prompts/monetization-direction.md`. This file does not restate the model; it pins the model to RDB.

## 1. v1 RDB genre report PDF contents

The v1 RDB report is the auto-generated Phase 4 synthesis output formatted as a print-ready PDF. The matview row is `mv_genre_synthesis WHERE slug = 'roguelike-deckbuilder'`. The PDF formatter walks the JSONB `synthesis` field plus the operator-curated columns (`editorial_intro`, `churn_interpretation`) and renders the sections below.

### Field-to-section mapping

The synthesis JSON shape (defined in `src/library-layer/library_layer/models/genre_synthesis.py`):

| Synthesis field | PDF section | Render rule |
|---|---|---|
| `narrative_summary` | "Genre at a glance" (page 2, after TOC) | Full text, single paragraph |
| `editorial_intro` | "From the editor" (page 2, before "Genre at a glance") | Render only if non-empty; v1 may be empty |
| `friction_points[]` | "Cross-game friction" | Full list, no truncation. Each item: title (h3), description, representative_quote (blockquote with appid attribution), mention_count badge |
| `wishlist_items[]` | "Cross-game wishlist" | Full list. Same shape as friction items |
| `benchmark_games[]` | "Benchmark games" | One card per game: name (h3), why_benchmark, link annotation noting the per-game showcase page exists |
| `churn_insight` (singular) | "Where players drop off" (callout box) | typical_dropout_hour as headline number, primary_reason as subtitle, representative_quote as blockquote, source_appid attribution |
| `churn_interpretation` | Inside the churn callout, after the quote | Render only if non-empty |
| `dev_priorities[]` | "Ranked dev priorities" | Full table: rank, action, why_it_matters, frequency, effort. Effort cells colored per `EFFORT_COLOR` from `fill_report.py` |

### PDF wrapper additions (added by the formatter, not from the matview)

- **Cover page:** title "Roguelike Deckbuilder Player Intelligence Report", subtitle "Synthesised from 141 games, computed [date]", byline (author name from `frontend/lib/author.ts`)
- **Table of contents:** auto-generated from the section headings present
- **Methodology section:** input_count (141), median review count, avg positive_pct (87.5%), `computed_at` timestamp, one paragraph explaining the chunk-merge-synthesise pipeline
- **Single-game appendix:** all 141 RDB games sorted by review_count desc, with appid, name, review_count, positive_pct. Sourced via `JOIN games ON games.appid = ANY(...)` keyed on the cohort the matview row was built from

### Charts (all already implemented in `scripts/fill_report.py`)

Reuse these functions directly; do not roll new chart code:

- `chart_friction_counts(synthesis['friction_points'], out)` for the friction section
- `chart_wishlist_counts(synthesis['wishlist_items'], out)` for the wishlist section
- `chart_dev_priorities(synthesis['dev_priorities'], out)` for the dev priorities section
- `chart_top_games_by_reviews(games, out, n=10)` for the appendix
- `chart_releases_per_year(games, out)` and `chart_price_distribution(games, out)` for the methodology section
- All charts are saved as both PDF (vector) and PNG via `_save(fig, out)`
- Call `setup_chart_style()` once at formatter init

### Out of scope for v1

These are explicit non-goals for the v1 ship; they become editorial polish items post-launch:

- Hand-written executive summary
- Section reordering (synthesis-natural order is the v1 order)
- Cross-references between benchmark deep-dive cards
- Strategic recommendations narrative
- Print-quality cover art beyond a typeset title

## 2. Genre page render modes

`/genre/[slug]/` (frontend at `frontend/app/genre/[slug]/page.tsx`) has two render modes, decided server-side per request based on cookie + database lookup. No client flicker.

### Free mode (default; what ships today)

This is the current rendering. It stays exactly as-is for free traffic.

- `EditorialIntro` (display_name, narrative_summary, share buttons)
- `FrictionList` with `synthesis.friction_points.slice(0, 5)`, plus the "X more friction clusters in the report" CTA when `hasReport` is true
- `WishlistList` with `synthesis.wishlist_items.slice(0, 3)`, plus the "X more wishlist items in the report" CTA when `hasReport` is true
- `BenchmarkGrid` with all `synthesis.benchmark_games` (these are showcase anchors and stay fully visible)
- `ChurnWall` (churn_insight + churn_interpretation when curated)
- `DevPrioritiesTeaser` with `synthesis.dev_priorities.slice(0, 3)`, plus the "Full ranked priorities table in the report" CTA when `hasReport` is true
- `MethodologyFooter`
- `ReportBuyBlock` (subscribe + one-time CTAs; see Section 4)
- SEO-indexed (no `noindex` meta)

### Paid mode (active subscriber, OR one-time buyer of THIS slug within their access window)

- All synthesis fields render in full directly on-page:
  - `FrictionList` shows every `synthesis.friction_points` entry, no truncation
  - `WishlistList` shows every `synthesis.wishlist_items` entry, no truncation
  - `DevPrioritiesTeaser` shows the full ranked table
  - `BenchmarkGrid` shows every benchmark card with cross-links to the showcase per-game pages
  - `ChurnWall` shows the full churn detail
- Any post-launch editorial sections (executive summary, framing paragraphs, additional charts as the operator polishes) render here too. The same matview revisions land for paid users live, with no PDF download required.
- `ReportBuyBlock` is replaced by a `ReportDownloadBlock`: "Download PDF" + "Download CSV" buttons that hit `GET /api/reports/{slug}/download?asset=pdf|csv`, which re-validates the cookie and returns a fresh signed S3 URL.
- `noindex` meta is set so search engines crawl only the free shape.

### Auth mechanism

Render mode is decided server-side by reading a signed `sp_session` cookie that carries `user_id` (UUID), then querying entitlements by `user_id`. The full schema and lifecycle is in Section 5. Summary:

- Subscribers get paid mode for every `/genre/[slug]/` page.
- One-time buyers get paid mode for the slugs they bought, until `access_until`.
- No cookie or invalid cookie: free mode.

The cookie carries `user_id`, not email, so adding Auth0 (or any other auth method) later is a plug-in, not a migration. See Section 5.

## 3. Per-game preview surface

`frontend/app/games/[appid]/[slug]/` (rendered via `GameReportClient.tsx`) currently shows every section in full for every analyzed game. The spec splits per-game pages into two render modes triggered by appid membership.

### Showcase mode

An appid is in showcase mode if and only if it appears in `benchmark_appids` of any published `reports` row. Render is identical to today:

- All `design_strengths`
- All `gameplay_friction`
- Full `audience_profile`, `sentiment_trend`, `store_page_alignment` (PromiseGap)
- Full `player_wishlist`, `churn_triggers`, `dev_priorities`, `competitive_context`
- All non-narrative blocks (Verdict, Steam Facts, QuickStats, MarketReach, Sentiment History, Playtime Sentiment, Competitive Benchmark)

For RDB launch, the seed showcase set is the 5 RDB benchmark appids: Slay the Spire, Balatro, Inscryption, Monster Train, Dicey Dungeons.

### Preview mode (default for every other analyzed game)

- Top 3 of `report.design_strengths` (each rendered as the strength text plus one short representative quote pulled from the matched chunk-level signal)
- Top 3 of `report.gameplay_friction` (same shape)
- Basic metadata always: `price_usd`, `release_date`, top 3 `tags`, `review_count`, `review_score_desc`
- All non-narrative blocks stay visible (Verdict, Steam Facts, QuickStats, MarketReach, etc.) so the page is substantive enough for SEO
- A `GenreReportUpsell` block at the bottom: "See [Game] in the context of the [Genre] report. Subscribe $19/mo, or buy this report only $79." Linking to `/genre/[slug]/` of whichever published genre report the appid belongs to.
- If no published genre report covers the appid, the upsell block becomes a `RequestGenreReport` form (single email input, captures into a `genre_request_signals` table for future-cohort scoping).
- Hidden in preview mode: `audience_profile`, `sentiment_trend`, `store_page_alignment`, `player_wishlist`, `churn_triggers`, `dev_priorities`, `competitive_context`

### Genre upsell resolution

The "which report's `/genre/[slug]/` to link to" decision uses this resolver, server-side:

- Look up the appid's tag set via `game_tags`
- Find any published `reports` row whose `benchmark_appids` includes this appid OR whose cohort tag matches the appid's primary tag
- If multiple match, pick the one with the most recent `published_at`
- If none match, fall through to the `RequestGenreReport` form

## 4. Pricing decision and Stripe Product naming

Pinned numbers and Stripe-side configuration:

### Stripe Products and Prices

- **Product:** "SteamPulse Subscription"
  - Monthly Price: $19.00 USD, recurring monthly. Stripe metadata: `tier=subscription`, `period=monthly`
  - Annual Price: $190.00 USD, recurring yearly (saves ~17% versus monthly). Stripe metadata: `tier=subscription`, `period=annual`
- **Product:** "SteamPulse Genre Report: Roguelike Deckbuilder"
  - One Price: $79.00 USD, one-time. Stripe metadata: `tier=one_time`, `report_slug=roguelike-deckbuilder`
- Each future genre report ships as a new Stripe Product with the matching `report_slug` metadata; the subscription Product stays singular and unlocks them all.

### Iteration criterion (4 weeks post-launch)

- One-time conversion (sales / unique `/genre/roguelike-deckbuilder/` visitors) > 4%: raise the one-time price to $99.
- One-time conversion < 1%: drop to $59, or remove the SKU and rely on subscription only.
- Subscription has ≥ 5 active subscribers and monthly churn < 10%: hold pricing.
- Subscription falls short of either threshold: revisit. Annual rate moves with monthly (always ~17% off the monthly-times-12 rate).

## 5. User identity and entitlements schema

Forward-compatible with adding Auth0 (or any OIDC provider) later without migration. v1 ships with magic-link-only auth; Auth0 plugs in as an additional auth method against the same `users` table.

### Tables

```sql
users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  stripe_customer_id TEXT UNIQUE,
  -- Future: populated when Auth0 lands. Multiple auth methods resolve to the same user.
  auth0_sub TEXT UNIQUE,
  display_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

subscriptions (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  stripe_subscription_id TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL,  -- active, canceled, past_due, trialing, unpaid
  current_period_end TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

report_purchases (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  report_slug TEXT NOT NULL,
  stripe_session_id TEXT UNIQUE NOT NULL,
  purchased_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  access_until TIMESTAMPTZ NOT NULL  -- purchased_at + INTERVAL '30 days'
)

magic_link_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  token_hash TEXT UNIQUE NOT NULL,  -- sha256 of the token shipped in the email
  expires_at TIMESTAMPTZ NOT NULL,  -- typically created_at + INTERVAL '7 days'
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

All entitlement reads in the genre page render-mode decision use `user_id`, never email. Email lives on `users` for delivery and recovery only.

### Lifecycle: subscription purchase

1. Stripe Checkout completes; webhook receives `customer.subscription.created` with `customer_email`.
2. Upsert `users` by email (create if missing); set `users.stripe_customer_id` on the row.
3. Insert `subscriptions` row keyed on `user_id`.
4. Generate magic-link token (`base64url(random 32 bytes)`), insert `magic_link_sessions` row with `sha256(token)`, `expires_at = now() + INTERVAL '7 days'`.
5. Resend sends `https://steampulse.io/unlock/{token}` to the user's email.

### Lifecycle: one-time purchase

Same shape, but the webhook is `checkout.session.completed` with `metadata.tier = 'one_time'` and `metadata.report_slug`. Insert `report_purchases` row with `access_until = purchased_at + INTERVAL '30 days'`. Magic-link email also sent.

### Lifecycle: magic-link redeem

1. User clicks `/unlock/{token}`.
2. Server computes `sha256(token)` and queries `magic_link_sessions WHERE token_hash = $1 AND used_at IS NULL AND expires_at > now()`.
3. Marks `used_at = now()` (single-use tokens; reuse fails).
4. Issues an `sp_session` cookie: signed JWT, 90-day expiry, httpOnly, secure, sameSite=lax, payload `{ user_id, iat }`.
5. Redirects to `/` for subscription unlocks, or `/genre/{slug}/` for one-time unlocks (slug pulled from the purchase metadata).

### Lifecycle: render-mode decision (every server-side request to `/genre/[slug]/`)

1. Read `sp_session` cookie. If absent or signature invalid, render free mode.
2. Decode `user_id`.
3. Subscription check: `SELECT 1 FROM subscriptions WHERE user_id = $1 AND status = 'active' AND current_period_end > now()`.
4. One-time check: `SELECT 1 FROM report_purchases WHERE user_id = $1 AND report_slug = $2 AND access_until > now()`.
5. Either match: paid mode. No match: free mode.

### `/login` page

Simple form, single email input. On submit:

1. Look up `users` by email. If not found, render a generic "If that email matches an account, we sent a link" message (no enumeration).
2. If found, create a fresh `magic_link_sessions` row and send the link via Resend.

This is the recovery path for buyers who lose their cookie or want to log in from a new device. No passwords, no signup form (signup is implicit at first purchase).

### Auth0 plug-in path (future, zero migration)

When Auth0 (or another OIDC provider) is added later:

1. Add an Auth0 callback endpoint that exchanges the auth code and resolves the Auth0 sub claim.
2. Find user by `auth0_sub` first. If not found, fall through to email match. If still not found, create a new `users` row with the Auth0 sub and email both populated.
3. On match, populate `users.auth0_sub` if not already set.
4. Issue the same `sp_session` cookie. The cookie shape and the render-mode decision logic do not change.
5. Magic-link auth stays as a fallback for users who prefer not to use Auth0.

`subscriptions`, `report_purchases`, and the genre-page render flow stay identical. No backfill, no email-to-user-id rewrite, no schema migration.

## What this spec does not decide

- The exact PDF typography and layout: defined when writing the formatter (Step 2). The spec names sections and field mapping; visual choices land in the formatter prompt.
- JWT signing key management (rotation, KMS, etc.): infra concern, defined in launch-plan Step 3 implementation.
- Editorial polish content: continuous post-launch (Step 8 in the launch plan).
- Profile page UI: deferred until a buyer asks for it (no gate value at launch; magic-link recovery via `/login` covers the only common need).
