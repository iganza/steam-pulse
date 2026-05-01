import { SITEMAP_BASE_URL, SITEMAP_TOTAL_CHUNKS } from "../sitemap-config";

// generateSitemaps() in app/sitemap.ts emits children at /sitemap/N.xml but no parent index; vercel/next.js#77304.
// next.config.ts rewrites /sitemap.xml -> /sitemap-index because a directory at app/sitemap.xml/ breaks sitemap.ts's [__metadata_id__] route.
export const dynamic = "force-static";

export async function GET() {
  const sitemaps = Array.from(
    { length: SITEMAP_TOTAL_CHUNKS },
    (_, id) => `  <sitemap><loc>${SITEMAP_BASE_URL}/sitemap/${id}.xml</loc></sitemap>`,
  ).join("\n");
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${sitemaps}
</sitemapindex>`;
  return new Response(xml, {
    headers: { "Content-Type": "application/xml" },
  });
}
