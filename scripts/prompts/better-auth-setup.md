# Better Auth setup

Wire **Better Auth** as the identity provider for SteamPulse: magic link + Google OAuth + logout + account management. **Auth state lives on DynamoDB**, not RDS Postgres. This is a deliberate divergence from the prompt's earlier draft (which assumed Postgres) so that the sign-in path is isolated from RDS health: a slow or degraded small-instance RDS cannot bring down user sign-in. We still own the user table (no third-party identity provider).

This prompt is the implementation spec for the auth half of launch-plan Step 2 (the Stripe + Resend half is `scripts/prompts/stripe-resend-setup.md`).

The shape this delivers is defined in `scripts/prompts/rdb-launch-spec.md` Section 5. This prompt makes it concrete and actionable.

## Why Better Auth

Open-source TypeScript-first auth framework, current maintainer of Auth.js (NextAuth) and the recommended starting point for new Next.js projects in 2026. Plugin-based architecture covers magic link, Google OAuth, passkeys, 2FA, organisations, and account UI patterns while keeping the user database in storage we control. Zero recurring cost, zero vendor lock-in, no migration ever required because the user records are ours.

Sources:
- Docs: https://better-auth.com/
- Next.js integration guide: https://better-auth.com/docs/integrations/next
- Custom adapter guide: https://better-auth.com/docs/guides/create-a-db-adapter
- Stewardship announcement: https://better-auth.com/blog/authjs-joins-better-auth

## Why DynamoDB (not Postgres)

The prompt's earlier draft put Better Auth on Postgres. We are diverging because:

1. **Auth must keep working when RDS is degraded.** Small-instance RDS may be slow under load. Sign-in (a request on every authenticated page render) cannot be on the same critical path as report data.
2. **Lambda + Postgres connection management is its own problem.** Each cold start opens new connections; mitigations (RDS Proxy, pgbouncer) add cost and operational surface. DynamoDB has no connection pool.
3. **We own the read/write characteristics.** Better Auth on DynamoDB has predictable single-digit-ms reads at any traffic level with on-demand billing.

Trade-offs accepted: a custom adapter is required (no production-grade community adapter exists; `renanwilliam/better-auth-dynamodb` is a single-author reference repo, not on npm, ~5 commits). We use Better Auth's official `createAdapterFactory` and validate against `@better-auth/test-utils`. Effort: roughly 3 to 5 days.

Note: `checkEntitlement` (paid-mode genre page check) still queries RDS because `subscriptions` and `report_purchases` live there. The DynamoDB choice isolates sign-in and session lookup, not entitlement reads.

## Prerequisites

- [ ] **Google OAuth client.** Create a project in Google Cloud Console, enable Google Identity, add an OAuth 2.0 Client ID for "Web application", add `https://steampulse.io/api/auth/callback/google` and `http://localhost:3000/api/auth/callback/google` as authorized redirect URIs. Capture client ID + client secret.
- [ ] **Resend** is already wired (`RESEND_API_KEY_PARAM_NAME` in SSM, `ResendEmailSender` class, sending domain verified). Magic-link emails reuse this infrastructure via Better Auth's `sendMagicLink` callback.
- [ ] **Real DynamoDB dev table** (`BetterAuth-dev` in the same AWS account as production). DynamoDB Local was tried and dropped: Java startup is fragile, AWS SDK auth quirks, and pay-per-request DynamoDB in the real account is effectively free at dev volumes. Provisioned once via `scripts/dev/create-ddb-tables.sh`; the table persists.
- [ ] **Postgres** is already provisioned (the existing app DB) and continues to host all non-auth data: `games`, `mv_genre_synthesis`, `subscriptions`, `report_purchases`, etc.

### SSM Parameter Store

Follow the existing `/steampulse/{env}/{subsystem}/{name}` convention (env values are `staging` or `production`, not `prod`). Auth gets its own subsystem path:

- [ ] `/steampulse/production/auth/better-auth-secret` (SecureString; generate with `openssl rand -base64 32`)
- [ ] `/steampulse/production/auth/google-client-id` (SecureString)
- [ ] `/steampulse/production/auth/google-client-secret` (SecureString)

For local dev: same values in `frontend/.env.local` as `BETTER_AUTH_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (the Google OAuth client has both prod and `localhost` redirect URIs allowed, so a single client serves both environments). CDK synth wires SSM into the Next.js Lambda environment.

## Files to create / modify

### DynamoDB table (CDK)

Single-table design. One table holds all four Better Auth entities (users, sessions, accounts, verifications), distinguished by the `pk` prefix. Defined in `infra/stacks/data_stack.py` (or wherever the existing CDK convention places shared tables; match the file that hosts the OpenNext cache table). On-demand billing, point-in-time recovery enabled, `RemovalPolicy.RETAIN` for production.

`BetterAuth-{env}`:
- PK `pk` (S), SK `sk` (S).
- GSI1 `unique-lookup`: `gsi1_pk` (S), `gsi1_sk` (S). Serves the four unique-key access patterns: user-by-email, session-by-token, account-by-(provider, provider-account-id), verification-by-identifier.
- GSI2 `user-index`: `gsi2_pk` (S), `gsi2_sk` (S). Serves the two one-to-many access patterns: sessions-for-user, accounts-for-user.
- TTL: `expires_at` (N, epoch seconds). Covers sessions and verifications with one config; non-expiring entities (users, accounts) omit the attribute.

Item shapes (logical schema; the adapter writes/reads these):

| Entity | pk | sk | gsi1_pk / gsi1_sk | gsi2_pk / gsi2_sk |
|---|---|---|---|---|
| User | `USER#<id>` | `META` | `EMAIL#<email>` / `USER` | (none) |
| Session | `SESSION#<id>` | `META` | `TOKEN#<token>` / `SESSION` | `USER#<user_id>` / `SESSION#<created_at>` |
| Account | `ACCOUNT#<id>` | `META` | `PROVIDER#<provider_id>#<account_id>` / `ACCOUNT` | `USER#<user_id>` / `ACCOUNT` |
| Verification | `VERIFICATION#<id>` | `META` | `IDENTIFIER#<identifier>` / `VERIFICATION` | (none) |

The frontend Lambda role gets `grant_read_write_data` on the table and both GSIs. Table name is injected as a single env var: `BETTER_AUTH_TABLE`.

### Custom Better Auth DynamoDB adapter

`frontend/lib/auth-dynamodb-adapter.ts`:

```ts
import { createAdapterFactory } from "better-auth/adapters";
import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, GetCommand, PutCommand, QueryCommand, UpdateCommand, DeleteCommand, ScanCommand } from "@aws-sdk/lib-dynamodb";

export const dynamoAdapter = createAdapterFactory({
  config: { adapterId: "dynamodb", adapterName: "DynamoDB", supportsBooleans: true, supportsDates: true, supportsJSON: true },
  adapter: ({ getDefaultModelName, getFieldName, schema }) => {
    // Single table from env. Items keyed by entity-prefixed pk + literal sk = "META".
    // 8 CRUD ops: create, update, updateMany, delete, deleteMany, findOne, findMany, count.
    //   - id lookup       -> GetCommand on (pk = "<ENTITY>#<id>", sk = "META")
    //   - unique key      -> QueryCommand on GSI1 unique-lookup (e.g. EMAIL#<email>)
    //   - by user_id      -> QueryCommand on GSI2 user-index    (e.g. USER#<id>)
    //   - non-indexed     -> ScanCommand with filter, logged warning if hit in prod
    //   - findMany paging -> LastEvaluatedKey
  },
});
```

Builds on Better Auth's `createAdapterFactory` so schema mapping, ID generation, JSON / date / boolean conversion, and key mapping are handled by the framework.

### Adapter compliance test suite

`frontend/lib/auth-dynamodb-adapter.test.ts`:

```ts
import { testAdapter, createTestSuite } from "@better-auth/test-utils";
import { dynamoAdapter } from "./auth-dynamodb-adapter";

createTestSuite(testAdapter, {
  adapter: dynamoAdapter({ table: process.env.BETTER_AUTH_TEST_TABLE ?? "BetterAuth-test" }),
  // The test table lives in real AWS (created once via create-ddb-tables.sh with table name override).
  // Tests insert and clean up their own data; do not point at the dev or prod table.
});
```

Runs the official Better Auth adapter compliance suite against a dedicated `BetterAuth-test` table in the same AWS account. Every operation must pass before the adapter is considered shippable. Local CI without AWS creds is out of scope for v1; this matches the existing pattern (Postgres tests need a running DB, per `feedback_test_db.md`).

### Frontend wiring

- [ ] Install: `npm install better-auth @aws-sdk/client-dynamodb @aws-sdk/lib-dynamodb @aws-sdk/client-sqs pg @types/pg` (the AWS SDKs power the adapter and the magic-link SQS enqueue; `pg` is for `entitlements.ts` only, not auth).
- [ ] Dev install: `npm install -D @better-auth/test-utils vitest`.
- [ ] `frontend/lib/auth.ts` (server-side config):

  ```ts
  import { betterAuth } from "better-auth";
  import { magicLink } from "better-auth/plugins";
  import { dynamoAdapter } from "./auth-dynamodb-adapter";
  import { SQSClient, SendMessageCommand } from "@aws-sdk/client-sqs";

  const sqs = new SQSClient({});

  export const auth = betterAuth({
    database: dynamoAdapter({ table: process.env.BETTER_AUTH_TABLE! }),
    secret: process.env.BETTER_AUTH_SECRET!,
    baseURL: process.env.NEXT_PUBLIC_BASE_URL ?? "http://localhost:3000",
    socialProviders: {
      google: {
        clientId: process.env.GOOGLE_CLIENT_ID!,
        clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
      },
    },
    plugins: [
      magicLink({
        sendMagicLink: async ({ email, url }) => {
          await sqs.send(new SendMessageCommand({
            QueueUrl: process.env.EMAIL_QUEUE_URL!,
            MessageBody: JSON.stringify({ message_type: "magic_link", version: 1, email, url }),
          }));
        },
      }),
    ],
    emailAndPassword: { enabled: false },
  });
  ```

- [ ] `frontend/lib/auth-client.ts` (client-side):

  ```ts
  import { createAuthClient } from "better-auth/react";

  export const authClient = createAuthClient({
    baseURL: process.env.NEXT_PUBLIC_BASE_URL ?? "http://localhost:3000",
  });

  export const { useSession, signIn, signOut } = authClient;
  ```

- [ ] `frontend/app/api/auth/[...all]/route.ts`:

  ```ts
  import { auth } from "@/lib/auth";
  import { toNextJsHandler } from "better-auth/next-js";

  export const { GET, POST } = toNextJsHandler(auth);
  ```

- [ ] **Header sign-in/out.** The existing nav is `frontend/components/layout/Navbar.tsx` (no `Header.tsx` exists). Extend `Navbar.tsx`: when `useSession()` returns a session, render a small avatar + dropdown with "Account" and "Sign out". When no session, render a "Sign in" button that routes to `/sign-in`.
- [ ] `frontend/app/sign-in/page.tsx`: a small page with two CTAs:
  1. "Continue with Google" calls `signIn.social({ provider: "google" })`.
  2. Email field + "Send me a sign-in link" calls `signIn.magicLink({ email })`.
  Reads `?redirect=` from the URL and passes it through. Match SteamPulse design tokens.
- [ ] `frontend/app/account/page.tsx`: a profile page showing email, connected accounts, and a "Sign out" button. Server component that calls `auth.api.getSession({ headers })`; sign-out is a small client island.

### Magic-link email integration with the existing email Lambda

- [ ] `frontend/lib/auth.ts`'s `sendMagicLink` callback enqueues to the existing email queue via `@aws-sdk/client-sqs` (see code above).
- [ ] Add `"magic_link"` to the `SqsMessageType` literal in `src/library-layer/library_layer/events.py` and add a new message class:

  ```python
  class MagicLinkMessage(BaseSqsMessage):
      message_type: SqsMessageType = "magic_link"
      email: str
      url: str
  ```

- [ ] Add a `case "magic_link":` branch in `src/lambda-functions/lambda_functions/email/handler.py` calling a new `_handle_magic_link(email, url)` helper. Body is short HTML containing the URL with a 15-minute expiry note. Reuse `_FROM_ADDR`, `_REPLY_TO`, and the existing `_sender`.
- [ ] No new Resend setup; the integration reuses the existing wiring.

### Server-side auth helper for genre page render-mode decision

`frontend/lib/entitlements.ts` (new). Uses `pg` against `DATABASE_URL` to query `subscriptions` and `report_purchases`. Wraps queries in try/catch so missing-table errors return `false` (defensive guard removable once `stripe-resend-setup.md` lands).

In `frontend/app/genre/[slug]/page.tsx`:

```ts
import { auth } from "@/lib/auth";
import { headers } from "next/headers";
import { checkEntitlement } from "@/lib/entitlements";

export default async function GenrePage({ params }: Props) {
  const session = await auth.api.getSession({ headers: await headers() });
  const userId = session?.user?.id ?? null;
  const isPaid = userId ? await checkEntitlement(userId, slug) : false;
  // render free or paid mode
}
```

### Buy block flow

`frontend/components/genre/ReportBuyBlock.tsx` already POSTs to `/api/checkout/start` (route owned by `stripe-resend-setup.md`). Extend its click handler: if `useSession()` is empty, push to `/sign-in?redirect=/genre/${slug}#buy` first; otherwise keep the existing POST.

### Stripe webhook

The webhook handler reads `metadata.user_id` from Stripe events and inserts the entitlement row keyed on the Better Auth `users.id` (DynamoDB-issued UUID, treated as a string foreign key in Postgres). No Better Auth API call required during webhook processing. Schema and webhook details: `scripts/prompts/stripe-resend-setup.md`.

## Environment + deployment

- [ ] **Local dev:** `frontend/.env.local` carries all values. `start-local.sh` boots Postgres only; `create-ddb-tables.sh` provisions the dev DynamoDB table once.
- [ ] **Production:** keys in SSM under `/steampulse/production/auth/...`. Frontend Lambda joins the existing VPC (so `entitlements.ts` can reach RDS) and gets `DATABASE_URL` injected like the API Lambda does.
- [ ] **DynamoDB table:** created via CDK alongside the existing OpenNext cache table; frontend Lambda role granted read/write on the table and both GSIs.
- [ ] **Magic-link SQS:** `EMAIL_QUEUE_URL` env var on the frontend Lambda; `email_queue.grant_send_messages(frontend_fn)` in CDK.
- [ ] **Google Cloud Console:** allowed redirect URIs include both `https://steampulse.io/api/auth/callback/google` and `http://localhost:3000/api/auth/callback/google`.

## Verification

- [ ] `npm run build` passes with Better Auth wired.
- [ ] `npm run test` passes the adapter compliance suite against the `BetterAuth-test` table in real AWS.
- [ ] `aws dynamodb describe-table --table-name BetterAuth-dev --query 'Table.TableStatus'` returns `ACTIVE`.
- [ ] Visit `/` unauthenticated; "Sign in" visible in the nav.
- [ ] Click sign in; complete Google OAuth flow; redirected back; signed-in state visible (avatar in nav).
- [ ] Sign out; back to unauthenticated state.
- [ ] Repeat with magic link: enter email on `/sign-in`, receive email via Resend, click the link, land authenticated.
- [ ] Visit `/account`; profile page renders email + connected accounts + sign-out button.
- [ ] Visit `/genre/roguelike-deckbuilder/` while authenticated but with no entitlement row in the DB; renders free mode (correct).
- [ ] After `stripe-resend-setup.md` lands and `subscriptions` exists, insert a manual row with `user_id` matching your test user, `status = 'active'`, `current_period_end` in the future; reload `/genre/roguelike-deckbuilder/`; renders paid mode.
- [ ] Click Subscribe / Buy when unauthenticated; redirected to `/sign-in?redirect=...`; after auth, returned to `/genre/[slug]/`; click again, Stripe Checkout opens with `metadata.user_id` populated.

## What this prompt does not decide

- Stripe Product / Price configuration: `scripts/prompts/stripe-resend-setup.md`.
- Stripe webhook handler implementation: `scripts/prompts/stripe-resend-setup.md`.
- `/api/checkout/start` implementation: `scripts/prompts/stripe-resend-setup.md`.
- Per-game preview frontend wiring of `auth.api.getSession()`: launch-plan Step 4 consumes the same helper for showcase / canonical / preview decisions.
- Whether to enable additional Better Auth plugins (passkeys, 2FA, organisation): deferred. Magic link + Google OAuth covers the launch buyer audience.

## Failure modes to handle explicitly

- **User changes email.** Better Auth's email-update flow re-verifies. The `users.id` (DynamoDB-issued UUID, treated as a string) does not change, so entitlements survive.
- **OAuth account already linked to a different email.** Better Auth's default behaviour is to refuse the link; the user has to sign in with their original method first, then add the OAuth account in `/account`. Document this in the sign-in page copy if it surprises buyers.
- **Magic link expired or reused.** Better Auth's `verifications` table tracks single-use; expired or used tokens fail with a clear error. Sign-in page handles the error and prompts a fresh request.
- **Session theft.** Better Auth supports immediate session revocation (logout invalidates the session item), unlike pure stateless JWT. v1 inherits this for free; the `user-index` GSI makes "revoke all sessions for this user" a single query.
- **DynamoDB throttling.** On-demand billing scales without provisioned-capacity throttling. If the adapter ever does a `Scan` (it should not in steady state), a runtime warning is logged so we catch the regression.
