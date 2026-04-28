import type { Metadata } from "next";
import { Clock } from "lucide-react";
import { getDiscoveryFeed, getGameBasics, getGameReport } from "@/lib/api";
import type { GameBasicsEntry } from "@/lib/api";
import { MarketTrendsPreview } from "@/components/home/MarketTrendsPreview";
import { WaitlistEmailForm } from "@/components/home/WaitlistEmailForm";
import { FeaturedAnalysesShowcase } from "@/components/home/FeaturedAnalysesShowcase";
import type { ShowcaseEntry } from "@/components/home/FeaturedAnalysesShowcase";
import { GameCard } from "@/components/game/GameCard";
import type { Game } from "@/lib/types";

const SHOWCASE_APPIDS = [1086940, 413150, 1091500] as const;

export const metadata: Metadata = {
  title: "SteamPulse — Steam Game Intelligence",
  description:
    "Game intelligence for studios. Player sentiment, themes, and market gaps across every Steam game.",
  openGraph: {
    title: "SteamPulse — Steam Game Intelligence",
    description:
      "Game intelligence for studios. Player sentiment, themes, and market gaps across every Steam game.",
    url: "https://steampulse.io",
    images: [{ url: "/og-default.png", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "SteamPulse — Steam Game Intelligence",
    description:
      "Game intelligence for studios. Player sentiment, themes, and market gaps across every Steam game.",
    images: ["/og-default.png"],
  },
  alternates: {
    canonical: "https://steampulse.io",
  },
};

const HERO_SUBTEXT = "Free reports today. Pro launches soon. No spam.";

export default async function HomePage() {
  const [
    justAnalyzed,
    showcase,
    ...reportResults
  ] = await Promise.allSettled([
    getDiscoveryFeed("just_analyzed", 3),
    getGameBasics([...SHOWCASE_APPIDS]),
    ...SHOWCASE_APPIDS.map((appid) => getGameReport(appid)),
  ]);

  const analyzedGames: Game[] =
    justAnalyzed.status === "fulfilled" ? justAnalyzed.value.games ?? [] : [];
  const showcaseGames: GameBasicsEntry[] =
    showcase.status === "fulfilled" ? showcase.value : [];

  const showcaseEntries: ShowcaseEntry[] = [];
  SHOWCASE_APPIDS.forEach((appid, i) => {
    const basics = showcaseGames.find((g) => g.appid === appid);
    if (!basics) return;
    const reportResult = reportResults[i];
    const report =
      reportResult?.status === "fulfilled"
        ? reportResult.value.report
        : undefined;
    showcaseEntries.push({
      appid,
      name: basics.name,
      slug: basics.slug,
      header_image: basics.header_image,
      positive_pct: basics.positive_pct,
      one_liner: report?.one_liner ?? null,
      top_strength: report?.design_strengths?.[0] ?? null,
      top_friction: report?.gameplay_friction?.[0] ?? null,
      reviews_analyzed: report?.total_reviews_analyzed ?? null,
    });
  });

  return (
    <div className="min-h-screen bg-background">
      {/* Hero */}
      <header className="relative">
        <div
          className="absolute inset-0 opacity-30 pointer-events-none overflow-hidden"
          style={{
            background:
              "radial-gradient(ellipse 80% 50% at 50% -20%, rgba(45,185,212,0.15), transparent)",
          }}
        />
        <div className="relative max-w-3xl mx-auto px-6 pt-12 pb-6 text-center">
          <h1
            className="font-serif text-h1 font-bold text-foreground mb-2 leading-tight"
            style={{ letterSpacing: "-0.03em" }}
          >
            Steam, decoded
          </h1>
          <p className="text-base text-muted-foreground mb-6 max-w-lg mx-auto">
            Game intelligence for studios. Sentiment, themes, and market gaps
            across every Steam game.
          </p>
          <WaitlistEmailForm
            variant="hero"
            buttonLabel="Join the Pro waitlist"
            subtext={HERO_SUBTEXT}
          />
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 pb-24 space-y-12">
        {/* Featured analyses — name-recognition trust signal + real teaser content */}
        {showcaseEntries.length > 0 && (
          <FeaturedAnalysesShowcase entries={showcaseEntries} />
        )}

        {/* Market Trends — live charts demonstrate platform capability */}
        <MarketTrendsPreview />

        {/* Just Analyzed — freshness signal, reason to revisit */}
        {analyzedGames.length > 0 && (
          <section>
            <div className="flex items-center gap-2 mb-2">
              <Clock className="w-4 h-4 text-teal" />
              <h2 className="font-serif text-xl font-semibold">Just analyzed</h2>
            </div>
            <p className="text-sm text-muted-foreground font-mono mb-6">
              Updated continuously. Each report is free to read.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {analyzedGames.map((game) => (
                <GameCard key={game.appid} game={game} />
              ))}
            </div>
          </section>
        )}

        {/* Repeat CTA */}
        <section className="py-8">
          <WaitlistEmailForm
            variant="repeat"
            headline="Be first when Pro launches."
            buttonLabel="Join the Pro waitlist"
            subtext={HERO_SUBTEXT}
          />
        </section>
      </main>
    </div>
  );
}

// ISR: homepage content doesn't change faster than the matview refresh cadence.
// CloudFront + Next.js ISR serve the rendered HTML from cache for every visitor
// between revalidations.
export const revalidate = 300;
