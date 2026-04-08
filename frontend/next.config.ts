import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
  async redirects() {
    return [
      { source: "/analytics", destination: "/explore", permanent: true },
      { source: "/toolkit", destination: "/explore", permanent: true },
    ];
  },
  async rewrites() {
    if (process.env.NODE_ENV !== "production") {
      return [
        {
          source: "/api/:path*",
          destination: `${process.env.API_URL ?? "http://localhost:8000"}/api/:path*`,
        },
      ];
    }
    return [];
  },
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
