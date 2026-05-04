# RDB launch spec

The concrete specification for Step 1 of the Active Launch Plan in `steam-pulse.org`. RDB-specific numbers and field mappings that downstream implementation prompts consume without further clarification.

The pricing and packaging model lives in `scripts/prompts/monetization-direction.md`. This file does not restate the model; it pins the model to RDB.

## 1. v1 source of truth

The site is the deliverable. The buyable artifact for RDB is the paid-mode rendering of `/genre/roguelike-deckbuilder/` (described in Section 2). The data source is the existing `mv_genre_synthesis` row at `WHERE slug = 'roguelike-deckbuilder'`, augmented by two operator-curated columns (`editorial_intro`, `churn_interpretation`) that may be empty at v1.

There is no PDF in v1. PDF and CSV export are deferred Tier-2 SKUs (gate: ≥ 3 buyers explicitly request offline / sharable export). The `Deferred` table in `steam-pulse.org` carries the gate.

### Field-to-rendering mapping

The synthesis JSON shape (defined in `src/library-layer/library_layer/models/genre_synthesis.py`) maps to existing genre-page components:

| Synthesis field | Component | Free mode | Paid mode |
|---|---|---|---|
| `narrative_summary` | `EditorialIntro` | full | full |
| `editorial_intro` (curated) | `EditorialIntro` (front) | full when non-empty | full when non-empty |
| `friction_points[]` | `FrictionList` | top 5 + upsell CTA | full list |
| `wishlist_items[]` | `WishlistList` | top 3 + upsell CTA | full list |
| `benchmark_games[]` | `BenchmarkGrid` | full (these are showcase anchors) | full |
| `churn_insight` | `ChurnWall` | full callout | full callout |
| `churn_interpretation` (curated) | `ChurnWall` extension | full when non-empty | full when non-empty |
| `dev_priorities[]` | `DevPrioritiesTeaser` | top 3 + upsell CTA | full ranked table |

### Out of scope for v1

These are explicit non-goals for the v1 ship; they become editorial polish items post-launch (launch plan Step 8) or Tier-2 deferrals:

- Hand-written executive summary as a separate page section
- Section reordering on paid mode (synthesis-natural order is the v1 order)
- Cross-references between benchmark deep-dive cards
- Strategic recommendations narrative as its own section
- Inline charts (Recharts components for friction counts, wishlist counts, dev priorities), possible v2 visual polish
- PDF or CSV export, deferred Tier-2

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
- Any post-launch editorial revisions land for paid users live (the matview re-renders on next page load; no offline artifact to regenerate).
- `ReportBuyBlock` is replaced by a small `PaidStatusBlock` that confirms the buyer's access ("You have access through [date]" for one-time, "Subscriber" for active subscriptions) and offers a "Manage subscription" link to a Stripe customer portal session.
- `noindex` meta is set so search engines crawl only the free shape.

### Auth mechanism

Render mode is decided server-side by reading a signed `sp_session` cookie that carries `user_id` (UUID), then querying entitlements by `user_id`. The full schema and lifecycle is in Section 5. Summary:

- Subscribers get paid mode for every `/genre/[slug]/` page.
- One-time buyers get paid mode for the slugs they bought, until `access_until`.
- No cookie or invalid cookie: free mode.

The cookie carries `user_id`, not email, so adding Auth0 (or any other auth method) later is a plug-in, not a migration. See Section 5.

## 3. Per-game preview surface

`frontend/app/games/[appid]/[slug]/` (rendered via `GameReportClient.tsx`) currently shows every section in full for every analyzed game. The spec splits per-game pages into two render modes triggered by appid membership.

A page renders in **full mode** when EITHER of two rules matches:

- **Showcase rule:** the appid appears in `benchmark_appids` of any published `reports` row.
- **Canonical rule:** `games.is_canonical_free = true`. Defined and populated per `scripts/prompts/canonical-free-games.md` (top 200 by `review_count` with quality floor and stickiness).

Otherwise the page renders the abbreviated **preview mode**.

### Full mode (formerly "showcase mode")

Render is identical to today:

- All `design_strengths`
- All `gameplay_friction`
- Full `audience_profile`, `sentiment_trend`, `store_page_alignment` (PromiseGap)
- Full `player_wishlist`, `churn_triggers`, `dev_priorities`, `competitive_context`
- All non-narrative blocks (Verdict, Steam Facts, QuickStats, MarketReach, Sentiment History, Playtime Sentiment, Competitive Benchmark)

For RDB launch, the seed showcase set is the 5 RDB benchmark appids: Slay the Spire, Balatro, Inscryption, Monster Train, Dicey Dungeons. The canonical-free set adds up to 200 more, picked by `review_count` across the full sentiment range (no quality floor) so the public surface demonstrates the engine on positive, mixed, and negatively-received games.

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

## 5. User identity and entitlements

Identity runs on **Better Auth**, an open-source TypeScript framework that lives inside our Next.js app and persists to our own Postgres. Magic link + Google OAuth + sessions + logout are built in via plugins. The user database is ours: zero recurring cost, zero vendor lock-in, no migration ever required because the user table sits next to our entitlement tables.

The implementation prompt is `scripts/prompts/better-auth-setup.md`. This section pins the schema and lifecycle the Better Auth + Stripe wiring satisfies.

### Tables

Better Auth manages four tables (`users`, `sessions`, `accounts`, `verifications`); see the auth prompt for the full migration. Entitlement tables FK to `users.id` (UUID):

```sql
subscriptions (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  stripe_customer_id TEXT NOT NULL,
  stripe_subscription_id TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL,  -- active, canceled, past_due, trialing, unpaid
  current_period_end TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
CREATE INDEX subscriptions_user_idx ON subscriptions (user_id);

report_purchases (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  report_slug TEXT NOT NULL,
  stripe_session_id TEXT UNIQUE NOT NULL,
  purchased_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  access_until TIMESTAMPTZ NOT NULL  -- purchased_at + INTERVAL '30 days'
)
CREATE INDEX report_purchases_user_slug_idx
  ON report_purchases (user_id, report_slug);
```

Real foreign-key constraints. If a user is deleted, their entitlements cascade. If a `users.id` is referenced by a subscription, the user row cannot be silently dropped.

### Purchase flow (gate behind sign-in)

1. Buyer clicks "Subscribe" or "Buy this report" on `/genre/[slug]/`.
2. If not signed in: client redirects to `/sign-in?redirect=/genre/[slug]/`. The sign-in page offers two CTAs: "Continue with Google" and "Send me a sign-in link" (magic link via the existing email Lambda).
3. After auth, the redirect query param returns the buyer to `/genre/[slug]/`; they click again.
4. Backend creates a Stripe Checkout Session with `metadata.user_id` set to the authenticated `users.id`.
5. Stripe Checkout completes (subscription or one-time).
6. Webhook receives `customer.subscription.created` (or `checkout.session.completed` for one-time) with metadata. Inserts the entitlement row keyed on `user_id`.
7. Buyer redirected back to `/genre/[slug]/`. Better Auth session cookie is already live; server-side render reads `auth.api.getSession({ headers })`, queries entitlements, renders paid mode.

Resend is used for magic-link emails (via the existing `ResendEmailSender` and email Lambda) and for transactional confirmations ("subscription confirmed", "report purchase confirmed").

### Render-mode decision (every server-side request to `/genre/[slug]/`)

1. Call `auth.api.getSession({ headers })` to read the current Better Auth session. If unauthenticated, render free mode.
2. Read `session.user.id` (UUID).
3. Subscription check: `SELECT 1 FROM subscriptions WHERE user_id = $1 AND status = 'active' AND current_period_end > now()`.
4. One-time check: `SELECT 1 FROM report_purchases WHERE user_id = $1 AND report_slug = $2 AND access_until > now()`.
5. Either match: paid mode. No match: free mode.

### Logout, account, and recovery

- **Logout:** the auth client exposes `signOut()`. Wired to the avatar dropdown in the page header. Server-side, this invalidates the row in `sessions`, so revocation is immediate (not just stateless-JWT-best-effort).
- **Account UI:** `/account` is a small custom page showing email, connected accounts (Google), and a "Sign out" button. Built with Better Auth's React hooks; ~half day of work. Stripe Customer Portal handles billing.
- **Recovery:** "I lost my session" is the same flow as initial sign-in. Buyer visits `/sign-in`, enters email, receives a magic link. No separate `/login` route needed; sign-in IS recovery.
- **Billing portal:** "Manage subscription" link from `/account` hits a backend endpoint that creates a Stripe Billing Portal session and redirects.

### Why Better Auth

- **Open source.** $0 at any scale; no vendor risk.
- **You own the data.** `users`, `sessions`, `accounts`, `verifications` live in our Postgres alongside `subscriptions` and `report_purchases`. Real FK constraints possible.
- **TypeScript-first.** Plugin types flow through end-to-end (`signIn.magicLink({ email })` is fully typed once the magic-link plugin is enabled).
- **Active stewardship.** The Better Auth team is the current maintainer of Auth.js (NextAuth); new Next.js projects in 2026 are recommended to start with Better Auth directly.
- **Plugin breadth.** Magic link, Google OAuth, passkeys, 2FA, MFA, organisations, all available as opt-in plugins. v1 enables magic link + Google OAuth only.

Sources:
- https://better-auth.com/
- https://better-auth.com/blog/authjs-joins-better-auth
- https://better-auth.com/docs/integrations/next

## What this spec does not decide

- JWT signing key management (rotation, KMS, etc.): infra concern, defined in the launch plan Step 2 (Stripe + Resend backend) implementation.
- Editorial polish content: continuous post-launch (launch plan Step 8).
- Profile page UI: deferred until a buyer asks for it (no gate value at launch; magic-link recovery via `/login` covers the only common need).
- PDF and CSV export: deferred Tier-2 SKUs. Gate: ≥ 3 buyers explicitly request offline / sharable export.
