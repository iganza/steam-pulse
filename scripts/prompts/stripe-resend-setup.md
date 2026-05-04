# Stripe + Resend setup

Wire Stripe Checkout (subscription + one-time SKUs) and Resend (transactional emails) for SteamPulse. This prompt is the implementation spec for the payment + email half of launch-plan Step 2. The auth half is `scripts/prompts/better-auth-setup.md`.

The schema and lifecycle this delivers is defined in `scripts/prompts/rdb-launch-spec.md` Sections 4 (pricing + Stripe Product names) and 5 (entitlement schema). This prompt makes it concrete and actionable.

## Prerequisites

Before any code: three accounts that only the operator can create.

### Stripe

- [ ] Account at https://stripe.com. Verify the business so live mode unlocks.
- [ ] In Stripe dashboard, create two Products with the exact names below (the spec pins these):
  - **Product:** `SteamPulse Subscription`
    - Monthly Price: $19.00 USD recurring monthly. Metadata: `tier=subscription`, `period=monthly`
    - Annual Price: $190.00 USD recurring yearly. Metadata: `tier=subscription`, `period=annual`
  - **Product:** `SteamPulse Genre Report: Roguelike Deckbuilder`
    - Single Price: $79.00 USD one-time. Metadata: `tier=one_time`, `report_slug=roguelike-deckbuilder`
- [ ] Capture Publishable Key (`pk_live_...`) and Secret Key (`sk_live_...`).
- [ ] Webhook endpoint: configure for `https://steampulse.io/api/webhook/stripe` listening to `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`. Capture the signing secret (`whsec_...`).
- [ ] Customer Portal: enable in dashboard so subscribers can self-manage cancellation. Default link is fine.
- [ ] Use test mode keys for local dev (`pk_test_...`, `sk_test_...`); same Products in test mode.

### Resend

Resend is already integrated. Existing infrastructure to reuse:

- `library_layer/utils/email.py`: `EmailSender` protocol + `ResendEmailSender` implementation. Provider-swappable.
- `library_layer/events.py`: `BaseSqsMessage` and `SqsMessageType` literal. Existing message: `WaitlistConfirmationMessage`.
- `lambda-functions/lambda_functions/email/handler.py`: SQS-triggered Lambda dispatching by `message_type`. Currently handles `waitlist_confirmation`.
- API key already in SSM under `RESEND_API_KEY_PARAM_NAME` (referenced via `SteamPulseConfig`).
- Sending domain `send.steampulse.io` already verified; `_FROM_ADDR = "SteamPulse <hello@send.steampulse.io>"`, `_REPLY_TO = "feedback@steampulse.io"`.

No new accounts, no new SSM parameters, no new Lambda. New transactional emails ship as new SQS message types + new dispatcher cases in the email handler. Pattern documented below.

### SSM Parameter Store (Stripe only; Resend already wired)

- [ ] `/steampulse/prod/stripe/publishable_key`
- [ ] `/steampulse/prod/stripe/secret_key`
- [ ] `/steampulse/prod/stripe/webhook_signing_secret`

For local dev: same names in `.env.local` under `STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`. CDK synth wires the SSM parameters into the Lambda + Next.js environment. Resend's `RESEND_API_KEY_PARAM_NAME` is unchanged.

## Files to create / modify

### Database migration

`src/lambda-functions/migrations/<next>__entitlements_tables.sql`:

```sql
-- depends: 0057_waitlist_confirmation_sent_at
-- transactional: true

CREATE TABLE subscriptions (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stripe_customer_id TEXT NOT NULL,
    stripe_subscription_id TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL,
    current_period_end TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX subscriptions_user_idx ON subscriptions (user_id);

CREATE TABLE report_purchases (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    report_slug TEXT NOT NULL,
    stripe_session_id TEXT UNIQUE NOT NULL,
    purchased_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    access_until TIMESTAMPTZ NOT NULL
);
CREATE INDEX report_purchases_user_slug_idx
    ON report_purchases (user_id, report_slug);

CREATE TABLE reports (
    slug TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    benchmark_appids INTEGER[] NOT NULL DEFAULT '{}',
    stripe_one_time_price_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Repository

`src/library-layer/library_layer/repositories/entitlement_repo.py` (new):

- `get_active_subscription(user_id) -> Subscription | None`
- `get_one_time_purchase(user_id, report_slug) -> ReportPurchase | None`
- `upsert_subscription(...)` for webhook handlers
- `insert_report_purchase(...)` for webhook handlers
- All methods accept `user_id: str`. No email lookups in entitlement queries.

`src/library-layer/library_layer/repositories/report_repo.py` (new or extend):

- `get_published_report(slug) -> Report | None`
- `list_published_reports() -> list[Report]`
- Used by the genre page server-side render and by `/api/checkout/start` to look up the right Stripe Price ID.

### Pydantic models

Per the workflow rule, all domain objects use `pydantic.BaseModel`. Add to `src/library-layer/library_layer/models/`:

- `subscription.py` with `Subscription(BaseModel)` and a `SubscriptionStatus` literal
- `report_purchase.py` with `ReportPurchase(BaseModel)`
- `report.py` with `Report(BaseModel)`

### API routes

These live in the existing FastAPI handler at `src/lambda-functions/lambda_functions/api/...`.

- [ ] `POST /api/checkout/start` (auth required):
  - Read `user_id` from `auth.api.getSession({ headers })` (Better Auth, server-side; see `scripts/prompts/better-auth-setup.md`). 401 if unauthenticated.
  - Body: `{mode: "subscription" | "one_time", period?: "monthly" | "annual", report_slug?: string}`.
  - Look up the right Stripe Price ID:
    - `mode=subscription` + `period=monthly` → fixed env var `STRIPE_SUB_MONTHLY_PRICE_ID`
    - `mode=subscription` + `period=annual` → fixed env var `STRIPE_SUB_ANNUAL_PRICE_ID`
    - `mode=one_time` → `reports.stripe_one_time_price_id` for the slug
  - Create Stripe Checkout Session with `metadata.user_id` and `metadata.report_slug` (if one-time). Set `success_url` to `/genre/[slug]/?welcome=1`, `cancel_url` to `/genre/[slug]/`.
  - Return `{url: session.url}`.

- [ ] `POST /api/webhook/stripe` (no auth, signature-verified):
  - Verify signature using `stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)`.
  - Idempotency: check `event.id` against a small `processed_webhook_events` cache table OR rely on the unique constraints on `stripe_subscription_id` / `stripe_session_id` to swallow duplicates.
  - Event handlers:
    - `checkout.session.completed` (mode=payment, i.e. one-time): read `metadata.user_id` and `metadata.report_slug`, insert `report_purchases` row with `access_until = now() + INTERVAL '30 days'`. Send Resend confirmation email.
    - `customer.subscription.created` and `.updated`: upsert `subscriptions` row keyed on `stripe_subscription_id`. On `created`, send subscription confirmation email.
    - `customer.subscription.deleted`: update status to `canceled`, preserve row.
  - Return 200 quickly. Heavy work (Resend sends) can be inline at v1; consider SQS dispatch later if webhook latency becomes a problem.

- [ ] `POST /api/billing-portal` (auth required): create a Stripe Billing Portal session for the authenticated user's `stripe_customer_id` and return the URL. Used by the "Manage subscription" link on the `/account` page.

### New SQS message types and email handler dispatch

Email infrastructure is already in place; this step only adds new message types + dispatcher cases. No new Lambda, no Resend setup.

- [ ] In `library_layer/events.py`: extend `SqsMessageType` literal with three new strings:
  - `"subscription_confirmed"`
  - `"report_purchase_confirmed"`
  - `"report_updated"`
- [ ] Add three new message classes (after `WaitlistConfirmationMessage`):
  ```python
  class SubscriptionConfirmedMessage(BaseSqsMessage):
      message_type: SqsMessageType = "subscription_confirmed"
      email: str

  class ReportPurchaseConfirmedMessage(BaseSqsMessage):
      message_type: SqsMessageType = "report_purchase_confirmed"
      email: str
      report_slug: str
      report_display_name: str

  class ReportUpdatedMessage(BaseSqsMessage):
      message_type: SqsMessageType = "report_updated"
      email: str
      report_slug: str
      report_display_name: str
  ```
- [ ] In `lambda-functions/lambda_functions/email/handler.py`: add three new `case` branches in the `match msg_type` block. Each calls a new `_handle_*` helper that uses the existing `_sender.send(...)` with `_FROM_ADDR` and `_REPLY_TO`. Match the inline-HTML style used by `_handle_waitlist_confirmation`.
- [ ] Stripe webhook (in the API handler) enqueues these messages to the existing email SQS queue; it does not call Resend directly. Same dispatch pattern as the existing waitlist flow.

### Email content (inline HTML, ~5 to 10 lines each)

- **Subscription confirmed:** "Welcome to SteamPulse. You have access to every published genre report and every future report at https://steampulse.io. Manage your subscription at https://steampulse.io/account."
- **Report purchase confirmed:** "Thanks for buying the [Genre] report. You have on-site access at https://steampulse.io/genre/[slug]/ for 30 days. Subscribe at https://steampulse.io to get every report and never lose access."
- **Report updated** (sent when an editorial revision lands; v1 gated off behind a config flag, enable later): "The [Genre] report just got an update. View the latest at https://steampulse.io/genre/[slug]/."

Magic-link emails for sign-in are owned by `scripts/prompts/better-auth-setup.md` (a `magic_link` SQS message type sent via the same email Lambda). The three messages above are pure transactional confirmations for purchases.

### Frontend wiring

Better Auth owns sign-in. Buy block work:

- [ ] `frontend/components/genre/ReportBuyBlock.tsx`: wire the Subscribe and Buy buttons to call `POST /api/checkout/start` with the right `mode`. If `useSession()` returns no session, redirect to `/sign-in?redirect=/genre/${slug}` first; the user signs in, returns, and re-clicks. After a session exists, the POST resolves to a Stripe Checkout URL; redirect there.
- [ ] `frontend/lib/entitlements.ts` (called by the genre page server-side render): given `user_id` and `slug`, run the two SQL queries from `rdb-launch-spec.md` Section 5 against `subscriptions` and `report_purchases`. Return `{ paid: boolean, source: 'subscription' | 'one_time' | null, expires_at: string | null }`.

## Verification

- [ ] Local: trigger Stripe webhook with `stripe trigger checkout.session.completed --add 'metadata.user_id=<a-real-test-uuid>' --add 'metadata.report_slug=roguelike-deckbuilder'`. Confirm a `report_purchases` row appears (the user_id must match an existing `users.id` for the FK constraint to satisfy).
- [ ] Local: trigger `customer.subscription.created`. Confirm a `subscriptions` row appears with `status='active'`.
- [ ] End-to-end test against Stripe test mode:
  - Sign in as test user via Better Auth (Google OAuth or magic link).
  - Click Subscribe on `/genre/roguelike-deckbuilder/`. Backend reads the session, creates the Stripe Checkout Session with `metadata.user_id`, redirects to Stripe.
  - Complete with test card `4242 4242 4242 4242`. Webhook fires. Page reloads in paid mode.
  - Click "Manage subscription" → Stripe Customer Portal session opens.
  - Cancel from the portal. Webhook fires `subscription.deleted`. Reload `/genre/roguelike-deckbuilder/`. Page renders free mode (current_period_end may still be in the future, in which case paid mode persists until the period ends, per Stripe defaults).
- [ ] One-time end-to-end: sign in fresh test user, click Buy this report, complete with test card, verify `report_purchases` row + Resend email.
- [ ] `stripe listen --forward-to localhost:3000/api/webhook/stripe` for local webhook delivery. Verify signature validation rejects requests with the wrong secret.

## What this prompt does not decide

- Better Auth integration (sign-in / sign-out / sessions / magic-link emails): `scripts/prompts/better-auth-setup.md` owns it.
- Per-game preview frontend (showcase / canonical / preview decision): launch-plan Step 4.
- Genre page paid-mode rendering (the full synthesis layout): launch-plan Step 5.
- Editorial polish content (`editorial_intro`, `churn_interpretation` updates): launch-plan Step 8.

## Failure modes worth handling explicitly

- **Webhook arrives without metadata.user_id.** Defensive: the webhook reads `metadata.user_id` set by `/api/checkout/start`, which itself required an authenticated Better Auth session. So `user_id` is always present at `checkout.session.completed` time. If absent (defensive log), fail loud rather than insert a row with NULL identity. The FK constraint on `subscriptions.user_id` and `report_purchases.user_id` would also reject a NULL or invalid id.
- **Refund or chargeback.** Stripe sends `charge.refunded` / `charge.dispute.created`. v1 logs these and emails the operator; manual `UPDATE` on the affected `subscriptions` or `report_purchases` row. Don't auto-revoke at v1; the operator's reaction is part of the loop.
- **Webhook duplicate delivery.** Stripe retries failed webhooks. Unique constraints on `stripe_subscription_id` and `stripe_session_id` make repeat inserts no-ops. The `customer.subscription.updated` handler is naturally idempotent (it upserts by `stripe_subscription_id`).
- **Customer changes their email.** Better Auth's email-update flow keeps the same `users.id`. Entitlements survive untouched. Stripe's `customer.email` may diverge from the Better Auth email; not a problem because we never key on email.
