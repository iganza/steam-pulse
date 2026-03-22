# SEO Foundations: OG Tags, Twitter Cards, Canonical URLs, Structured Data

## Goal

Strengthen the existing SEO foundations across all pages. The sitemap,
robots.txt, and basic metadata already exist. This task adds the missing
layer: OpenGraph tags, Twitter cards, canonical URLs, security/cache headers,
and enhanced structured data. **Do not touch any backend code — frontend only.**

Production domain: `https://steampulse.io`

---

## What Already Exists (do not duplicate)

- `frontend/app/layout.tsx` — `metadataBase`, title template, basic OG siteName/type/locale, Twitter card type
- `frontend/app/sitemap.ts` — dynamic sitemap, fully implemented
- `frontend/app/robots.ts` — robots rules, fully implemented
- `frontend/app/games/[appid]/[slug]/page.tsx` — `generateMetadata()` with OG title/description/image + VideoGame JSON-LD schema
- Basic `title` + `description` on all other pages (search, genre, tag, developer, trending, new-releases, pro)

---

## Changes Required

### 1. Root Layout — `frontend/app/layout.tsx`

Expand the existing metadata export to add:
- `openGraph.title`, `openGraph.description`, `openGraph.url`, `openGraph.images`
- `twitter.title`, `twitter.description`, `twitter.images`, `twitter.creator` (`@steampulse`)
- `alternates.canonical` pointing to `https://steampulse.io`

Default OG/Twitter image: use `https://steampulse.io/og-default.png` (a static
image to be placed at `frontend/public/og-default.png` — create a simple 1200×630
placeholder text file with that name and a comment that it needs to be replaced
with a real image).

Add a root-level `WebSite` JSON-LD with `SearchAction` sitelinks searchbox:
```json
{
  "@context": "https://schema.org",
  "@type": "WebSite",
  "name": "SteamPulse",
  "url": "https://steampulse.io",
  "description": "Deep review intelligence for Steam games.",
  "potentialAction": {
    "@type": "SearchAction",
    "target": {
      "@type": "EntryPoint",
      "urlTemplate": "https://steampulse.io/search?q={search_term_string}"
    },
    "query-input": "required name=search_term_string"
  }
}
```

### 2. Homepage — `frontend/app/page.tsx`

Add a `metadata` export (static, not `generateMetadata`):
```typescript
export const metadata: Metadata = {
  title: "SteamPulse: Steam Game Intelligence",
  description: "Deep review intelligence for 6,000+ Steam games. Discover what players love, hate, and want next.",
  openGraph: {
    title: "SteamPulse: Steam Game Intelligence",
    description: "Deep review intelligence for 6,000+ Steam games.",
    url: "https://steampulse.io",
    images: [{ url: "/og-default.png", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "SteamPulse: Steam Game Intelligence",
    description: "Deep review intelligence for 6,000+ Steam games.",
    images: ["/og-default.png"],
  },
  alternates: {
    canonical: "https://steampulse.io",
  },
};
```

### 3. Game Report Page — `frontend/app/games/[appid]/[slug]/page.tsx`

Extend the existing `generateMetadata()` to add:
- `openGraph.url` — canonical URL for the game page
- `openGraph.type: "article"`
- `twitter.card`, `twitter.title`, `twitter.description`, `twitter.images`
- `alternates.canonical` — the canonical URL

The canonical URL format: `https://steampulse.io/games/{appid}/{slug}`

Also enhance the existing VideoGame JSON-LD (already present) to add:
- `"description"`: use `one_liner` if report available, else `short_desc`
- `"url"`: the canonical game page URL
- `"numberOfPlayers"`: `{"@type": "QuantitativeValue", "value": review_count}` (proxy for player count)

Wrap JSON-LD in a `<script type="application/ld+json">` tag using Next.js
`<Script>` or a plain `<script>` in the page's JSX (check how it's currently
rendered and follow the same pattern).

### 4. Taxonomy Pages (genre, tag, developer) + Static Pages (search, trending, new-releases, pro)

For each page, expand the existing `generateMetadata()` (or `metadata` export)
to add OG and Twitter tags following this pattern:

**Genre page (`frontend/app/genre/[slug]/page.tsx`):**
```typescript
openGraph: {
  title: `${name} Games on Steam — SteamPulse`,
  description: `Browse ${name} games with player sentiment analysis...`,
  url: `https://steampulse.io/genre/${slug}`,
  images: [{ url: "/og-default.png", width: 1200, height: 630 }],
},
twitter: {
  card: "summary_large_image",
  title: `${name} Games on Steam — SteamPulse`,
  description: `Browse ${name} games with player sentiment analysis...`,
},
alternates: { canonical: `https://steampulse.io/genre/${slug}` },
```

Apply the same pattern to **tag**, **developer**, **trending**, **new-releases**, and **pro** pages — adapting titles and descriptions to match the page purpose.

**Search page (`frontend/app/search/page.tsx`):**

Add canonical that strips sort/filter params to prevent duplicate content:
```typescript
alternates: {
  canonical: q
    ? `https://steampulse.io/search?q=${encodeURIComponent(q)}`
    : "https://steampulse.io/search",
},
```

### 5. Security + Cache Headers — `frontend/next.config.ts`

Add an `async headers()` function to the existing Next config:

```typescript
async headers() {
  return [
    {
      source: "/(.*)",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "SAMEORIGIN" },
        { key: "X-XSS-Protection", value: "1; mode=block" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
      ],
    },
    {
      // Cache static Steam CDN images aggressively in the CDN
      source: "/_next/image(.*)",
      headers: [
        { key: "Cache-Control", value: "public, max-age=86400, stale-while-revalidate=604800" },
      ],
    },
  ];
},
```

---

## Placeholder OG Image

Create `frontend/public/og-default.png` as a placeholder (any valid PNG file,
or just note in a comment file). This is referenced by all pages that don't
have a game-specific header image. A real designed image should replace it
before launch.

---

## Tests

Add tests to `frontend/e2e/seo.spec.ts` (new file):

```typescript
// Test that key pages have correct meta tags

test("homepage has OG tags", async ({ page }) => {
  await page.goto("/");
  const ogTitle = await page.locator('meta[property="og:title"]').getAttribute("content");
  expect(ogTitle).toContain("SteamPulse");
  const twitterCard = await page.locator('meta[name="twitter:card"]').getAttribute("content");
  expect(twitterCard).toBe("summary_large_image");
  const canonical = await page.locator('link[rel="canonical"]').getAttribute("href");
  expect(canonical).toBe("https://steampulse.io");
});

test("game page has OG image and canonical", async ({ page }) => {
  // Use a known appid that exists in the test env (e.g., mock or use appid 440)
  await page.goto("/games/440/team-fortress-2");
  const ogImage = await page.locator('meta[property="og:image"]').getAttribute("content");
  expect(ogImage).toContain("steam"); // CDN image URL
  const canonical = await page.locator('link[rel="canonical"]').getAttribute("href");
  expect(canonical).toContain("/games/440/");
  const jsonLd = await page.locator('script[type="application/ld+json"]').textContent();
  expect(JSON.parse(jsonLd ?? "{}")).toMatchObject({ "@type": "VideoGame" });
});

test("genre page has OG tags", async ({ page }) => {
  await page.goto("/genre/action");
  const ogTitle = await page.locator('meta[property="og:title"]').getAttribute("content");
  expect(ogTitle).toContain("Action");
  expect(ogTitle).toContain("SteamPulse");
});

test("robots.txt is accessible and correct", async ({ page }) => {
  const resp = await page.goto("/robots.txt");
  expect(resp?.status()).toBe(200);
  const body = await resp?.text();
  expect(body).toContain("sitemap");
  expect(body).toContain("Disallow: /api/");
});

test("sitemap.xml is accessible", async ({ page }) => {
  const resp = await page.goto("/sitemap.xml");
  expect(resp?.status()).toBe(200);
  const body = await resp?.text();
  expect(body).toContain("<urlset");
  expect(body).toContain("steampulse.io");
});

test("search page canonical strips filter params", async ({ page }) => {
  await page.goto("/search?q=portal&sort=review_count&genre=puzzle");
  const canonical = await page.locator('link[rel="canonical"]').getAttribute("href");
  // Canonical should only have q= not sort= or genre=
  expect(canonical).toContain("q=portal");
  expect(canonical).not.toContain("sort=");
});
```

---

## Constraints

- **Frontend only** — no changes to any Python/backend code
- **Do not modify** `sitemap.ts`, `robots.ts` — they are complete
- **Do not restructure** existing `generateMetadata()` functions — only add the missing OG/Twitter/canonical fields
- **Do not add new npm packages** — use only what Next.js Metadata API provides natively
- Run `cd frontend && npm run build` to verify no TypeScript errors
- Run the new Playwright SEO tests: `npx playwright test e2e/seo.spec.ts`
