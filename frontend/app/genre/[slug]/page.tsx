import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getGenreInsights, getReportForGenre } from "@/lib/api";
import { Breadcrumbs } from "@/components/layout/Breadcrumbs";
import { SynthesisHeader } from "@/components/genre/SynthesisHeader";
import { FrictionPoints } from "@/components/genre/FrictionPoints";
import { WishlistItems } from "@/components/genre/WishlistItems";
import { BenchmarkGames } from "@/components/genre/BenchmarkGames";
import { ChurnWall } from "@/components/genre/ChurnWall";
import { DevPrioritiesTable } from "@/components/genre/DevPrioritiesTable";
import { MethodologyFooter } from "@/components/genre/MethodologyFooter";
import { ReportBlock } from "@/components/genre/ReportBlock";
import { genrePageUrl } from "@/components/genre/url";

// Escape `<` in a JSON string so LLM-authored content like `</script>` inside
// any field can't break out of the <script type="application/ld+json"> tag.
function safeJsonLd(obj: unknown): string {
  return JSON.stringify(obj).replace(/</g, "\\u003c");
}

interface Props {
  params: Promise<{ slug: string }>;
}

export const revalidate = 3600;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const row = await getGenreInsights(slug);
  if (!row) {
    return {
      title: "Genre not found — SteamPulse",
      robots: { index: false, follow: false },
    };
  }
  const title = `${row.display_name}: What Players Want, Hate, and Praise | SteamPulse`;
  const description = row.narrative_summary.slice(0, 155);
  const canonical = genrePageUrl(slug);
  return {
    title,
    description,
    openGraph: {
      title,
      description,
      url: canonical,
      images: [{ url: "/og-default.png", width: 1200, height: 630 }],
      type: "article",
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
    },
    alternates: { canonical },
  };
}

export default async function GenrePage({ params }: Props) {
  const { slug } = await params;
  // Fetch insights first — if the slug is unknown we 404 without paying for
  // a second round trip to the optional report endpoint.
  const row = await getGenreInsights(slug);
  if (!row) notFound();
  const report = await getReportForGenre(slug);

  // Partial lookup so blockquote attributions can name the source game when
  // it's also one of the benchmark games. Friction/wishlist/churn may
  // reference appids outside the benchmark set — those fall back to a
  // plain "source game →" link.
  const appidToName: Record<number, string> = {};
  for (const b of row.synthesis.benchmark_games) {
    appidToName[b.appid] = b.name;
  }

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: `What ${row.display_name} Players Want, Hate, and Praise`,
    description: row.narrative_summary,
    datePublished: row.computed_at,
    dateModified: row.computed_at,
    author: {
      "@type": "Organization",
      name: "SteamPulse",
      url: "https://steampulse.io",
    },
    publisher: {
      "@type": "Organization",
      name: "SteamPulse",
      url: "https://steampulse.io",
    },
    about: {
      "@type": "VideoGameSeries",
      name: row.display_name,
    },
    mainEntityOfPage: {
      "@type": "WebPage",
      "@id": genrePageUrl(slug),
    },
  };

  return (
    <div className="min-h-screen bg-background">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: safeJsonLd(jsonLd) }}
      />
      <div className="max-w-6xl mx-auto px-4 md:px-6 py-8">
        <Breadcrumbs
          items={[
            { label: "Home", href: "/" },
            { label: "Genres", href: "/search" },
            { label: row.display_name },
          ]}
        />

        <div className="mt-6 grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_20rem] gap-10">
          <main>
            <SynthesisHeader row={row} />
            <FrictionPoints
              items={row.synthesis.friction_points}
              inputCount={row.input_count}
              appidToName={appidToName}
            />
            <WishlistItems
              items={row.synthesis.wishlist_items}
              inputCount={row.input_count}
              appidToName={appidToName}
            />
            <BenchmarkGames items={row.synthesis.benchmark_games} />
            <ChurnWall
              churn={row.synthesis.churn_insight}
              appidToName={appidToName}
            />
            <DevPrioritiesTable rows={row.synthesis.dev_priorities} />
            {report && (
              <div className="mb-14">
                <ReportBlock report={report} placement="body" />
              </div>
            )}
            <MethodologyFooter />
          </main>

          <aside className="hidden md:block">
            <div className="sticky top-24 space-y-6">
              <section
                aria-labelledby="at-a-glance"
                className="rounded-xl p-5"
                style={{ background: "var(--card)", border: "1px solid var(--border)" }}
              >
                <h2
                  id="at-a-glance"
                  className="font-mono text-xs uppercase tracking-widest text-muted-foreground mb-4"
                >
                  At a glance
                </h2>
                <dl className="space-y-3 text-sm">
                  <div className="flex justify-between gap-4">
                    <dt className="text-muted-foreground">Games</dt>
                    <dd className="font-mono tabular-nums">{row.input_count.toLocaleString()}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-muted-foreground">Median reviews/game</dt>
                    <dd className="font-mono tabular-nums">
                      {row.median_review_count.toLocaleString()}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-muted-foreground">Avg positive</dt>
                    <dd className="font-mono tabular-nums">
                      {Math.round(row.avg_positive_pct)}%
                    </dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-muted-foreground">Refresh</dt>
                    <dd className="font-mono text-xs">weekly</dd>
                  </div>
                </dl>
              </section>
              {report && <ReportBlock report={report} placement="sidebar" />}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
