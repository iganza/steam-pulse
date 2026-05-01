import { execSync } from "node:child_process";
import type { NextConfig } from "next";

// Pin Next BUILD_ID to git short SHA — same value CACHE_BUCKET_KEY_PREFIX
// uses, so OpenNext tag namespaces stay aligned across deploys and
// revalidateTag actually busts the entries readers see.
function gitBuildId(): string {
  try {
    return execSync("git rev-parse --short HEAD", { encoding: "utf8" }).trim();
  } catch {
    return "local";
  }
}

const nextConfig: NextConfig = {
  generateBuildId: gitBuildId,
  // In local dev, proxy /api/* to the FastAPI server.
  // In production/staging, CloudFront handles this routing at the CDN layer.
  // To point at staging API instead of local: API_URL=https://d218hpg56ignkd.cloudfront.net npm run dev
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
  async rewrites() {
    const base =
      process.env.NODE_ENV !== "production"
        ? [
            {
              source: "/api/:path*",
              destination: `${process.env.API_URL ?? "http://localhost:8000"}/api/:path*`,
            },
          ]
        : [];
    return [
      ...base,
      { source: "/stats/api/event", destination: "https://plausible.io/api/event" },
      // Next.js 16 generateSitemaps() omits the index; rewrite /sitemap.xml to our handler.
      { source: "/sitemap.xml", destination: "/sitemap-index" },
    ];
  },
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
