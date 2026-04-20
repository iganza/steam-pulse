import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "About SteamPulse",
  description:
    "How SteamPulse turns Steam reviews into structured game intelligence — methodology, sources, and who builds it.",
  alternates: {
    canonical: "https://steampulse.io/about",
  },
};

export default function AboutPage() {
  return (
    <div className="min-h-screen bg-background">
      <main className="max-w-2xl mx-auto px-6 py-20 space-y-10">
        <header>
          <h1
            className="font-serif text-4xl md:text-5xl font-bold text-foreground mb-4 leading-tight"
            style={{ letterSpacing: "-0.03em" }}
          >
            About SteamPulse
          </h1>
          <p className="text-base text-muted-foreground leading-relaxed">
            Structured player intelligence across the Steam catalog.
          </p>
        </header>

        <section className="space-y-4">
          <h2
            className="text-xs uppercase tracking-widest font-mono"
            style={{ color: "var(--teal)" }}
          >
            Methodology
          </h2>
          <p className="text-base text-foreground/80 leading-relaxed">
            Every report starts from public Steam data — store metadata, price,
            tags, and the full review corpus — and passes it through a chain of
            language models that cluster, summarise, and verify player
            sentiment. We extract design strengths, gameplay friction, churn
            triggers, player wishlists, and developer priorities, then
            benchmark each game against its genre cohort. Every claim is
            anchored in a counted review quote.
          </p>
          <p className="text-base text-foreground/80 leading-relaxed">
            Steam-sourced facts (sentiment %, review totals, recent trend,
            playtime distribution) are shown as reported by Steam, with
            per-source crawl timestamps. LLM-synthesised facts are labelled
            separately so you always know what is data and what is
            interpretation.
          </p>
        </section>

        <section className="space-y-4">
          <h2
            className="text-xs uppercase tracking-widest font-mono"
            style={{ color: "var(--teal)" }}
          >
            Who runs it
          </h2>
          <p className="text-base text-foreground/80 leading-relaxed">
            SteamPulse is built and operated by Ivan Z. Ganza — a one-person
            shop. Reports are produced offline and sold as catalog PDFs; the
            rest of the site is free.
          </p>
        </section>
      </main>
    </div>
  );
}
