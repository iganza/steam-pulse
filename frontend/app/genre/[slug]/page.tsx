import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getGenreInsights, getReportForGenre, getGameBasics } from "@/lib/api";
import { AUTHOR_NAME, ABOUT_URL } from "@/lib/author";
import { Breadcrumbs } from "@/components/layout/Breadcrumbs";
import { EditorialIntro } from "@/components/genre/EditorialIntro";
import { FrictionList } from "@/components/genre/FrictionList";
import { WishlistList } from "@/components/genre/WishlistList";
import { BenchmarkGrid } from "@/components/genre/BenchmarkGrid";
import { ChurnWall } from "@/components/genre/ChurnWall";
import { DevPrioritiesTeaser } from "@/components/genre/DevPrioritiesTeaser";
import { MethodologyFooter } from "@/components/genre/MethodologyFooter";
import { ReportBuyBlock } from "@/components/genre/ReportBuyBlock";
import type { GameBasics } from "@/components/genre/gameBasics";

interface Props {
  params: Promise<{ slug: string }>;
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  const slice = s.slice(0, n - 1);
  const lastSpace = slice.lastIndexOf(" ");
  return (lastSpace > n * 0.6 ? slice.slice(0, lastSpace) : slice).trimEnd() + "…";
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const insights = await getGenreInsights(slug);
  // No trailing slash — mirrors the games/[appid]/[slug] canonical shape and
  // avoids the Next.js default-off trailingSlash redirect loop.
  const canonical = `https://steampulse.io/genre/${slug}`;
  if (!insights) {
    return {
      title: "Not found | SteamPulse",
      alternates: { canonical },
    };
  }
  const title = `${insights.display_name}: What Players Want, Hate, and Praise | SteamPulse`;
  const description = truncate(insights.narrative_summary, 155);
  const ogImage = "/og-default.png";
  return {
    title,
    description,
    openGraph: {
      title,
      description,
      url: canonical,
      images: [{ url: ogImage, width: 1200, height: 630 }],
      type: "article",
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [ogImage],
    },
    alternates: { canonical },
  };
}

export default async function GenrePage({ params }: Props) {
  const { slug } = await params;

  const [insights, report] = await Promise.all([
    getGenreInsights(slug),
    getReportForGenre(slug),
  ]);
  // At launch, only a handful of genres have a cross-genre synthesis row.
  // Clicking a Browse link for a genre without one (e.g. "Indie") would
  // otherwise 404. Send those users to the game-list search filtered by
  // genre — same intent, different surface — until the synthesis ships.
  if (!insights) redirect(`/search?genre=${encodeURIComponent(slug)}`);

  // Collect every appid that renders a crosslink: friction quotes, wishlist
  // quotes, benchmark cards. The churn insight's source_appid is NOT
  // included — the free-page churn wall shows the stat + interpretation
  // only, no per-game quote link, so fetching its basics is wasted work.
  // One batched /api/games/basics call replaces up to 11 /report fetches.
  const appids = new Set<number>();
  for (const f of insights.synthesis.friction_points.slice(0, 5)) appids.add(f.source_appid);
  for (const w of insights.synthesis.wishlist_items.slice(0, 3)) appids.add(w.source_appid);
  for (const b of insights.synthesis.benchmark_games.slice(0, 3)) appids.add(b.appid);

  const games: Record<number, GameBasics> = {};
  try {
    const basics = await getGameBasics(Array.from(appids));
    for (const g of basics) {
      games[g.appid] = {
        slug: g.slug,
        name: g.name,
        header_image: g.header_image ?? `https://cdn.akamai.steamstatic.com/steam/apps/${g.appid}/header.jpg`,
      };
    }
  } catch {
    // Basics endpoint failure degrades to plain names + Steam-CDN covers;
    // the page still renders.
  }

  const shareUrl = `https://steampulse.io/genre/${slug}`;
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: `What ${insights.display_name} Players Want, Hate, and Praise`,
    datePublished: insights.computed_at,
    dateModified: insights.computed_at,
    // author = named human expert (Google 2026 AI-content signal); publisher
    // = the org. Mirrors the games/[appid]/[slug] JSON-LD shape.
    author: { "@type": "Person", name: AUTHOR_NAME, url: ABOUT_URL },
    publisher: {
      "@type": "Organization",
      name: "SteamPulse",
      url: "https://steampulse.io",
    },
    about: { "@type": "VideoGameSeries", name: insights.display_name },
    mainEntityOfPage: shareUrl,
    description: truncate(insights.narrative_summary, 300),
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <main className="min-h-screen bg-background">
        <div className="max-w-6xl mx-auto px-6 py-8">
          <Breadcrumbs
            items={[
              { label: "Home", href: "/" },
              { label: "Browse", href: "/search" },
              { label: insights.display_name },
            ]}
          />

          <div className="mt-8 grid grid-cols-1 lg:grid-cols-[1fr_20rem] gap-10">
            <article>
              <EditorialIntro insights={insights} shareUrl={shareUrl} />

              <FrictionList
                items={insights.synthesis.friction_points}
                gameCount={insights.input_count}
                games={games}
                hasReport={!!report}
              />

              <WishlistList
                items={insights.synthesis.wishlist_items}
                gameCount={insights.input_count}
                games={games}
                hasReport={!!report}
              />

              <BenchmarkGrid
                items={insights.synthesis.benchmark_games}
                totalCount={insights.synthesis.benchmark_games.length}
                games={games}
                hasReport={!!report}
              />

              <ChurnWall
                insight={insights.synthesis.churn_insight}
                interpretation={insights.churn_interpretation}
              />

              <DevPrioritiesTeaser
                items={insights.synthesis.dev_priorities}
                totalCount={insights.synthesis.dev_priorities.length}
                hasReport={!!report}
              />

              {report && <ReportBuyBlock report={report} variant="main" />}

              <MethodologyFooter
                displayName={insights.display_name}
                inputCount={insights.input_count}
              />
            </article>

            <aside className="hidden lg:block">
              <div className="sticky top-6 space-y-4">
                {report && <ReportBuyBlock report={report} variant="sidebar" />}
                <nav
                  className="rounded-xl p-5 text-sm"
                  style={{ background: "var(--card)", border: "1px solid var(--border)" }}
                >
                  <h2
                    className="text-xs font-mono uppercase tracking-widest mb-3"
                    style={{ color: "var(--muted-foreground)" }}
                  >
                    On this page
                  </h2>
                  <ul className="space-y-2">
                    <li><a href="#methodology" className="hover:text-foreground transition-colors">Methodology &rarr;</a></li>
                  </ul>
                </nav>
              </div>
            </aside>
          </div>
        </div>
      </main>
    </>
  );
}

export const revalidate = 3600;
