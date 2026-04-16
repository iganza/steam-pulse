# Cleeng integration — subscription billing + merchant of record

## Context

SteamPulse uses **Cleeng** (https://cleeng.com) for Pro subscription billing,
merchant-of-record services, and entitlement management. This prompt covers
the full integration: hosted checkout, webhook handling, entitlement sync
into our own DB for fast Pro-status checks, and wiring into the existing
Pro-gating frontend.

This is Stage 2 of the launch plan (see `steam-pulse.org` → Active Launch
Plan). It depends on `auth0-authentication.md` being complete, and pairs
with `pricing-page.md`. See `scripts/prompts/monetization-strategy.md` for
the tier strategy ($15/mo Pro only at launch; no Pro+ yet, no one-off
unlock).

## Why Cleeng (vs rolling our own Stripe)

- **Free platform up to 10,000 subscribers** — $0 platform fee, no monthly cost.
  SteamPulse will not exceed this threshold for a very long time, if ever.
- **Merchant of record** — Cleeng is the seller of record on the transaction:
  - Tax calculation + remittance across 13,000+ jurisdictions (VAT MOSS,
    GST, US state sales tax) — handled, not our problem.
  - Chargeback dispute management — handled.
  - PCI compliance — Cleeng's scope, not ours.
  - GDPR / PSD2 — handled.
- **Built-in entitlement & identity** — we don't reimplement
  customer/subscription lifecycle; Cleeng has it.
- **Native coupons & campaigns** — the "3-months free for waitlist members"
  mechanic is a first-class Cleeng feature, not a custom coupon table.
- **ChurnIQ analytics** — subscription health, dunning, failed-payment
  recovery out of the box.
- **Hosted checkout** — we don't build our own card form.
- **Transaction fees**: promo $0.35 + 3.5% (through June 2026);
  regular $0.39 + 3.9%. Slightly more than Stripe's $0.30 + 2.9%, but
  covers tax + compliance that would otherwise need Stripe Tax (+0.5%)
  or Paddle/Quaderno (another vendor).

## Architecture decisions (locked)

1. **auth0 is the identity provider.** Users log in with auth0. The auth0
   `user_id` is used as the Cleeng `customerId` via the Cleeng API's
   external-ID mapping. Cleeng does NOT replace auth0.
2. **Merchant of Record is enabled** (Cleeng's MoR add-on). The small
   fee premium is worth the compliance offload at indie-SaaS scale.
3. **Hosted checkout at launch.** Redirect to Cleeng-hosted checkout;
   embedded/SDK integration is a later optimisation if conversion data
   justifies it.
4. **Entitlement is cached locally** in a Postgres `entitlements` table.
   Cleeng webhooks keep it fresh. Every Pro-check reads the local cache;
   we never call the Cleeng API on the hot path.
5. **One Cleeng product / one offer at launch**: Pro $15/mo.
   Pro+ lives in Cleeng config post-Stage-4 signal.

## Data model

### New migration

Create `src/lambda-functions/migrations/00NN_entitlements.sql`:

```sql
-- depends: <latest migration>

CREATE TABLE IF NOT EXISTS entitlements (
    auth0_user_id        TEXT PRIMARY KEY,
    cleeng_customer_id   TEXT UNIQUE NOT NULL,
    tier                 TEXT NOT NULL DEFAULT 'free',          -- 'free' | 'pro' | 'pro_plus'
    active_until         TIMESTAMPTZ,                            -- NULL when free
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    cleeng_offer_id      TEXT,                                   -- which Cleeng offer
    last_webhook_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_entitlements_cleeng_customer
    ON entitlements(cleeng_customer_id);
CREATE INDEX IF NOT EXISTS idx_entitlements_active_until
    ON entitlements(active_until);
```

Mirror the DDL in `library_layer/schema.py`.

### Repository

Create `src/library-layer/library_layer/repositories/entitlement_repo.py`:

- Extends `BaseRepository`
- `get_by_auth0_user_id(auth0_user_id) -> Entitlement | None`
- `get_by_cleeng_customer_id(cleeng_customer_id) -> Entitlement | None`
- `upsert(entitlement: Entitlement) -> None` — from webhook
- `is_pro(auth0_user_id) -> bool` — single hot-path query:
  `SELECT 1 FROM entitlements WHERE auth0_user_id = %s AND tier IN ('pro','pro_plus') AND (active_until IS NULL OR active_until > NOW())`

No business logic in the repo. All tier-expiry math in the service layer.

### Pydantic model

`library_layer/models/entitlement.py`:

```python
class Entitlement(BaseModel):
    auth0_user_id: str
    cleeng_customer_id: str
    tier: Literal["free", "pro", "pro_plus"]
    active_until: datetime | None
    cancel_at_period_end: bool = False
    cleeng_offer_id: str | None = None
    last_webhook_at: datetime
    created_at: datetime
    updated_at: datetime
```

## Service layer

`library_layer/services/entitlement_service.py`:

- `is_pro(auth0_user_id: str) -> bool` — wraps repo call
- `get_or_create_cleeng_customer(auth0_user_id: str, email: str) -> str` —
  idempotent; creates Cleeng customer on first subscribe attempt, stores
  `cleeng_customer_id` in the entitlements row with `tier='free'`
- `apply_webhook(event: CleengWebhookEvent) -> None` — the entry point
  for all subscription lifecycle events; updates the entitlements row
- `build_checkout_url(auth0_user_id: str, offer_id: str, coupon: str | None = None) -> str` —
  calls Cleeng API to create a hosted checkout session, returns the URL

External API client:
`library_layer/services/cleeng_client.py`:

- Thin wrapper around Cleeng REST API using `httpx`
- API key read from SSM (`CLEENG_API_KEY_SECRET_NAME` env var →
  Secrets Manager path `steampulse/{env}/cleeng-api-key`)
- `create_customer(email, external_id) -> customer_id`
- `create_checkout_session(customer_id, offer_id, coupon, success_url, cancel_url) -> url`
- `get_subscription(customer_id) -> dict` — for reconciliation / cache miss

## Webhook handler

New Lambda at `src/lambda-functions/lambda_functions/webhooks/cleeng_webhook.py`:

1. Verify signature header against `CLEENG_WEBHOOK_SECRET` (from Secrets Manager).
   On mismatch return 401.
2. Parse body as typed `CleengWebhookEvent` (new Pydantic model in `events.py`).
3. Match on event type:
   - `subscription.created`, `subscription.renewed`, `subscription.updated`
     → upsert entitlement with `tier='pro'`, `active_until = next_renewal_at`.
   - `subscription.cancelled` → set `cancel_at_period_end=True`, keep
     `active_until` as-is (user retains access until period end).
   - `subscription.expired` → downgrade to `tier='free'`, clear `active_until`.
   - `payment.failed` → log only at launch (dunning handled by Cleeng).
4. Return 200 on success; 5xx on transient failure so Cleeng retries.

CDK: expose via a dedicated Function URL or API Gateway route. Do NOT
hang this off the existing FastAPI Lambda — webhooks want simple, cold-start-friendly
isolation. Add `tracing=ACTIVE`. Use Powertools `Logger` with
`service="cleeng-webhook"`.

## API endpoints (FastAPI)

Add to `src/lambda-functions/lambda_functions/api/handler.py`:

- `POST /api/subscribe` — authenticated (auth0 bearer). Body:
  `{ "offer_id": "...", "coupon": "WAITLIST3M" | None }`.
  Calls `entitlement_service.build_checkout_url()`, returns
  `{ "checkout_url": "..." }`. Frontend does `window.location = checkout_url`.
- `GET /api/me/entitlement` — authenticated. Returns the user's current
  tier + `active_until` + `cancel_at_period_end`. Used by `usePro()`.
- `POST /api/subscription/cancel` — authenticated. Calls Cleeng API to
  cancel; webhook will update the local row.
- Remove the existing stubbed `/api/validate-key` — `is_pro()` now reads
  from the entitlements table.

## Frontend wiring

In `frontend/lib/api.ts`: add typed client methods for the three endpoints above.

In `frontend/app/pro/page.tsx` (exists as stub):
- "Subscribe — $15/mo" button → `POST /api/subscribe` with the Pro offer ID
  → redirect to `checkout_url`.
- If user is already Pro, show manage-subscription state instead.

In `frontend/components/...` `usePro()` hook:
- Replace the current `validate-key` call with `GET /api/me/entitlement`.
- Cache entitlement in the auth context; refresh on focus and after
  checkout redirect-back.

Post-checkout redirect: Cleeng posts the webhook BEFORE the user is
redirected back, usually. Assume the local entitlement may lag by a few
seconds — the redirect-back page should poll `GET /api/me/entitlement`
for up to 10 s and show a loading state until `tier='pro'` appears.

## Waitlist coupon wiring

The "3 months free for waitlist members" mechanic (see Active Launch
Plan, Stage 2):

1. Create a Cleeng campaign in the dashboard: code `WAITLIST3M`,
   3-month free trial, restricted to the Pro offer.
2. When emailing the waitlist, include a unique signed URL that passes
   `?coupon=WAITLIST3M` to `/pro`.
3. The `/pro` page reads the coupon param, passes it to
   `POST /api/subscribe`, which forwards it to Cleeng checkout.
4. No custom coupon table in our DB — Cleeng owns this.

## Infrastructure (CDK)

In `infra/stacks/data_stack.py`:
- The `entitlements` table is created by the yoyo migration, not CDK.
  (Tables aren't CDK-managed in this project.)

In `infra/stacks/compute_stack.py`:
- New `cleeng_webhook_fn` `PythonFunction` with Function URL
- Grant `secret.grant_read(cleeng_webhook_fn.role)` for the Cleeng webhook secret
- Grant DB access via the existing VPC + security-group pattern
- `tracing=lambda_.Tracing.ACTIVE`
- API Lambda gets Cleeng API key secret read grant (for `build_checkout_url`)

In `infra/stacks/messaging_stack.py` or a new config location:
- Add secrets:
  - `steampulse/{env}/cleeng-api-key`
  - `steampulse/{env}/cleeng-webhook-secret`

New env vars (literals, no SSM needed):
- `CLEENG_ENVIRONMENT` — `sandbox` | `production`
- `CLEENG_PUBLISHER_ID` — the Cleeng-assigned publisher ID
- `CLEENG_PRO_OFFER_ID` — the offer ID for the $15/mo Pro plan
- `CLEENG_WEBHOOK_SECRET_NAME` — Secrets Manager path
- `CLEENG_API_KEY_SECRET_NAME` — Secrets Manager path

## Events / SQS

Add typed models to `library_layer/events.py`:

- `CleengWebhookEvent(BaseModel)` — strongly-typed subset of the Cleeng
  webhook payload we actually consume. Include event_type literal.
- `EntitlementChangedEvent(BaseEvent)` — published on SNS when a user's
  tier changes. Downstream consumers (welcome-email worker,
  cancellation-survey worker, analytics) subscribe to this.

## Observability

- Powertools `Logger` on the webhook Lambda with structured fields:
  `auth0_user_id`, `cleeng_customer_id`, `event_type`.
- Metric counter on subscription lifecycle events:
  `Subscriptions/Created`, `Subscriptions/Cancelled`, `Subscriptions/Expired`.
- CloudWatch alarm on webhook 5xx rate > 1% over 15 min.

## Tests

- `tests/services/test_entitlement_service.py` — unit tests for
  `is_pro()` edge cases (expired, cancelled-but-still-in-period, free).
- `tests/handlers/test_cleeng_webhook.py` — signature verify, each
  event type upserts correctly, idempotency (replay the same webhook
  twice → same DB state).
- `tests/smoke/test_subscription_flow.py` — smoke test against Cleeng
  sandbox: create test user → subscribe → webhook fires → entitlement
  row reflects tier=pro → cancel → row reflects cancel_at_period_end.
  Mark `@pytest.mark.smoke`; runs against `CLEENG_ENVIRONMENT=sandbox`.

## Rollout sequence

1. Cleeng sandbox account set up, publisher ID + Pro offer ID configured.
2. Migration + repo + service + CleengClient (unit-testable).
3. Webhook Lambda + CDK wiring; point Cleeng sandbox to staging webhook URL.
4. API endpoints + frontend wiring against staging.
5. End-to-end test: subscribe in sandbox → Pro sections unlock in staging.
6. Waitlist coupon created in Cleeng sandbox; test the coupon URL flow.
7. Swap to Cleeng production credentials on prod deploy.
8. Email waitlist with the coupon URL on launch day (Stage 2 of plan).

## Out of scope (explicitly)

- **Pro+ tier** — deferred until Stage 4 signal. Adds a second Cleeng offer
  + tier handling in the entitlement row when that happens.
- **Multi-seat / team billing** — Pro+ feature, not Stage 2.
- **Embedded/SDK checkout** — hosted at launch. Migrate only if conversion
  data justifies the engineering.
- **Custom dunning / failed-payment email campaigns** — Cleeng handles this
  natively via ChurnIQ; don't rebuild.
- **Custom tax handling** — Cleeng MoR handles all tax. Never compute tax
  ourselves.

## Open questions to resolve during implementation

- How does Cleeng's auth model interact with our auth0 session? Specifically:
  does the redirect-back from hosted checkout need us to re-establish the
  auth0 session, or is the original session still valid?
- What's the actual webhook event-type catalogue? Verify against Cleeng's
  current API docs before writing the match statement in the handler.
- Rate limits on the Cleeng API for `create_checkout_session` — add a
  Powertools retry decorator if needed.
