# Auth0 Authentication — SteamPulse

## Background

SteamPulse has no authentication system. Users are anonymous. Pro features are
gated by a `NEXT_PUBLIC_PRO_ENABLED` env var read in `layout.tsx` and served via
`ProProvider` / `usePro()` (see `frontend/lib/pro.tsx`). This was designed as
Phase 1 of a two-phase approach — Phase 2 replaces the env var with a real
session lookup. This prompt implements Phase 2 using Auth0.

**Why Auth0:** Best DX for consumer-facing apps. First-party Next.js SDK
(`@auth0/nextjs-auth0`). Universal Login handles sign-up/login UI, MFA, and
social connections out of the box. Auth0 is now part of Okta (branded "Okta
Customer Identity Cloud") but the SDK and docs remain under the Auth0 name.

**Prerequisite:** `pro-gating-context.md` must be implemented first (it already is).

---

## Current state (do not leave in place)

- `frontend/lib/pro.tsx` — `ProContext`, `ProProvider`, `usePro()` ✅ (implemented)
- `frontend/app/layout.tsx` — `ProProvider` mounted, reads `NEXT_PUBLIC_PRO_ENABLED`
- `frontend/middleware.ts` — does not exist
- `frontend/package.json` — no auth dependencies
- `frontend/lib/types.ts` — no user/session types
- `frontend/components/layout/Navbar.tsx` — no login/logout UI
- `infra/stacks/frontend_stack.py` — no auth env vars
- `src/lambda-functions/lambda_functions/api/handler.py` — no JWT validation

---

## Auth0 tenant setup (manual — not code)

These steps are performed in the Auth0 Dashboard before any code changes. Document
them here so the implementer knows what to configure.

### 1. Create tenant

- Tenant name: `steampulse` (or `steampulse-dev` for development)
- Region: US

### 2. Create application

- Type: **Regular Web Application** (server-side Next.js needs this, not SPA)
- Name: `SteamPulse`
- Allowed Callback URLs:
  - `http://localhost:3000/api/auth/callback` (dev)
  - `https://steampulse.io/api/auth/callback` (production)
  - Staging CloudFront URL `/api/auth/callback`
- Allowed Logout URLs:
  - `http://localhost:3000` (dev)
  - `https://steampulse.io` (production)
  - Staging CloudFront URL
- Allowed Web Origins: same as logout URLs
- Note the **Domain**, **Client ID**, and **Client Secret** — needed for env vars

### 3. Enable connections

- **Database** — `Username-Password-Authentication` (Auth0's default database
  connection). This is the primary sign-up method. Users create an account with
  email + password directly on SteamPulse. Enabled by default on new tenants.
- **Google** — enable under Social connections. Requires Google OAuth credentials
  (Client ID + Secret from Google Cloud Console).
- **Steam** — deferred. Steam uses OpenID 2.0, not OIDC. Requires a custom
  Auth0 social connection with a Node.js script. Implement later as a follow-up.

### 4. Create API (for backend JWT validation)

- Name: `SteamPulse API`
- Identifier (audience): `https://api.steampulse.io` (convention — does not need
  to be a real URL)
- Signing Algorithm: RS256

### 5. Create "pro" role

- Go to User Management → Roles → Create Role
- Name: `pro`
- This role is assigned to users who have paid for Pro access

### 6. Add Login/Post-Login Action to include roles in ID token

Auth0 does not include roles in the ID token by default. Create a custom Action:

- Go to Actions → Flows → Login → Add Action → Build Custom
- Name: `Add roles to tokens`

```javascript
exports.onExecutePostLogin = async (event, api) => {
  const namespace = "https://steampulse.io";
  const roles = event.authorization?.roles || [];
  api.idToken.setCustomClaim(`${namespace}/roles`, roles);
  api.accessToken.setCustomClaim(`${namespace}/roles`, roles);
};
```

The namespace prefix is required by Auth0 — custom claims must use a URL namespace
to avoid collision with standard OIDC claims.

---

## What to build

### 1. Install `@auth0/nextjs-auth0`

```bash
cd frontend && npm install @auth0/nextjs-auth0
```

This is the only new dependency. It handles:
- Server-side session management (encrypted cookie)
- Route handlers for `/api/auth/login`, `/api/auth/callback`, `/api/auth/logout`
- `getSession()` for server components
- `useUser()` for client components
- `withMiddlewareAuthRequired()` for optional middleware

### 2. `frontend/.env.local` — Auth0 config

Add these variables (values come from Auth0 Dashboard):

```
AUTH0_SECRET=<random 32+ char string — run `openssl rand -hex 32`>
AUTH0_BASE_URL=http://localhost:3000
AUTH0_ISSUER_BASE_URL=https://steampulse.us.auth0.com
AUTH0_CLIENT_ID=<from Auth0 Dashboard>
AUTH0_CLIENT_SECRET=<from Auth0 Dashboard>
AUTH0_AUDIENCE=https://api.steampulse.io
```

`.env.local` is gitignored. For staging/production, set these as environment
variables in the CDK frontend stack (see section 8).

**Remove** `NEXT_PUBLIC_PRO_ENABLED` from `.env.local` — it is no longer needed.
The env var fallback in `layout.tsx` handles the case where Auth0 is not configured
(see section 4).

### 3. `frontend/app/api/auth/[auth0]/route.ts` — Auth0 route handler

```typescript
import { handleAuth } from "@auth0/nextjs-auth0";

export const GET = handleAuth();
```

This single file creates four routes automatically:
- `GET /api/auth/login` — redirects to Auth0 Universal Login
- `GET /api/auth/callback` — handles the OAuth callback
- `GET /api/auth/logout` — clears session and redirects to Auth0 logout
- `GET /api/auth/me` — returns the current user profile (JSON)

No other auth route files are needed.

### 4. `frontend/app/layout.tsx` — add `UserProvider`, update `isPro` source

```typescript
import { UserProvider } from "@auth0/nextjs-auth0/client";
import { getSession } from "@auth0/nextjs-auth0";
import { ProProvider } from "@/lib/pro";

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const session = await getSession();
  const roles: string[] =
    session?.user?.["https://steampulse.io/roles"] ?? [];
  const isPro = roles.includes("pro");

  return (
    <html lang="en" className={`${playfair.variable} ${syne.variable} ${jetbrains.variable}`}>
      <body className="antialiased min-h-screen bg-background text-foreground">
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(websiteJsonLd) }}
        />
        <UserProvider>
          <ProProvider isPro={isPro}>
            <Navbar />
            {children}
          </ProProvider>
        </UserProvider>
      </body>
    </html>
  );
}
```

Key changes from the current `layout.tsx`:
1. Function becomes `async` (needed for `getSession()`)
2. `UserProvider` wraps everything — provides `useUser()` hook to client components
3. `isPro` now reads from the Auth0 session's custom roles claim
4. `ProProvider` is unchanged — it still receives a boolean

**`ProContext`, `ProProvider`, and `usePro()` do not change at all.** Only the
source of the `isPro` boolean changes, exactly as designed in `pro-gating-context.md`.

**Fallback when Auth0 is not configured:** If `getSession()` returns `null` (no
Auth0 env vars, or user not logged in), `roles` defaults to `[]` and `isPro` is
`false`. Anonymous users always see the free tier. This is correct — no env var
fallback needed.

### 5. `frontend/middleware.ts` — optional session attachment

```typescript
import { withMiddlewareAuthRequired } from "@auth0/nextjs-auth0/edge";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export default function middleware(request: NextRequest) {
  // Do not protect any routes — all pages are publicly accessible.
  // Auth0 session cookie is attached automatically by the SDK when present.
  return NextResponse.next();
}

export const config = {
  matcher: [
    // Skip static files, _next internals, and auth routes
    "/((?!_next/static|_next/image|favicon.ico|api/auth).*)",
  ],
};
```

**Important:** SteamPulse is a public SEO-driven site. No route should require
authentication. The middleware exists only to define the matcher — the Auth0 SDK
handles session cookie management automatically. Do NOT use
`withMiddlewareAuthRequired` on any route.

If middleware is not needed for session attachment (the SDK handles it via the
route handler), skip this file entirely. Test without it first.

### 6. `frontend/components/layout/Navbar.tsx` — login/logout/sign-up UI

Add auth controls to the Navbar. The `useUser()` hook from Auth0 provides the
current user in client components.

```typescript
"use client";

import { useUser } from "@auth0/nextjs-auth0/client";
// ... existing imports ...

export function Navbar() {
  const { user, isLoading } = useUser();
  // ... existing state ...

  return (
    <nav ...>
      <div className="max-w-6xl mx-auto px-4 h-14 flex items-center gap-4">
        {/* ... existing logo, nav links, search ... */}

        {/* Auth controls — desktop */}
        <div className="hidden md:flex items-center gap-2 flex-shrink-0">
          {!isLoading && !user && (
            <>
              <a
                href="/api/auth/login"
                className="text-sm font-mono tracking-widest text-muted-foreground hover:text-foreground transition-colors"
              >
                Log In
              </a>
              <a
                href="/api/auth/login?screen_hint=signup"
                className="text-sm font-mono tracking-widest px-3 py-1 rounded"
                style={{ background: "var(--teal)", color: "var(--background)" }}
              >
                Sign Up
              </a>
            </>
          )}
          {!isLoading && user && (
            <div className="flex items-center gap-2">
              {user.picture && (
                <img
                  src={user.picture}
                  alt=""
                  className="w-6 h-6 rounded-full"
                />
              )}
              <span className="text-sm text-muted-foreground">
                {user.name || user.email}
              </span>
              <a
                href="/api/auth/logout"
                className="text-sm font-mono tracking-widest text-muted-foreground hover:text-foreground transition-colors"
              >
                Log Out
              </a>
            </div>
          )}
        </div>
      </div>

      {/* Mobile menu — add auth controls at bottom */}
      {mobileMenuOpen && (
        <div ...>
          {/* ... existing mobile links ... */}
          <div className="border-t pt-2" style={{ borderColor: "var(--border)" }}>
            {!isLoading && !user && (
              <div className="space-y-1">
                <a href="/api/auth/login" className="block py-2 text-base text-foreground/70">Log In</a>
                <a href="/api/auth/login?screen_hint=signup" className="block py-2 text-base" style={{ color: "var(--teal)" }}>Sign Up</a>
              </div>
            )}
            {!isLoading && user && (
              <div className="space-y-1">
                <span className="block py-2 text-sm text-muted-foreground">{user.email}</span>
                <a href="/api/auth/logout" className="block py-2 text-base text-foreground/70">Log Out</a>
              </div>
            )}
          </div>
        </div>
      )}
    </nav>
  );
}
```

Notes:
- `screen_hint=signup` tells Auth0 Universal Login to show the sign-up tab instead
  of the login tab. Works with Auth0's New Universal Login experience.
- Use `<a href>` for Auth0 routes, not `<Link>` — these are API routes that
  perform redirects, not client-side navigations.
- "For Developers →" link to `/pro` is unchanged.
- Show nothing while `isLoading` to avoid layout shift.

### 7. Backend JWT validation (FastAPI)

Protected API endpoints (future pro-only endpoints) need to validate the Auth0
JWT. This does NOT apply to existing public endpoints like `/api/games/{appid}/report`.

#### `src/library-layer/library_layer/utils/auth.py`

```python
from functools import lru_cache

import httpx
import jwt  # PyJWT
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, Request

AUTH0_DOMAIN = ""       # Set from config
AUTH0_AUDIENCE = ""     # Set from config
AUTH0_ALGORITHMS = ["RS256"]


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    return PyJWKClient(f"https://{AUTH0_DOMAIN}/.well-known/jwks.json")


def get_token_from_header(request: Request) -> str | None:
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    return auth[7:]


def verify_token(token: str) -> dict:
    signing_key = _jwks_client().get_signing_key_from_jwt(token)
    payload = jwt.decode(
        token,
        signing_key.key,
        algorithms=AUTH0_ALGORITHMS,
        audience=AUTH0_AUDIENCE,
        issuer=f"https://{AUTH0_DOMAIN}/",
    )
    return payload


def get_current_user(request: Request) -> dict | None:
    """FastAPI dependency — returns decoded JWT payload or None for anonymous."""
    token = get_token_from_header(request)
    if token is None:
        return None
    try:
        return verify_token(token)
    except jwt.PyJWTError:
        return None


def require_auth(request: Request) -> dict:
    """FastAPI dependency — returns decoded JWT or raises 401."""
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_pro(request: Request) -> dict:
    """FastAPI dependency — returns decoded JWT with pro role or raises 403."""
    user = require_auth(request)
    roles = user.get("https://steampulse.io/roles", [])
    if "pro" not in roles:
        raise HTTPException(status_code=403, detail="Pro subscription required")
    return user
```

Usage in API handler:

```python
from library_layer.utils.auth import get_current_user, require_pro

@app.get("/api/some-pro-endpoint")
async def some_pro_endpoint(user: dict = Depends(require_pro)):
    # user is guaranteed to have the "pro" role
    ...

@app.get("/api/some-public-endpoint")
async def some_public_endpoint(user: dict | None = Depends(get_current_user)):
    # user is None for anonymous, dict for authenticated
    ...
```

**Important:** Existing public endpoints (`/api/games/*`, `/api/genres`, `/api/tags/*`,
etc.) do NOT require authentication. Do not add auth dependencies to them. Only
future pro-only endpoints use `require_pro`.

#### Dependencies

Add `PyJWT[crypto]` to `src/library-layer/pyproject.toml`:

```toml
[tool.poetry.dependencies]
PyJWT = {version = "^2.8", extras = ["crypto"]}
```

Then regenerate the lock file: `cd src/library-layer && poetry lock && cd ../..`

The `[crypto]` extra installs `cryptography` for RS256 key validation.

### 8. CDK changes — environment variables

#### `infra/stacks/frontend_stack.py`

The frontend Lambda needs Auth0 env vars for server-side session management:

```python
# These values come from Secrets Manager or SSM
AUTH0_SECRET_PARAM_NAME    # /steampulse/{env}/auth0/secret
AUTH0_CLIENT_SECRET_PARAM_NAME  # /steampulse/{env}/auth0/client-secret
```

Auth0 configuration env vars for the frontend Lambda:

```
AUTH0_SECRET           — session encryption key (from Secrets Manager)
AUTH0_BASE_URL         — https://steampulse.io (production) or CloudFront URL (staging)
AUTH0_ISSUER_BASE_URL  — https://steampulse.us.auth0.com
AUTH0_CLIENT_ID        — from Auth0 Dashboard (not secret, but env-specific)
AUTH0_CLIENT_SECRET    — from Secrets Manager
AUTH0_AUDIENCE         — https://api.steampulse.io
```

Store `AUTH0_SECRET` and `AUTH0_CLIENT_SECRET` in AWS Secrets Manager:
- `steampulse/{env}/auth0/secret`
- `steampulse/{env}/auth0/client-secret`

Store `AUTH0_ISSUER_BASE_URL`, `AUTH0_CLIENT_ID`, and `AUTH0_AUDIENCE` in SSM
Parameter Store (not secret — safe as plaintext params):
- `/steampulse/{env}/auth0/issuer-base-url`
- `/steampulse/{env}/auth0/client-id`
- `/steampulse/{env}/auth0/audience`

#### `infra/stacks/compute_stack.py`

The API Lambda needs Auth0 domain and audience for JWT validation:

```
AUTH0_DOMAIN    — steampulse.us.auth0.com (no https://)
AUTH0_AUDIENCE  — https://api.steampulse.io
```

These are read by `library_layer/utils/auth.py` at module level.

### 9. `frontend/lib/types.ts` — user type (optional)

The Auth0 SDK provides its own `UserProfile` type. If SteamPulse needs to extend
it (e.g., display pro badge in UI), add:

```typescript
export interface SteamPulseUser {
  email: string;
  name?: string;
  picture?: string;
  isPro: boolean;
}
```

This is optional — the `useUser()` hook's built-in type may be sufficient. Only
add if custom user shaping is needed.

---

## What does NOT change

- `frontend/lib/pro.tsx` — `ProContext`, `ProProvider`, `usePro()` are permanent
- `frontend/app/games/[appid]/[slug]/GameReportClient.tsx` — still calls `usePro()`
- `PlaytimeChart.tsx`, `CompetitiveBenchmark.tsx` — still accept `isPro` prop
- All existing public API endpoints — no auth required
- `doc/frontend-architecture.md` — pro gating section is already correct for Phase 2

---

## Out of scope

- **`/api/validate-key`** — will be removed separately before this is implemented
- **Steam login** — requires custom Auth0 social connection (OpenID 2.0 wrapper).
  Implement as a follow-up after core Auth0 is working.
- **Payment integration** — how users become "pro" (Stripe, etc.) is a separate
  concern. This prompt assumes the `"pro"` role is assigned manually or via a
  future payment webhook.
- **User profile page** — no `/account` or `/settings` page in this prompt
- **Email verification flow** — Auth0 handles this automatically for database
  connections. Default settings are fine.

---

## Files to create / modify

| File | Action |
|------|--------|
| `frontend/app/api/auth/[auth0]/route.ts` | Create — Auth0 route handler (4 lines) |
| `frontend/app/layout.tsx` | Modify — add `UserProvider`, `getSession()`, read roles |
| `frontend/components/layout/Navbar.tsx` | Modify — add login/logout/sign-up UI |
| `frontend/middleware.ts` | Create — matcher config (may be unnecessary — test without first) |
| `frontend/.env.local` | Modify — add `AUTH0_*` vars, remove `NEXT_PUBLIC_PRO_ENABLED` |
| `src/library-layer/library_layer/utils/auth.py` | Create — JWT validation utilities |
| `src/library-layer/pyproject.toml` | Modify — add `PyJWT[crypto]` |
| `infra/stacks/frontend_stack.py` | Modify — add Auth0 env vars to frontend Lambda |
| `infra/stacks/compute_stack.py` | Modify — add Auth0 domain/audience to API Lambda |

---

## Testing

### Local development

1. Create an Auth0 tenant (free tier) and configure as described above
2. Add Auth0 env vars to `frontend/.env.local`
3. `cd frontend && npm install && npm run dev`
4. Visit `http://localhost:3000` — should see Login/Sign Up in Navbar
5. Click Sign Up → Auth0 Universal Login → create account with email/password
6. After redirect, Navbar should show user name/avatar and Log Out
7. Assign `"pro"` role to user in Auth0 Dashboard → refresh → pro features unlocked
8. Log out → pro features locked (free tier)

### Anonymous users

- All pages load without authentication
- No redirects to login
- Pro features show free-tier (blur + CTA) — same as `NEXT_PUBLIC_PRO_ENABLED=false`

### Playwright E2E

Existing tests do not need Auth0 — they test components directly with `isPro`
prop (leaf components) or can wrap in `ProProvider` with a known value. No Auth0
provider needed in tests.

For testing authenticated flows in E2E:
- Use Auth0's Resource Owner Password Grant (test tenant only) to get tokens
  programmatically in test setup
- Or set session cookie directly in Playwright context
- Detail TBD when E2E auth tests are written

### Backend JWT validation

- Test `verify_token()` with a real Auth0-issued token (from test tenant)
- Test `require_pro()` returns 403 for users without the `"pro"` role
- Test `get_current_user()` returns `None` for missing/invalid tokens

---

## Migration checklist

When implementing, follow this order:

1. Auth0 tenant setup (manual)
2. `npm install @auth0/nextjs-auth0`
3. Create `frontend/app/api/auth/[auth0]/route.ts`
4. Update `frontend/.env.local` with Auth0 vars
5. Update `frontend/app/layout.tsx` (UserProvider + getSession)
6. Update `frontend/components/layout/Navbar.tsx` (login/logout UI)
7. Verify: anonymous access works, sign-up works, login/logout works
8. Add "pro" role to test user in Auth0 Dashboard
9. Verify: pro features unlock for pro user, lock for free user
10. Add `PyJWT[crypto]` to library layer, create `utils/auth.py`
11. Update CDK stacks with Auth0 env vars
12. Remove `NEXT_PUBLIC_PRO_ENABLED` from all environments
