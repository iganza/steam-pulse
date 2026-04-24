# Stripe Checkout + secure report delivery

## Context

Tier 1 payment + delivery engine for the self-serve genre PDF report
catalog. Aligned with `steam-pulse.org` → Active Launch Plan and
memory `project_business_model_2026.md`.

Scope: **one-off purchases of genre market reports** delivered as
PDF + CSV dataset via signed-S3 URL and magic-link reader access.

**Single SKU at $49** — one Stripe Price per report, one Checkout
button. No tier selector, no persona naming, no contact form, no
manual invoicing, no email scoping — the asynchronous-transactions
criterion requires it.

Higher-priced SKUs (Genre Q&A $79, All-Access $149, White-label
$499) are Tier-2 gated and explicitly out of scope for this prompt.
The DB schema below keeps a `tier` column (defaulting to `'report'`,
no CHECK constraint) so those future SKUs can land without a schema
migration once their gates fire.

This prompt covers the end-to-end path from the genre synthesis page
→ Stripe Checkout → webhook → entitlement → email → re-download.

**Pre-order mode.** A `reports` row with `published_at > now()` is a
pre-order. Stripe Checkout still runs immediately; the purchase row
is written; the receipt email says *"thanks, shipping [date]"* and
does **not** include a signed S3 URL. When `published_at` reaches
`now()` (the operator flips the date once the PDF is uploaded), a
delivery sweep sends the signed URL to every un-delivered purchase.
A `reports` row with `published_at <= now()` delivers inline on
checkout, same email template minus the shipping-date phrasing.

No separate pre-order SKU, no separate Stripe product, no waitlist
abstraction. The pre-order / live distinction is derived from the
`published_at` column, nothing else.

Any future subscription / NL chat / audit-SKU work is Tier-2-gated
and does not belong here (see `monetization-strategy.md`).

## What to do

### 1. Migration: `reports` and `report_purchases` tables

```sql
-- depends: <prev>

-- Catalog of products available for sale.
-- tier defaults to 'report' (the $49 base SKU). Future Tier-2-gated
-- SKUs (q&a, all-access, white-label) land in this column without a
-- migration once their demand gates fire.
CREATE TABLE IF NOT EXISTS reports (
    slug TEXT PRIMARY KEY,                      -- "roguelike-deckbuilder-2026-q2"
    genre_slug TEXT NOT NULL,                   -- "roguelike-deckbuilder"
    edition TEXT NOT NULL,                      -- "2026-Q2"
    display_name TEXT NOT NULL,                 -- "Roguelike Deckbuilder Market Report — Q2 2026"
    tier TEXT NOT NULL DEFAULT 'report',        -- "report" at launch; future gated SKUs land here
    price_cents INTEGER NOT NULL,
    stripe_price_id TEXT NOT NULL,              -- Stripe Price object (pre-created in dashboard)
    pdf_s3_key TEXT NOT NULL,                   -- "reports/rdb-2026-q2/report.pdf"
    csv_s3_key TEXT NOT NULL,                   -- "reports/rdb-2026-q2/report.csv" — CSV is always bundled
    published_at TIMESTAMPTZ NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true
);
CREATE INDEX IF NOT EXISTS reports_genre_edition_idx ON reports(genre_slug, edition);

-- Each successful purchase is one row. Buyer keyed by email (no
-- user accounts — magic-link access via email).
-- delivered_at = NULL means the signed-URL email has not been sent
-- yet (pre-order: waiting for reports.published_at to land).
CREATE TABLE IF NOT EXISTS report_purchases (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL,
    report_slug TEXT NOT NULL REFERENCES reports(slug),
    stripe_checkout_session_id TEXT NOT NULL UNIQUE,
    stripe_payment_intent_id TEXT NOT NULL,
    amount_paid_cents INTEGER NOT NULL,
    tier TEXT NOT NULL DEFAULT 'report',        -- denormalized from reports.tier at purchase time
    purchased_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at TIMESTAMPTZ,
    last_downloaded_at TIMESTAMPTZ,
    download_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS report_purchases_email_idx ON report_purchases(email);
CREATE INDEX IF NOT EXISTS report_purchases_report_slug_idx ON report_purchases(report_slug);
CREATE INDEX IF NOT EXISTS report_purchases_undelivered_idx
    ON report_purchases(report_slug) WHERE delivered_at IS NULL;

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

# At launch only "report" exists. Future Tier-2-gated SKUs add to
# this union without a schema migration (the DB column has no CHECK).
Tier = Literal["report"]

class ReportRow(BaseModel):
    slug: str
    genre_slug: str
    edition: str
    display_name: str
    tier: Tier = "report"
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
    tier: Tier = "report"
    purchased_at: datetime
    delivered_at: datetime | None   # None until the signed-URL email is sent
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
  - `list_by_email(email) -> list[ReportPurchaseRow]` — only rows where `delivered_at IS NOT NULL` (undelivered pre-orders are not claimable yet)
  - `list_undelivered_for_live_reports() -> list[ReportPurchaseRow]` — JOIN against `reports` WHERE `reports.published_at <= now() AND report_purchases.delivered_at IS NULL`. Used by the delivery sweep.
  - `mark_delivered(id)` — sets `delivered_at = now()`
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
    self, *, email: str, report_slug: str, success_url: str, cancel_url: str
) -> str:
    """Returns the Stripe Checkout session URL. Records email in leads
    table (pre-purchase lead). Stripe Customer is created/reused
    keyed on email. Price is resolved from reports.stripe_price_id —
    the caller does not pass price or tier."""

def handle_checkout_session_completed(self, *, event: stripe.Event) -> None:
    """Webhook handler. Idempotent on stripe_checkout_session_id.
    1. Verify event signature with webhook secret.
    2. Extract email, report_slug, amount_paid from metadata.
    3. Insert report_purchase row with delivered_at = NULL. Skip
       silently on duplicate session_id.
    4. Look up the reports row. Branch on published_at:
       - If published_at <= now(): report is LIVE.
         Call deliver_now(purchase) inline — sends signed-URL email
         via Resend, sets delivered_at = now().
       - If published_at > now(): report is a PRE-ORDER.
         Send shipping-notice email via Resend with published_at
         (no signed URL, no magic-link — nothing to download yet).
         Leave delivered_at = NULL.
    5. Return 200 to Stripe."""

def deliver_now(self, *, purchase: ReportPurchaseRow) -> None:
    """Used by both the live-checkout path and the delivery sweep.
    1. Create magic-link token (30 min TTL).
    2. Send receipt + download email via Resend, with:
       - magic-link to /reports/access?token=...
       - tax receipt text
       - what-you-got list (PDF + CSV — always the same at launch)
    3. Set delivered_at = now() on the purchase row."""

def sweep_pre_order_deliveries(self) -> int:
    """Called by the delivery-sweep EventBridge rule (daily).
    Also callable on-demand from the admin CLI once published_at is
    flipped on a report.

    1. purchase_repo.list_undelivered_for_live_reports() → rows where
       the report is now live but the buyer hasn't received their link.
    2. For each row: deliver_now(purchase).
    3. Return the count of deliveries fired.

    Idempotent: deliver_now sets delivered_at, so a re-run emails no
    one twice."""

def generate_download_urls(
    self, *, purchase: ReportPurchaseRow
) -> dict[str, str]:
    """Returns {'pdf': signed_url, 'csv': signed_url}. S3 signed URL,
    15-min TTL. Caller is responsible for bumping download_count.
    Raises if purchase.delivered_at IS NULL (pre-order not yet
    fulfilled)."""

def request_magic_link(self, *, email: str, purpose: str) -> None:
    """Creates a magic-link token for any delivered purchase this email
    owns, emails it via Resend. Always returns 200 even if email has no
    purchases OR only un-delivered pre-orders (no account enumeration,
    no "your pre-order ships on…" leak to a non-buyer)."""
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
    """body: {email, report_slug, success_url, cancel_url}
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
```

There is **no** inquiry endpoint, lead form, or contact button. The
single $49 SKU flows through `/api/checkout/start`. Do not add a
manual-invoicing code path.

Keep these thin — service layer does the real work.

### 6. Frontend — Next.js pages

The commerce surface is the **genre synthesis page** (`/genre/[slug]/`,
owned by `genre-insights-page.md`). That page renders a pre-order /
buy block when a `reports` row exists for the genre. A single
"Buy — $49" (or "Pre-order — $49") button kicks off Stripe Checkout.

Supporting pages under `frontend/app/`:

- `/reports` — catalog page. Lists every active `reports` row grouped
  by genre. Each card: display_name, narrative summary one-liner,
  price ("$49"), `published_at` status ("ships [date]" if pre-order,
  "available now" otherwise), link to the synthesis page (not directly
  to Stripe — the synthesis page is the funnel step).
- `/reports/success` — post-checkout thank-you. Reads `session_id`
  query param. If the report is live, shows "check your email for the
  download link." If the report is a pre-order, shows "check your
  email for your pre-order confirmation; the report ships [date]."
- `/reports/access` — magic-link entry. Takes `?token=...`, redirects
  to `/api/reports/download` on page load, shows spinner + fallback
  email-entry form.

No tier selector. No `/publisher` page. No inquiry form. Framing
copy reads "landscape vs plan," not "top-5 free vs top-10 paid."

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
- New Lambda `DeliverySweepFunction` wired to a daily EventBridge
  rule + manual invoke (for use when the operator flips a report's
  `published_at` after uploading the PDF). Calls
  `ReportPurchaseService.sweep_pre_order_deliveries()`. 60s timeout,
  512MB memory.
- Extend existing API Lambda IAM to read the SSM params above and
  read from the reports bucket (signed URL generation needs
  `s3:GetObject`).
- EventBridge daily rule calling a small `MagicLinkPruneLambda` to
  delete expired tokens.
- No CloudFormation output needed beyond the SSM params (frontend
  reads Stripe publishable key at build time from SSM).

### 8. Stripe dashboard setup (operator, one-time)

Operator does this manually in the Stripe dashboard — not in code:

- Enable **Stripe Tax** (required; no custom tax logic in our code).
- Create **one Product per report edition**, and **one Price** at $49 one-time:
  - `rdb-2026-q2` — $49 one-time
- Record the `price_id` in the `reports` table via an ops script
  `scripts/ops/seed_report_catalog.py`.
- Configure Checkout branding (logo, colors).
- Configure **webhook endpoint** pointing at
  `https://steampulse.io/api/stripe/webhook`, listening for
  `checkout.session.completed` only. Capture the signing secret
  into the SSM param above.
- Enable **Customer Portal** — harmless default for refund handling
  even on one-off purchases.

### 9. Email templates (Resend)

Templates live in `library_layer/email_templates/` as module constants
(Jinja2 or plain f-string; mirror existing email patterns). Two
templates are needed:

**`report_receipt_live.py`** — sent when the purchase is for a live
(already-published) report. Fields: buyer name (optional), report
display_name, amount paid, tax amount, magic-link URL (30-min TTL),
what-to-expect block (PDF + CSV), support email.

**`report_receipt_preorder.py`** — sent when the purchase is for a
pre-order. Fields: buyer name, report display_name, amount paid,
tax amount, `published_at` formatted as a human-readable ship date,
what-to-expect block ("you'll receive a download link on [date]"),
support email. **No magic-link, no signed URL** — there is nothing to
download yet.

When the delivery sweep fires for a pre-order purchase, use
`report_receipt_live.py` with a slight copy variant ("your report is
ready" instead of "thanks for your purchase"). Keep it as a third
template `report_receipt_ship.py` rather than branching inside the
live template.

## Verification

1. **Migration applies**: `bash scripts/dev/migrate.sh`; `\d reports`,
   `\d report_purchases`, `\d leads`, `\d magic_link_tokens` all show
   expected schema. `report_purchases.delivered_at` exists and is
   nullable.
2. **Catalog seed**: `python scripts/ops/seed_report_catalog.py` upserts
   the RDB report rows tied to real Stripe Price IDs.
3. **Stripe webhook signature verification**: integration test posts a
   tampered payload → handler returns 400.
4. **Live-report happy path**: seed a `reports` row with
   `published_at = now() - '1 day'`. Call `/api/checkout/start`,
   complete checkout in Stripe test mode. Assert: `report_purchases`
   row written with `delivered_at ≈ now()`. Receipt email sent via
   Resend (mock in test). Magic-link redeems to signed S3 URL once
   and errors on second use.
5. **Pre-order happy path**: seed a `reports` row with
   `published_at = now() + '14 days'`. Complete checkout. Assert:
   `report_purchases` row written with `delivered_at = NULL`.
   Pre-order receipt email sent (no magic-link). Magic-link endpoint
   called with this buyer's email returns 200 with no Resend call.
6. **Delivery sweep**: with the pre-order row from (5) in place, flip
   the `reports.published_at` to `now() - '1 second'`. Invoke
   `DeliverySweepFunction` manually. Assert: ship-notice email sent
   via Resend. `delivered_at` set. Magic-link endpoint now returns
   the signed URL on request. Re-running the sweep emails nobody
   (idempotency).
7. **Idempotency**: replay the same `checkout.session.completed`
   event → second call is a no-op (UNIQUE on
   `stripe_checkout_session_id`). No duplicate receipt email.
8. **Magic-link expiry**: create a token with TTL -1 min; consume
   returns 410.
9. **No-account enumeration**: `/api/reports/magic-link` with a
   never-seen email returns 200 with no Resend call. Same for an
   email with only un-delivered pre-orders.
10. **Rate limiting**: hitting `/api/checkout/start` 20 times in 60s
    from one IP returns 429 after the threshold.
11. `poetry run pytest -v && poetry run ruff check .`

## Out of scope

Everything below is either Tier-2-gated or killed. Do not build any
of these as part of this prompt.

- **Subscription / NL chat / Pro tier** — Tier 2 gated (see
  `monetization-strategy.md`). No Stripe Subscription code path in
  Tier 1.
- **Genre Q&A add-on ($79)** — Tier 2 gated (10+ buyers ask).
- **1-yr All-Access Pass ($149, same genre family)** — Tier 2 gated
  (5+ reports shipped AND 100+ unique buyers).
- **White-label / team license ($499)** — Tier 2 gated (3+ publisher
  emails requesting). No multi-seat logic in Tier 1.
- **"Genre Audit" self-serve SKU ($79)** — Tier 2 gated (catalog
  MRR > $3k/mo × 3 months required).
- **Refund automation** — manual via Stripe dashboard for Tier 1;
  volume doesn't justify automation.
- **Abandoned-checkout re-engagement / lead drip sequences** — no
  newsletter at launch; defer indefinitely.
- **Affiliate / referral tracking** — not built.

## Rollout

- One migration. Two new Lambdas (`StripeWebhookFunction`,
  `DeliverySweepFunction`). Extensions to the existing API Lambda.
  One new S3 bucket. No redirects, no migration, no legacy
  compatibility.
- No deploy from Claude — user runs `bash scripts/deploy.sh` and the
  Stripe dashboard setup themselves.
- After deploy: seed the catalog with the RDB row (`published_at` set
  to the future ship date for pre-order mode), fire a Stripe
  test-mode purchase end-to-end in both live-report and pre-order
  configurations, switch webhook to live mode.
