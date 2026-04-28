import type { Metadata } from "next";
import { Clock } from "lucide-react";
import { getDiscoveryFeed, getCatalogStats } from "@/lib/api";
import { MarketTrendsPreview } from "@/components/home/MarketTrendsPreview";
import { WaitlistEmailForm } from "@/components/home/WaitlistEmailForm";
import { GameCard } from "@/components/game/GameCard";
import type { Game } from "@/lib/types";

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
  const [justAnalyzed, catalogStats] = await Promise.allSettled([
    getDiscoveryFeed("just_analyzed", 3),
    getCatalogStats(),
  ]);

  const analyzedGames: Game[] =
    justAnalyzed.status === "fulfilled" ? justAnalyzed.value.games ?? [] : [];
  const totalGames =
    catalogStats.status === "fulfilled" ? catalogStats.value.total_games : 0;

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
        <div className="relative max-w-3xl mx-auto px-6 pt-20 pb-12 text-center">
          <h1
            className="font-serif text-h1 font-bold text-foreground mb-3 leading-tight"
            style={{ letterSpacing: "-0.03em" }}
          >
            Steam, decoded
          </h1>
          <p className="text-base text-muted-foreground mb-8 max-w-lg mx-auto">
            Game intelligence for studios. Sentiment, themes, and market gaps
            across every Steam game.
          </p>
          <WaitlistEmailForm
            variant="hero"
            buttonLabel="Join the Pro waitlist"
            subtext={HERO_SUBTEXT}
          />
          {totalGames > 0 && (
            <p className="mt-6 text-xs font-mono uppercase tracking-widest text-muted-foreground">
              {totalGames.toLocaleString()} games analyzed · Updated daily
            </p>
          )}
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 pb-24 space-y-16">
        {/* Just Analyzed — proof we do real work, gives reason to revisit */}
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

        {/* Market Trends — live charts demonstrate platform capability */}
        <MarketTrendsPreview />

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
