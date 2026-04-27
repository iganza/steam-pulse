import type { Metadata } from "next";
import { Suspense } from "react";
import { getTagsGrouped, getTagTrend } from "@/lib/api";
import Link from "next/link";
import { Breadcrumbs } from "@/components/layout/Breadcrumbs";
import { SearchClient } from "@/app/search/SearchClient";
import { TagTrendChart } from "@/components/analytics/TagTrendChart";
import type { TagGroup } from "@/lib/types";

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

  // Fetch grouped tags and tag trend in parallel
  const [groupsResult, trendResult] = await Promise.allSettled([
    getTagsGrouped(200),
    getTagTrend(slug),
  ]);

  const groups: TagGroup[] =
    groupsResult.status === "fulfilled" ? groupsResult.value : [];
  const allTags = groups.flatMap((g) => g.tags);
  const currentTag = allTags.find((t) => t.slug === slug);
  const currentCategory = currentTag?.category;
  const otherTags = allTags.filter((t) => t.slug !== slug);
  const sameCategoryTags = currentCategory
    ? otherTags.filter((t) => t.category === currentCategory)
    : [];
  const relatedTags =
    sameCategoryTags.length >= 8
      ? sameCategoryTags.slice(0, 8)
      : [
          ...sameCategoryTags,
          ...otherTags
            .filter((t) => !sameCategoryTags.includes(t))
            .slice(0, 8 - sameCategoryTags.length),
        ];
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
            <span className="text-xs font-mono uppercase tracking-widest px-2 py-0.5 rounded bg-teal/10 border border-teal/20 text-teal">
              Tag
            </span>
            <h1
              className="font-serif text-h1 font-bold"
              style={{ letterSpacing: "-0.03em" }}
            >
              {name}
            </h1>
          </div>
        </div>

        {/* Related Tags */}
        {relatedTags.length > 0 && (
          <div className="mb-10">
            <p className="text-eyebrow mb-2">
              {currentCategory ? `More ${currentCategory} Tags` : "Related Tags"}
            </p>
            <div className="flex flex-wrap gap-2">
              {relatedTags.map((t) => (
                <Link
                  key={t.id}
                  href={`/tag/${t.slug}`}
                  className="text-sm px-3 py-1.5 rounded-full font-mono transition-colors hover:text-foreground bg-teal/6 border border-teal/15 text-teal"
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

        {/* Games with this tag */}
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
