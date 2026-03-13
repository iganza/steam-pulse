import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // In local dev, proxy /api/* to the FastAPI server.
  // In production/staging, CloudFront handles this routing at the CDN layer.
  // To point at staging API instead of local: API_URL=https://d218hpg56ignkd.cloudfront.net npm run dev
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
    remotePatterns: [
      {
        protocol: "https",
        hostname: "shared.akamai.steamstatic.com",
      },
      {
        protocol: "https",
        hostname: "cdn.akamai.steamstatic.com",
      },
      {
        protocol: "https",
        hostname: "steamcdn-a.akamaihd.net",
      },
      {
        protocol: "https",
        hostname: "store.akamai.steamstatic.com",
      },
    ],
  },
};

export default nextConfig;
