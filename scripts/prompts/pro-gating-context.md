# Pro/Free Gating — React Context Architecture

## Background

Pro features are currently gated by `const isPro = true; // TODO: wire to auth`
hardcoded in `GameReportClient.tsx:89`. Every new page would repeat this constant,
and if the source ever changes (env var → cookie → JWT claim), every file changes.

This spec replaces the hardcoded constant with a React Context that gives all
components a single, consistent source of truth for `isPro`, with a clear migration
path when real payment is wired up.

---

## Current state (do not leave in place)

```typescript
// frontend/app/games/[appid]/[slug]/GameReportClient.tsx:89
const isPro = true; // TODO: wire to auth
```

Components that accept `isPro` as a prop today:
- `PlaytimeChart.tsx` — blurs insight text when `!isPro`
- `CompetitiveBenchmark.tsx` — blurs percentile bars when `!isPro`

Both already implement the correct blur + CTA overlay pattern. They just need to
consume from context instead of receiving a prop from above.

---

## What to build

### 1. `frontend/lib/pro.tsx` — context, provider, and hook

```typescript
"use client";

import { createContext, useContext } from "react";

const ProContext = createContext<boolean>(false);

export function ProProvider({
  isPro,
  children,
}: {
  isPro: boolean;
  children: React.ReactNode;
}) {
  return <ProContext.Provider value={isPro}>{children}</ProContext.Provider>;
}

export function usePro(): boolean {
  return useContext(ProContext);
}
```

Three exports only: `ProContext`, `ProProvider`, `usePro`. No other logic here.

### 2. `frontend/app/layout.tsx` — mount the provider

The root layout is a server component. Read `isPro` from the env var at render
time and pass it into `ProProvider`:

```typescript
import { ProProvider } from "@/lib/pro";

// Inside the layout component:
const isPro = process.env.NEXT_PUBLIC_PRO_ENABLED === "true";

return (
  <html lang="en">
    <body>
      <ProProvider isPro={isPro}>
        {children}
      </ProProvider>
    </body>
  </html>
);
```

`ProProvider` is a client component wrapping server-rendered children — this is
the standard Next.js pattern for mixing server and client components at the root.

### 3. `frontend/.env.local` — local dev flag

Add one line:

```
NEXT_PUBLIC_PRO_ENABLED=true
```

This enables all pro features in local development. `.env.local` is gitignored —
it is never committed.

Check whether `.env.local` already exists before creating it; if it does, append
the line rather than overwriting.

**Staging:** Set `NEXT_PUBLIC_PRO_ENABLED=true` in the staging environment
(CDK frontend stack env or wherever Next.js env vars are configured for staging).

**Production:** `NEXT_PUBLIC_PRO_ENABLED=false` (or omit it — the default is `false`).

### 4. Remove all `isPro` prop drilling

#### `GameReportClient.tsx`

Remove the module-level `const isPro = true; // TODO: wire to auth` and add
`const isPro = usePro()` as the **first line inside the component function body**
(after the props destructuring, before any `useState` calls):

```typescript
export function GameReportClient({ ...props }: GameReportClientProps) {
  const isPro = usePro(); // ← first line inside the function
  const [reviewStats, setReviewStats] = useState<ReviewStats | null>(null);
  ...
}
```

Add the import: `import { usePro } from "@/lib/pro";`

The existing `isPro` usages in the file (passed to `PlaytimeChart`, `CompetitiveBenchmark`)
do NOT need to change — they still receive it as a prop. Only the source changes.

**Important:** `usePro()` must be called inside a component function body, not at
module level. The original `const isPro = true` was a module-level constant (valid),
but hooks cannot be called at module level.

#### `PlaytimeChart.tsx` and `CompetitiveBenchmark.tsx`

These components will continue to accept `isPro?: boolean` as a prop. Do NOT
change them to consume context directly — accepting a prop keeps them testable in
isolation (Playwright tests can render them with any `isPro` value without
needing to wrap in a provider).

The prop-vs-context boundary is: **pages/clients consume context, leaf
components accept props**. This is the standard pattern.

---

## Migration path to real auth (Phase 2)

Auth provider is TBD — Cognito, Auth0, and Okta are all viable. The `ProContext`
architecture is provider-agnostic and requires **zero changes** regardless of which
is chosen.

### Where pro status lives in the auth provider

Use a **group or role** named `"pro"`, not a custom user attribute:
- Groups surface automatically as a JWT claim (`cognito:groups`, `roles`, etc.)
- Easier to manage operationally: add/remove a user from the group via admin API
  or console when they pay or churn — no schema changes, no token mapping config
- Custom attributes require schema definitions upfront and explicit JWT claim
  mapping — more friction for the same result

### The only change: `layout.tsx`

Replace the env-var read with a session lookup from whichever auth library is
chosen. The pattern is identical across providers:

```typescript
// Provider-agnostic pseudocode
const session = await getSession(); // Amplify, Auth0 SDK, next-auth, etc.
const isPro = session?.user?.groups?.includes("pro") ?? false;
// ProProvider receives the same boolean — nothing else changes
```

Specific implementations by provider:
- **Cognito + Amplify v6:** `fetchAuthSession()` server-side, read `idToken.payload["cognito:groups"]`
- **Auth0:** `getSession()` from `@auth0/nextjs-auth0`, read `session.user["https://.../roles"]`
- **Okta / next-auth:** `getServerSession()`, map groups through the JWT callback

In every case: one isolated change in `layout.tsx`. `ProContext`, `ProProvider`,
and `usePro()` are untouched.

### AuthProvider is separate from ProProvider

Auth also requires an `AuthProvider` component wrapping the app (Amplify's
Authenticator, Auth0's UserProvider, next-auth's SessionProvider). This is
**a separate concern** — it handles login UI, session management, and token
refresh. `ProProvider` sits alongside it, receiving only the `isPro` boolean
that `layout.tsx` derives from the session. Do not conflate the two.

The full layout structure at Phase 2:

```tsx
<AuthProvider>          {/* handles login/session — provider-specific */}
  <ProProvider isPro={isPro}>  {/* handles feature gating — never changes */}
    {children}
  </ProProvider>
</AuthProvider>
```

Specific auth implementation is deferred until the provider is chosen.

---

## Rules for future components

Any new client component that needs to gate pro features:

```typescript
import { usePro } from "@/lib/pro";

// Inside the component:
const isPro = usePro();
```

Any new page or client container that renders pro-aware leaf components should
pass `isPro` down as a prop (not make leaf components import context directly).

Do NOT:
- Read `NEXT_PUBLIC_PRO_ENABLED` directly in any component (only in `layout.tsx`)
- Add `isPro` as a prop to page components — context exists for this
- Create multiple context providers for different pages

---

## Testing

**`isPro = true` path (default in dev/staging):**
- All existing E2E tests continue passing (they already test with `isPro = true`)
- No changes to `frontend/tests/` needed for the happy path

**`isPro = false` path:**
- Existing tests that verify blur/CTA behavior check for `.blur-sm` class and
  the "Upgrade to Pro" link — these tests already work via `isPro = false` prop
- For Playwright tests that need to test free-tier behavior: render the component
  with `isPro={false}` as a prop (leaf components still accept the prop)
- Do NOT require `ProProvider` in tests — test components directly with props

---

## Files to create / modify

| File | Action |
|------|--------|
| `frontend/lib/pro.tsx` | Create — `ProContext`, `ProProvider`, `usePro` |
| `frontend/app/layout.tsx` | Add `ProProvider` wrapping children, read `NEXT_PUBLIC_PRO_ENABLED` |
| `frontend/.env.local` | Add `NEXT_PUBLIC_PRO_ENABLED=true` (append if file exists) |
| `frontend/app/games/[appid]/[slug]/GameReportClient.tsx` | Replace hardcoded `const isPro = true` with `usePro()` |

`PlaytimeChart.tsx` and `CompetitiveBenchmark.tsx` do **not** change — they keep
their `isPro` prop.
