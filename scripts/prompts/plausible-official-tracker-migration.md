# plausible-official-tracker-migration

Migrate the frontend off the community `next-plausible` package onto Plausible's official `@plausible-analytics/tracker` ESM module so that pageviews fire reliably and the dashboard "Verify installation" check passes.

## Why

Live behavior on `https://steampulse.io` after the cutover (observed 2026-04-30):

- Plausible dashboard shows "We couldn't detect Plausible on your site."
- Curling the live HTML returns only `<link rel="preload" href="/stats/js/script.js">` with no accompanying `<script src=...>` tag. `next-plausible`'s `<PlausibleProvider>` defers script injection to `next/script` with `afterInteractive`, so the verifier (which does a no-JS HTML fetch) never sees a script tag.
- A real browser visit fires `GET /stats/js/script.js` 200 (~6.2KB, identical bytes to upstream `pa-fdpH1ur-zxTFCitvrhP8d.js`) but no `POST /stats/api/event` follows. Best diagnosis: the script is loaded by the preload, executes without the `data-api` attribute that `next-plausible` is supposed to inject onto a server-rendered tag, and POSTs directly to `https://plausible.io/api/event`, where the request is silently dropped by the gamer-audience adblock layer we set up the proxy to defeat.

The official `@plausible-analytics/tracker` package fixes both symptoms structurally:

- It is bundled with the app JS, so there is no preload-vs-script-tag race and no "did the proxy patch the data-api attribute" guesswork. If the page hydrates, the tracker initializes.
- `init({ endpoint })` configures the API URL explicitly, so the POST always goes through the proxy.
- `bindToWindow: true` (default) sets `window.plausible`, which is the hook Plausible's verifier uses to confirm installation.
- It is the upstream-maintained replacement for both the script tag and the now-archived `plausible-tracker` package.

## Goal

After this prompt:

- `next-plausible` is removed from the frontend.
- `@plausible-analytics/tracker` is installed and initialized exactly once on the client when `NEXT_PUBLIC_PLAUSIBLE_ENABLED === "true"`.
- `/stats/api/event` continues to proxy to `https://plausible.io/api/event` so the event POST is same-origin and bypasses adblockers.
- The 4 existing custom events in `WaitlistEmailForm.tsx` keep firing through a thin `trackEvent` wrapper that no-ops when the env var is not `"true"`.
- After deploy, `https://steampulse.io` shows pageviews in Plausible Realtime and the "Verify installation" banner clears.

## Scope

**In:**

- `frontend/package.json` / `frontend/package-lock.json`: remove `next-plausible`, add `@plausible-analytics/tracker` (current major).
- `frontend/next.config.ts`: drop the `withPlausibleProxy` wrapper. Replace the implicit rewrites with one explicit rewrite for the event endpoint:

  ```ts
  async rewrites() {
    const base = process.env.NODE_ENV !== "production"
      ? [{ source: "/api/:path*", destination: `${process.env.API_URL ?? "http://localhost:8000"}/api/:path*` }]
      : [];
    return [
      ...base,
      { source: "/stats/api/event", destination: "https://plausible.io/api/event" },
    ];
  }
  ```

  No more `/stats/js/script.js` route. The tracker code ships in the app bundle.

- `frontend/components/analytics/Plausible.tsx` (new, client component): one `useEffect` that **dynamically** imports the tracker and calls `init({ domain: "steampulse.io", endpoint: "/stats/api/event" })` when the env flag is `"true"`. Returns `null`.

  ```tsx
  "use client";
  import { useEffect } from "react";

  export function Plausible() {
    useEffect(() => {
      if (process.env.NEXT_PUBLIC_PLAUSIBLE_ENABLED !== "true") return;
      void import("@plausible-analytics/tracker").then(({ init }) => {
        init({ domain: "steampulse.io", endpoint: "/stats/api/event" });
      });
    }, []);
    return null;
  }
  ```

  The dynamic import is required: the package's compiled JS evaluates `location.href` at module top level, so any static `import` from `@plausible-analytics/tracker` blows up Next's prerender of `/_not-found` with `ReferenceError: location is not defined`.

- `frontend/lib/analytics.ts` (new): tiny wrapper that calls `window.plausible` (set by the package after `init` runs, since `bindToWindow` defaults to true). Type-only import keeps full type safety with no runtime module evaluation:

  ```ts
  import type { PlausibleEventOptions } from "@plausible-analytics/tracker";

  const enabled = process.env.NEXT_PUBLIC_PLAUSIBLE_ENABLED === "true";

  declare global {
    interface Window {
      plausible?: (name: string, options?: PlausibleEventOptions) => void;
    }
  }

  export function trackEvent(name: string, options?: PlausibleEventOptions) {
    if (!enabled) return;
    if (typeof window === "undefined") return;
    window.plausible?.(name, options);
  }
  ```

  Symmetric with the `init` gating, so call sites do not need to know about the env var. The `typeof window` guard handles SSR of the client component before hydration.

- `frontend/app/layout.tsx`: drop the `PlausibleProvider` import and wrapper. Mount `<Plausible />` once inside `<body>`, sibling to the existing JSON-LD scripts. Keep `<NuqsAdapter>` and `<Navbar />` in their current positions.

- `frontend/components/home/WaitlistEmailForm.tsx`: replace `import { usePlausible } from "next-plausible"` and the `const plausible = usePlausible()` line with `import { trackEvent } from "@/lib/analytics"`. Rename the 4 call sites from `plausible(name, opts)` to `trackEvent(name, opts)`. **One signature gotcha:** the official tracker types `props` as `Record<string, string>` (stricter than `next-plausible`), so the `Waitlist Suggestion` event's `length: trimmed.length` becomes `length: String(trimmed.length)`.

**Out:**

- `scripts/deploy.sh`: no change. The `NEXT_PUBLIC_PLAUSIBLE_ENABLED` wiring at lines 109-113 is reused as-is.
- CDK / CloudFront config: no change. The `/stats/api/event` rewrite is handled inside Next.js / OpenNext, not at the CDN layer.
- Custom event taxonomy: no new events in this prompt. Same 4 waitlist events as today.
- No commits, pushes, or deploys. Operator handles those.

## Decisions

1. **Centralize the env-flag gate in `lib/analytics.ts`.** Both `init` and `track` are no-ops when the flag is off. Call sites stay clean and we cannot regress by forgetting to gate one of them.

2. **Keep the `/stats/api/event` path unchanged.** It is the path that the prior setup uses, so any documentation, dashboard "outbound" rules, or follow-on configuration that referenced it stays valid.

3. **No `data-domain` or script-tag fallback.** The official package treats `init({ domain })` as the source of truth. Mixing in a parallel script tag would double-count pageviews.

4. **Initialize in a dedicated `<Plausible />` component, not inline in the layout.** Layouts are server components; init must run on the client. A one-purpose client component is cleaner than marking the entire layout `"use client"`.

5. **No retry / error surface around `init()`.** The package is browser-only and the `enabled` gate prevents SSR execution. Any runtime failure inside `init` is Plausible's bug, not ours, and would be visible in the browser console.

6. **Dynamic import + `window.plausible` instead of static `import { track }`.** The package isn't SSR-safe at module level (`location.href` evaluated top-level). A static import would crash any server-rendered code path. Dynamic-importing inside `useEffect` keeps the runtime module out of the SSR graph; the wrapper then calls `window.plausible` which the package binds during `init`. Type-only `import type { PlausibleEventOptions }` retains full type safety and is erased at compile time.

## Verification

1. **Build:**
   ```
   cd frontend && npm run build
   ```
   Must compile cleanly (no TS errors, no missing-module warnings).

2. **Run prod server locally with the flag on:**
   ```
   NEXT_PUBLIC_PLAUSIBLE_ENABLED=true PORT=3737 npm run start
   ```

3. **Confirm the rendered HTML no longer references `/stats/js/script.js`:**
   ```
   curl -s http://localhost:3737/ | grep -c 'stats/js/script.js'
   ```
   Must return `0`. The tracker is bundled now.

4. **Confirm the event endpoint still proxies upstream:**
   ```
   curl -sI -X POST http://localhost:3737/stats/api/event \
     -H 'Content-Type: application/json' \
     -d '{"n":"pageview","u":"http://localhost:3737/","d":"steampulse.io"}'
   ```
   Should return 202 from Plausible, not 404 from Next.

5. **Confirm `usePlausible` is fully removed:**
   ```
   grep -rn 'next-plausible\|usePlausible\|PlausibleProvider\|withPlausibleProxy' frontend
   ```
   Must return no matches.

6. **Post-deploy (operator-run, after merge):**
   - Open `https://steampulse.io` in a browser with no adblock for that origin.
   - DevTools Network: confirm `POST /stats/api/event` returns 202 on page load.
   - Plausible Realtime dashboard shows the visit within ~5s.
   - The "We couldn't detect Plausible" banner clears on next dashboard refresh.
   - Submit the waitlist form on the homepage and confirm the `Waitlist Signup` event lands in the dashboard's Goals view.

## Files modified

| File | Change |
|------|--------|
| `frontend/package.json` / `package-lock.json` | Remove `next-plausible`, add `@plausible-analytics/tracker` |
| `frontend/next.config.ts` | Drop `withPlausibleProxy`, add explicit `/stats/api/event` rewrite |
| `frontend/app/layout.tsx` | Drop `<PlausibleProvider>`, mount `<Plausible />` |
| `frontend/components/analytics/Plausible.tsx` | New client component, calls `init({ domain, endpoint })` once |
| `frontend/lib/analytics.ts` | New `trackEvent` wrapper, env-flag gated |
| `frontend/components/home/WaitlistEmailForm.tsx` | Replace `usePlausible()` with `trackEvent` from `lib/analytics` |

## After merge

- Move this file: `scripts/prompts/plausible-official-tracker-migration.md` to `scripts/prompts/completed/`.
- The earlier `scripts/prompts/completed/plausible-analytics-pre-launch.md` stays where it is. It documents the prior cutover honestly; this prompt supersedes its implementation only.
