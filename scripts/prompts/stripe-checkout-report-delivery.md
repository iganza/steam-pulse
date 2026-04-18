# Stripe Checkout + secure report delivery

## Context

Replaces the prior Cleeng subscription integration (`cleeng-integration.md`)
and the `/pro` page as the payment/delivery path. Aligned with the
reports-led business model (see `steam-pulse.org` → Active Launch
Plan, and memory `project_business_model_2026.md`).

Scope: **one-off purchases of genre market reports** delivered as
PDF + optional CSV dataset via signed-S3 URL and magic-link reader
access. Three self-serve tiers (indie $49, standard $99, studio $299)
plus a contact-form publisher tier ($1,499 manual invoice).

This prompt covers the end-to-end path from landing page → Stripe
Checkout → webhook → entitlement → email → re-download. It does NOT
cover the Phase-3 Pro subscription with NL chat — that lives in a
future `pro-subscription-nl-chat.md` once Phase 2 gates pass.

## What to do

### 1. Migration: `reports` and `report_purchases` tables

```sql
-- depends: <prev>

-- Catalog of products available for sale.
CREATE TABLE IF NOT EXISTS reports (
    slug TEXT PRIMARY KEY,                      -- "roguelike-deckbuilder-2026-q2"
    genre_slug TEXT NOT NULL,                   -- "roguelike-deckbuilder"
    edition TEXT NOT NULL,                      -- "2026-Q2"
    display_name TEXT NOT NULL,                 -- "Roguelike Deckbuilder Market Report — Q2 2026"
    tier TEXT NOT NULL,                         -- "indie" | "standard" | "studio" | "publisher"
    price_cents INTEGER NOT NULL,
    stripe_price_id TEXT NOT NULL,              -- Stripe Price object (pre-created in dashboard)
    pdf_s3_key TEXT NOT NULL,                   -- "reports/rdb-2026-q2/indie.pdf"
    csv_s3_key TEXT NOT NULL DEFAULT '',        -- "" if tier doesn't include CSV
    published_at TIMESTAMPTZ NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT reports_tier_valid CHECK (tier IN ('indie','standard','studio','publisher'))
);
CREATE INDEX IF NOT EXISTS reports_genre_edition_idx ON reports(genre_slug, edition);

-- Each successful purchase is one row. Buyer keyed by email (no
-- user accounts — magic-link access via email).
CREATE TABLE IF NOT EXISTS report_purchases (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL,
    report_slug TEXT NOT NULL REFERENCES reports(slug),
    stripe_checkout_session_id TEXT NOT NULL UNIQUE,
    stripe_payment_intent_id TEXT NOT NULL,
    amount_paid_cents INTEGER NOT NULL,
    tier TEXT NOT NULL,
    purchased_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_downloaded_at TIMESTAMPTZ,
    download_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS report_purchases_email_idx ON report_purchases(email);
CREATE INDEX IF NOT EXISTS report_purchases_report_slug_idx ON report_purchases(report_slug);

-- Lead magnet email capture (executive-summary PDF download).
-- Separate from report_purchases because leads haven't paid.
CREATE TABLE IF NOT EXISTS leads (
    email TEXT PRIMARY KEY,
    source TEXT NOT NULL,                       -- "exec-summary-rdb" | "genre-insights-page" | etc.
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    consented_to_marketing BOOLEAN NOT NULL DEFAULT true
);

-- Magic-link tokens for report re-download. Short-lived.
CREATE TABLE IF NOT EXISTS magic_link_tokens (
    token TEXT PRIMARY KEY,                     -- random 32-byte hex
    email TEXT NOT NULL,
    purpose TEXT NOT NULL,                      -- "report_download" | "customer_portal"
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS magic_link_tokens_email_idx ON magic_link_tokens(email);
CREATE INDEX IF NOT EXISTS magic_link_tokens_expires_at_idx ON magic_link_tokens(expires_at);
```

Mirror all four tables in `schema.py`.

### 2. Pydantic models

In `library_layer/models/reports.py`:

```python
from pydantic import BaseModel
from datetime import datetime
from typing import Literal

Tier = Literal["indie", "standard", "studio", "publisher"]

class ReportRow(BaseModel):
    slug: str
    genre_slug: str
    edition: str
    display_name: str
    tier: Tier
    price_cents: int
    stripe_price_id: str
    pdf_s3_key: str
    csv_s3_key: str
    published_at: datetime
    is_active: bool

class ReportPurchaseRow(BaseModel):
    id: int
    email: str
    report_slug: str
    stripe_checkout_session_id: str
    stripe_payment_intent_id: str
    amount_paid_cents: int
    tier: Tier
    purchased_at: datetime
    last_downloaded_at: datetime | None
    download_count: int

class LeadRow(BaseModel):
    email: str
    source: str
    captured_at: datetime
    consented_to_marketing: bool

class MagicLinkToken(BaseModel):
    token: str
    email: str
    purpose: Literal["report_download", "customer_portal"]
    expires_at: datetime
    used_at: datetime | None
```

All per CLAUDE.md — pydantic `BaseModel`, avoid `| None` except where
null is a legitimate state (download not yet happened, token not yet
used).

### 3. Repositories

- `ReportRepository` in `library_layer/repositories/report_repo.py`:
  - `get_by_slug(slug) -> ReportRow | None`
  - `list_active_by_genre(genre_slug) -> list[ReportRow]`
  - `upsert(row: ReportRow) -> None` (ops script use)

- `ReportPurchaseRepository` in
  `library_layer/repositories/report_purchase_repo.py`:
  - `insert(row) -> int` — returns id
  - `get_by_session_id(stripe_checkout_session_id) -> ReportPurchaseRow | None`
  - `list_by_email(email) -> list[ReportPurchaseRow]`
  - `mark_downloaded(id)` — bump `last_downloaded_at` + `download_count`

- `LeadRepository`:
  - `upsert(email, source, consented)` — ON CONFLICT do update
    (update `source` only if new and `captured_at` to earliest)

- `MagicLinkRepository`:
  - `create(email, purpose, ttl_minutes=30) -> MagicLinkToken`
  - `consume(token) -> MagicLinkToken | None` — returns the row IFF
    unused and unexpired; marks `used_at = now()` atomically.
  - `prune_expired()` — called daily by EventBridge.

Extend `BaseRepository`. No business logic. SQL only.

### 4. Service — `ReportPurchaseService`

In `library_layer/services/report_purchase_service.py`. Coordinates
the checkout → entitlement → delivery flow. Constructor takes:
`report_repo`, `purchase_repo`, `lead_repo`, `magic_link_repo`,
`stripe_client`, `s3_client`, `resend_client`, `config`.

```python
def create_checkout_session(
    self, *, email: str, report_slug: str, tier: Tier, success_url: str, cancel_url: str
) -> str:
    """Returns the Stripe Checkout session URL. Records email in leads
    table (pre-purchase lead). Stripe Customer is created/reused
    keyed on email."""

def handle_checkout_session_completed(self, *, event: stripe.Event) -> None:
    """Webhook handler. Idempotent on stripe_checkout_session_id.
    1. Verify event signature with webhook secret.
    2. Extract email, report_slug, amount_paid from metadata.
    3. Insert report_purchase row. Skip silently on duplicate session_id.
    4. Send receipt email via Resend with:
       - a magic-link to the download page (30 min TTL)
       - tax receipt text
       - "what you'll receive" expectations block
    5. Return 200 to Stripe."""

def generate_download_urls(
    self, *, purchase: ReportPurchaseRow
) -> dict[str, str]:
    """Returns {'pdf': signed_url, 'csv': signed_url | ''}. S3 signed
    URL, 15-min TTL. Caller is responsible for bumping download_count."""

def request_magic_link(self, *, email: str, purpose: str) -> None:
    """Creates a magic-link token, emails it via Resend. Always
    returns 200 even if email has no purchases (no account enumeration)."""
```

### 5. Lambda handlers

Two new handler modules:

**`lambda_functions/stripe_webhook/handler.py`** — receives Stripe
webhook events. POST endpoint at `/api/stripe/webhook`. Signature
verification via `STRIPE_WEBHOOK_SECRET` (SSM param). Handles
`checkout.session.completed`. Ignores all other event types with a
logged debug line. Returns 200 within 10s.

**`lambda_functions/api/handler.py`** — extend existing API Lambda:

```python
@app.post("/api/checkout/start")
def start_checkout(body: CheckoutStartRequest) -> CheckoutStartResponse:
    """body: {email, report_slug, tier, success_url, cancel_url}
    Returns {url}. Rate-limited by email + IP (no DDoS on session creation)."""

@app.post("/api/leads/exec-summary")
def capture_exec_summary_lead(body: LeadRequest) -> EmptyResponse:
    """body: {email, consent}
    Records in leads. Emails the exec-summary PDF signed URL via Resend.
    Rate-limited by IP."""

@app.post("/api/reports/magic-link")
def request_report_magic_link(body: MagicLinkRequest) -> EmptyResponse:
    """body: {email}
    Always returns 200. Issues magic-link IFF email has purchases."""

@app.get("/api/reports/download")
def download_report(token: str, report_slug: str) -> RedirectResponse:
    """Consumes magic-link token. Validates token + purchase ownership.
    Bumps download_count. 302 to signed S3 URL. Token is
    one-use; returns 410 Gone after first consumption."""

@app.post("/api/publisher/inquiry")
def publisher_inquiry(body: PublisherInquiryRequest) -> EmptyResponse:
    """body: {email, studio_name, genre, use_case, notes}
    Records in a simple `publisher_inquiries` table (optional to add);
    sends notification email to operator via Resend. Manual followup
    and invoicing — no self-serve checkout for $1,499 tier."""
```

Keep these thin — service layer does the real work.

### 6. Frontend — Next.js pages

New pages under `frontend/src/app/reports/`:

- `/reports` — catalog page. Lists active reports grouped by genre.
  Each card: display_name, 3-sentence summary, tier pricing, "buy" CTA.
  Free executive-summary download CTA separate (email capture only).
- `/reports/[slug]` — individual report landing page. Full table of
  contents, 3-page sample PDF download, tier comparison matrix,
  methodology + data caveats. Buy buttons post to `/api/checkout/start`
  and redirect to returned Stripe URL.
- `/reports/success` — post-checkout thank-you. Reads `session_id`
  query param, shows "check your email for the download link."
- `/reports/access` — magic-link entry. Takes `?token=...`, redirects
  to `/api/reports/download` on page load, shows spinner + fallback
  email-entry form.
- `/publisher` — publisher tier inquiry form (no self-serve checkout).

The genre-insights pages (`/genre/[slug]/insights`) gain a "Buy the
full report" CTA in every section after a 3-sentence preview.

### 7. CDK wiring — `infra/stacks/`

- New SSM params:
  - `/steampulse/{env}/stripe/publishable-key`
  - `/steampulse/{env}/stripe/secret-key`
  - `/steampulse/{env}/stripe/webhook-secret`
  - `/steampulse/{env}/resend/api-key`
  - `/steampulse/{env}/s3/reports-bucket`
- New S3 bucket `steampulse-reports-{env}` with versioning on, public
  access blocked, CloudFront OAC for signed-URL delivery (OR direct
  SDK-signed URLs — direct is simpler for Phase 1).
- New Lambda `StripeWebhookFunction` with API Gateway binding at
  `/api/stripe/webhook`. 30s timeout. Minimal memory (512MB).
- Extend existing API Lambda IAM to read the SSM params above and
  read from the reports bucket (signed URL generation needs `s3:GetObject`).
- EventBridge daily rule calling a small `MagicLinkPruneLambda` to
  delete expired tokens.
- No CloudFormation output needed beyond the SSM params (frontend
  reads Stripe publishable key at build time from SSM).

### 8. Stripe dashboard setup (operator, one-time)

Operator does this manually in the Stripe dashboard — not in code:

- Enable **Stripe Tax** (required; no custom tax logic in our code).
- Create **Products** for each report (one Product per report
  edition), and **Prices** per tier:
  - `rdb-2026-q2 / indie` — $49 one-time
  - `rdb-2026-q2 / standard` — $99 one-time
  - `rdb-2026-q2 / studio` — $299 one-time
- Record each `price_id` in the `reports` table via an ops script
  `scripts/ops/seed_report_catalog.py`.
- Configure Checkout branding (logo, colors).
- Configure **webhook endpoint** pointing at
  `https://steampulse.io/api/stripe/webhook`, listening for
  `checkout.session.completed` only. Capture the signing secret
  into the SSM param above.
- Enable **Customer Portal** (needed for Phase 3 Pro; harmless to
  enable now for refund handling).

### 9. Receipt + download email (Resend)

Template lives in `library_layer/email_templates/report_receipt.py`
as a module constant (Jinja2 or plain f-string; mirror existing email
patterns). Fields: buyer name (optional), report display_name, tier,
amount paid, tax amount, magic-link URL with 30-min TTL, what-to-expect
block, support email.

### 10. Abandonment + re-engagement (Phase 1.5, not launch)

After Phase 1 ships and some sales come through, add:
- Stripe Checkout `abandoned_checkout` webhook → queued re-engagement
  email at T+1h, T+24h (per Stripe's best-practice cadence).
- Lead-drip sequence: exec-summary download → T+3d educational email
  → T+7d "here's the full report" pitch.

Both use Resend + a small `EngagementLambda` scheduled by EventBridge.
Defer until Phase 1 proves sales work.

## Verification

1. **Migration applies**: `bash scripts/dev/migrate.sh`; `\d reports`,
   `\d report_purchases`, `\d leads`, `\d magic_link_tokens` all show
   expected schema.
2. **Catalog seed**: `python scripts/ops/seed_report_catalog.py` upserts
   the RDB report rows tied to real Stripe Price IDs.
3. **Stripe webhook signature verification**: integration test posts a
   tampered payload → handler returns 400.
4. **Happy path**: seed a Stripe test-mode Price, call
   `/api/checkout/start`, complete checkout in Stripe test mode,
   confirm webhook fires, row lands in `report_purchases`, receipt
   email sent to Resend (mock in test, real in staging), magic-link
   redeems to signed S3 URL once and errors on second use.
5. **Idempotency**: replay the same `checkout.session.completed`
   event → second call is a no-op (UNIQUE on
   `stripe_checkout_session_id`). No duplicate receipt email.
6. **Magic-link expiry**: create a token with TTL -1 min; consume
   returns 410.
7. **No-account enumeration**: `/api/reports/magic-link` with a
   never-seen email returns 200 with no Resend call.
8. **Rate limiting**: hitting `/api/checkout/start` 20 times in 60s
   from one IP returns 429 after the threshold.
9. **Publisher inquiry**: posting to `/api/publisher/inquiry` stores
   row and sends operator notification.
10. `poetry run pytest -v && poetry run ruff check .`

## Out of scope (separate prompts later)

- **Refund handling UI.** Stripe Customer Portal + manual refund for
  V1; automated refund workflow later if volume justifies.
- **Phase 3 Pro subscription** (`pro-subscription-nl-chat.md` to be
  written). Different code path (Stripe Subscription + Customer
  Portal + magic-link persistent session rather than one-time token).
- **Upgrade between tiers** (indie → studio for the same report).
  Phase 2 feature; Stripe supports `mode: "payment"` + manual
  credit for V1.
- **CSV-only purchase tier** ($29 data-only). Add once signal shows
  dataset-only buyers exist.
- **Team / multi-seat licensing**. Publisher-tier feature; handled
  manually for V1.
- **Affiliate / referral tracking**. Not yet.
- **Tax receipts in multiple languages / jurisdictions**. Stripe Tax
  handles remittance; localized invoicing is post-Phase-3.

## Rollout

- One migration. One new Lambda (`StripeWebhookFunction`). Extensions
  to the existing API Lambda. One new S3 bucket. No Cleeng, no auth0.
- No deploy from Claude — user runs `bash scripts/deploy.sh` and the
  Stripe dashboard setup themselves.
- After deploy, seed the catalog, fire a Stripe test-mode purchase end
  to end, switch webhook to live mode, publish `/reports` page.
