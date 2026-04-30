# Plausible Analytics Integration (Pre-Launch)

## Goal

Wire Plausible Analytics into the Next.js frontend before the `steampulse.io`
domain is cut over in Route53. When DNS flips, analytics is already live —
no day-one tracking gap. Use **proxy mode** so the script is served from our
own domain and isn't blocked by uBlock Origin / Brave / AdGuard (gamer
audience → high adblock penetration).

## Background

- Phase 5 launch task per `scripts/launch-checklist.org` lines 188-193
  (the raw `<script>` snippet there is superseded by this prompt)
- Privacy-friendly, cookieless — no GDPR banner required
- $9/mo (Growth plan)
- Frontend: Next.js 16.1.6 App Router → OpenNext → CloudFront + S3
- No analytics exists today (only JSON-LD structured data in the layout)
- Domain `steampulse.io` is hardcoded across `metadataBase`, JSON-LD,
  `sitemap.ts`, `robots.ts`

## Prerequisites (user-side)

1. Sign up at https://plausible.io and add `steampulse.io` as a site.
2. From the dashboard, copy the **site-specific script URL** — it looks
   like `https://plausible.io/js/pa-XXXXX.js`. Plausible v4 bakes per-site
   feature config (outbound links, file downloads, etc.) into this URL,
   configured in the dashboard rather than as code props.
3. **Skip the dashboard "Verify" step** — it fetches `https://steampulse.io`
   to look for the script, which fails today because DNS isn't cut over yet.
   Verification will succeed automatically once DNS is live and a real
   pageview hits.

## Implementation

Use [`next-plausible`](https://github.com/4lejandrito/next-plausible) v4.
It provides `withPlausibleProxy` for Next.js rewrites and a
`<PlausibleProvider>` that auto-uses the proxied URLs when the proxy is
configured.

### 1. Install

```bash
cd frontend && npm install next-plausible
```

(The frontend uses npm — `package-lock.json` is the lockfile, despite some
docs referencing `bun`.)

### 2. Configure the proxy in `frontend/next.config.ts`

Wrap the existing `nextConfig` export with `withPlausibleProxy`. Pass:
- `src` — the site-specific script URL from the Plausible dashboard.
- `scriptPath` and `apiPath` overriding the defaults (`/js/script.js`,
  `/api/event`) to live under `/stats/*`. This avoids collision with the
  existing FastAPI `/api/*` dev rewrite at `next.config.ts:42-50`.

```ts
import { withPlausibleProxy } from "next-plausible";

// ...existing nextConfig declaration unchanged...

export default withPlausibleProxy({
  src: "https://plausible.io/js/pa-XXXXX.js",
  scriptPath: "/stats/js/script.js",
  apiPath: "/stats/api/event",
})(nextConfig);
```

The wrapper adds Next.js rewrites internally:
- `GET /stats/js/script.js` → fetches upstream `pa-XXXXX.js` and serves it
- `POST /stats/api/event` → forwards to `https://plausible.io/api/event`

### 3. Mount the provider in `frontend/app/layout.tsx`

Gate the provider on `NEXT_PUBLIC_PLAUSIBLE_ENABLED` so it only fires in
the production build — same posture as the `is_production` gate on
EventBridge rules per `feedback_no_staging_schedules`. Without this gate,
a future staging deploy would pollute prod analytics with QA traffic
(Plausible only auto-ignores `localhost`, not `staging.*` subdomains).

```tsx
import PlausibleProvider from "next-plausible";

// ...inside <body>, wrapping the existing tree:
<PlausibleProvider
  enabled={process.env.NEXT_PUBLIC_PLAUSIBLE_ENABLED === "true"}
>
  <NuqsAdapter>
    <Navbar />
    {children}
  </NuqsAdapter>
</PlausibleProvider>
```

The two existing JSON-LD `<script>` tags stay where they are — siblings to
the provider, inside `<body>`.

Outbound-link tracking, file-download tracking, etc. are **not** code
props in v4 — toggle them in the Plausible dashboard and they get baked
into the `pa-XXXXX.js` script automatically.

### 4. Wire the env var in `scripts/deploy.sh`

In Step 1 (frontend build), export the var only for production:

```bash
if [[ "$ENV" == "production" ]]; then
    export NEXT_PUBLIC_PLAUSIBLE_ENABLED=true
fi
npm run build:open-next
```

Result: production builds emit the `<PlausibleProvider>` script chain;
staging and local prod-builds emit nothing — the provider returns `null`.

## Verification

1. **Build:**
   ```
   cd frontend && npm run build
   ```
   Must compile cleanly (no TS errors).

2. **Run prod server locally:**
   ```
   PORT=3737 npm run start
   ```

3. **Confirm the served HTML preloads the proxied script:**
   ```
   curl -s http://localhost:3737/ | grep -oE 'href="/stats/js/script.js"'
   ```
   Should return `href="/stats/js/script.js"` (relative path, not
   `plausible.io`).

4. **Confirm the proxy fetches & serves the right bytes:**
   ```
   diff <(curl -s http://localhost:3737/stats/js/script.js) \
        <(curl -s https://plausible.io/js/pa-XXXXX.js)
   ```
   Should show no diff — same bytes.

5. **Confirm no `/api/*` collision:**
   ```
   curl -sI 'http://localhost:3737/api/games?limit=1'
   ```
   Should hit the FastAPI dev rewrite (404 if no FastAPI running, or
   200 if it is). Either way it must NOT be intercepted by Plausible.

6. **Post-deploy (after DNS cutover — separate launch task):**
   - Open `https://steampulse.io`
   - DevTools → Network: script comes from `steampulse.io/stats/js/...`
     (NOT `plausible.io`) — confirms proxy is working
   - Plausible **Realtime** dashboard shows the pageview within ~5s
   - The "Verify" banner in the Plausible dashboard auto-clears

## Out of scope (deferred)

- Custom events (Pro CTA clicks, search submissions, genre conversions).
  Add via `usePlausible<MyEvents>()` once we know which conversions matter.
- Move the `pa-XXXXX.js` URL to env var if it ever needs per-environment
  values. Today it's a single production-targeted ID, hardcoded in
  `next.config.ts`. Not a secret — appears in public `<script src>`.

## Files modified

| File | Change |
|------|--------|
| `frontend/package.json` / `package-lock.json` | Add `next-plausible@^4` |
| `frontend/next.config.ts` | Wrap export with `withPlausibleProxy({ src, scriptPath: "/stats/js/script.js", apiPath: "/stats/api/event" })` |
| `frontend/app/layout.tsx` | Import `PlausibleProvider`, wrap `<NuqsAdapter>` tree, gate via `enabled={process.env.NEXT_PUBLIC_PLAUSIBLE_ENABLED === "true"}` |
| `scripts/deploy.sh` | Export `NEXT_PUBLIC_PLAUSIBLE_ENABLED=true` in Step 1 only when `$ENV == "production"` |

## After merge

- Move this file: `scripts/prompts/plausible-analytics-pre-launch.md` →
  `scripts/prompts/completed/`
- Update `scripts/launch-checklist.org` lines 188-193: replace the raw
  `<script>` snippet with a one-liner referencing the completed prompt,
  then mark the entry `** DONE`.
