import type { Metadata } from "next";
import { Suspense } from "react";
import { getTopTags, getTagTrend } from "@/lib/api";
import Link from "next/link";
import { Breadcrumbs } from "@/components/layout/Breadcrumbs";
import { SearchClient } from "@/app/search/SearchClient";
import { TagTrendChart } from "@/components/analytics/TagTrendChart";
import type { Tag } from "@/lib/types";

interface Props {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const name = slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return {
    title: `${name} Games`,
    description: `Steam games tagged "${name}" \u2014 player sentiment analysis, hidden gems, and review intelligence.`,
    openGraph: {
      title: `${name} Games on Steam — SteamPulse`,
      description: `Steam games tagged "${name}" — player sentiment analysis, hidden gems, and review intelligence.`,
      url: `https://steampulse.io/tag/${slug}`,
      images: [{ url: "/og-default.png", width: 1200, height: 630 }],
    },
    twitter: {
      card: "summary_large_image",
      title: `${name} Games on Steam — SteamPulse`,
      description: `Steam games tagged "${name}" — player sentiment analysis, hidden gems, and review intelligence.`,
    },
    alternates: { canonical: `https://steampulse.io/tag/${slug}` },
  };
}

export default async function TagPage({ params }: Props) {
  const { slug } = await params;
  const name = slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  // Fetch related tags and tag trend in parallel
  const [tagsResult, trendResult] = await Promise.allSettled([
    getTopTags(50),
    getTagTrend(slug),
  ]);

  const tags = tagsResult.status === "fulfilled" ? tagsResult.value : [];
  const relatedTags = (tags as Tag[])
    .filter((t) => t.slug !== slug)
    .slice(0, 8);
  const trend = trendResult.status === "fulfilled" ? trendResult.value : null;

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto px-6 py-8">
        <Breadcrumbs
          items={[
            { label: "Home", href: "/" },
            { label: "Tags", href: "/search" },
            { label: name },
          ]}
        />

        <div className="mt-6 mb-6">
          <div className="flex items-center gap-3 mb-2">
            <span
              className="text-xs font-mono uppercase tracking-widest px-2 py-0.5 rounded"
              style={{
                background: "rgba(45,185,212,0.1)",
                border: "1px solid rgba(45,185,212,0.2)",
                color: "var(--teal)",
              }}
            >
              Tag
            </span>
            <h1
              className="font-serif text-4xl font-bold"
              style={{ letterSpacing: "-0.03em" }}
            >
              {name}
            </h1>
          </div>
        </div>

        {/* Related Tags */}
        {relatedTags.length > 0 && (
          <div className="mb-10">
            <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-2">
              Related Tags
            </p>
            <div className="flex flex-wrap gap-2">
              {relatedTags.map((t) => (
                <Link
                  key={t.id}
                  href={`/tag/${t.slug}`}
                  className="text-sm px-3 py-1.5 rounded-full font-mono transition-colors hover:text-foreground"
                  style={{
                    background: "rgba(45,185,212,0.06)",
                    border: "1px solid rgba(45,185,212,0.15)",
                    color: "var(--teal)",
                  }}
                >
                  {t.name}
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* Tag Trends */}
        {trend && trend.yearly.length >= 2 && (
          <section className="mb-10 space-y-4">
            <h2 className="font-serif text-lg font-semibold">Tag Trends</h2>
            <TagTrendChart data={trend} />
          </section>
        )}

        {/* Full catalog with filters */}
        <Suspense fallback={<p className="text-base text-muted-foreground font-mono py-8">Loading...</p>}>
          <SearchClient
            initialParams={{}}
            initialFilters={{ tag: slug }}
            hideTagFilter
          />
        </Suspense>
      </div>
    </div>
  );
}

export const revalidate = 3600;
