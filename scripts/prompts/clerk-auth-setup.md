# Clerk auth setup

Wire Clerk as the identity provider for SteamPulse: magic link + Google OAuth + logout + account UI, with Clerk's `user_id` becoming the identity column on `subscriptions` and `report_purchases`. This prompt is the implementation spec for the auth half of launch-plan Step 2 (the Stripe + Resend half is its own scope inside the same step).

The shape this delivers is defined in `scripts/prompts/rdb-launch-spec.md` Section 5. This prompt makes it concrete and actionable.

## Why Clerk

Free tier covers ≥ 10K MAU (far above launch volume). Native Next.js SDK with `<ClerkProvider>`, `<UserButton>`, `<UserProfile />`, `<SignIn />`, `<SignUp />`, server-side `auth()` helper, and `clerkMiddleware()` route guard. Magic-link auth + Google OAuth + logout out of the box; passkeys available behind a flag.

We do not maintain a local `users` table. Clerk's user record is the source of truth for identity (email, display name, auth methods). Our DB stores only entitlements (`subscriptions`, `report_purchases`) keyed on `clerk_user_id` (string).

## Prerequisites

- Clerk account at https://clerk.com. Create a SteamPulse application (Production mode + Development mode).
- In Clerk dashboard: enable email magic link, enable Google OAuth, disable username/password (we are not exposing it).
- Custom domain set up so the Clerk hosted pages live on `accounts.steampulse.io` (or stay on `clerk.steampulse.io`; whichever Clerk routes by default for the production domain).
- Environment variables in SSM (or `.env.local` for dev):
  - `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`
  - `CLERK_SECRET_KEY`
  - `CLERK_WEBHOOK_SIGNING_SECRET` (only if we add a Clerk webhook; v1 may not need)

## Files to create / modify

### Frontend wiring

- [ ] Install: `npm install @clerk/nextjs`
- [ ] `frontend/middleware.ts`: add `clerkMiddleware()` from `@clerk/nextjs/server`. Public routes (home, `/genre/[slug]/`, `/games/[appid]/[slug]/`, `/reports`, robots/sitemap) explicitly listed; everything else defaults to authenticated. Use `createRouteMatcher` per Clerk docs.
- [ ] `frontend/app/layout.tsx`: wrap the root in `<ClerkProvider>`. Pass theme + appearance overrides to match the SteamPulse design tokens (background, foreground, accent colors).
- [ ] Header component (find the existing nav; likely `frontend/components/layout/Header.tsx` or similar): add `<SignedIn><UserButton /></SignedIn>` and `<SignedOut><SignInButton mode="modal" /></SignedOut>` to the right side of the navigation. The SignedOut button copy: "Sign in".
- [ ] `frontend/app/account/[[...rest]]/page.tsx`: Clerk's `<UserProfile />` mounted as a catch-all route. This handles email management, connected accounts, password (if ever enabled), passkeys (if ever enabled).
- [ ] (Optional, defer if not needed): `frontend/app/sign-in/[[...rest]]/page.tsx` and `frontend/app/sign-up/[[...rest]]/page.tsx` mounting `<SignIn />` and `<SignUp />` if we want full pages instead of modals. v1 ships modal-only.

### Server-side auth helper for genre page render-mode decision

- [ ] In `frontend/app/genre/[slug]/page.tsx`, replace any custom cookie reading with `auth()` from `@clerk/nextjs/server`:

```ts
import { auth } from '@clerk/nextjs/server';

export default async function GenrePage({ params }: Props) {
  const { userId } = await auth();
  // ...
  const isPaid = userId
    ? await checkEntitlement(userId, slug)  // queries subscriptions + report_purchases
    : false;
  // render free or paid mode based on isPaid
}
```

- [ ] `checkEntitlement(clerkUserId, reportSlug)` lives in `frontend/lib/entitlements.ts` (new file). It runs the two SQL queries from spec Section 5: subscription check (any active row for this user) OR report_purchases check (matching slug, access_until > now()).

### Buy block flow

- [ ] `frontend/components/genre/ReportBuyBlock.tsx`: when the user clicks Subscribe or Buy, check `useUser()` from `@clerk/nextjs`. If signed in, post to `/api/checkout/start` (which uses server-side `auth()` to read userId, creates Stripe Checkout Session with `metadata.clerk_user_id`). If not signed in, open the Clerk `<SignIn />` modal first; on successful sign-in, automatically resume the checkout request.

### Stripe webhook (the Stripe half of Step 2)

- [ ] Webhook handler reads `metadata.clerk_user_id` from the Stripe event and inserts the entitlement row. No Clerk API call required during webhook processing.
- [ ] If `metadata.clerk_user_id` is absent (defensive): log error, do NOT silently insert. Stripe Checkout always carries the metadata if `/api/checkout/start` set it correctly.

### Optional: Clerk webhook (skip for v1)

We do not need a Clerk webhook for v1. Clerk fires `user.created` etc. but we don't have anything to do on those events: identity lives in Clerk, entitlements are written by Stripe webhooks. Add a Clerk webhook only if we later want a local cache table (`clerk_user_cache`) for query/reporting purposes; leave that for Tier-2.

## Environment + deployment

- [ ] Local dev: `.env.local` carries dev keys (`pk_test_...`, `sk_test_...`).
- [ ] Production: keys stored in AWS SSM Parameter Store under `/steampulse/prod/clerk/publishable_key` and `/clerk/secret_key`. CDK synth wires them into the Lambda + Next.js environment.
- [ ] Clerk dashboard: configure allowed redirect URIs to include `https://steampulse.io/*` and `http://localhost:3000/*`. Set the post-sign-in / post-sign-up redirect to `/`.

## Verification

- [ ] `npm run build` passes locally with Clerk wired.
- [ ] Visit `/` unauthenticated; "Sign in" button visible in header.
- [ ] Click sign in, complete magic-link flow with a test email; redirected back; `<UserButton>` now visible.
- [ ] Click `<UserButton>` and choose "Sign out"; back to unauthenticated state.
- [ ] Repeat with Google OAuth; verify the same.
- [ ] Visit `/account`; the Clerk `<UserProfile />` renders.
- [ ] Visit `/genre/roguelike-deckbuilder/` while authenticated but with no entitlement row in the DB; renders free mode (correct).
- [ ] Insert a manual `subscriptions` row with `clerk_user_id` matching your test user, `status = 'active'`, `current_period_end` in the future; reload `/genre/roguelike-deckbuilder/`; renders paid mode.
- [ ] Click Subscribe / Buy when unauthenticated; sign-in modal opens; after auth, Stripe Checkout opens with `metadata.clerk_user_id` populated.

## What this prompt does not decide

- Stripe Product / Price configuration: in launch-plan Step 2 (Stripe half), values pinned by `rdb-launch-spec.md` Section 4.
- Stripe webhook handler implementation details: launch-plan Step 2 (Stripe half).
- Resend transactional template content: launch-plan Step 2 (Resend half).
- Per-game preview frontend wiring of `auth()`: launch-plan Step 4 (per-game preview frontend) consumes the same `auth()` helper for showcase / canonical / preview decisions.

## Migration off Clerk (only if it ever happens)

If we ever leave Clerk: the entitlement schema does not change. The migration is a one-time script that exports Clerk users (Clerk has a JSON export endpoint), creates equivalent records in the new provider (Auth0, Supabase, custom), maps old `clerk_user_id` strings to new ids in `subscriptions` and `report_purchases` via an `UPDATE ... SET clerk_user_id = new_id WHERE clerk_user_id = old_id` per row, and updates application code to read the new auth helper. Estimated effort: one focused day. Treat this as the safety valve, not a near-term plan.
