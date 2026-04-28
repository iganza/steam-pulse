import type { Metadata } from "next";
import {
  AUTHOR_NAME,
  CONTACT_EMAIL,
  STEAM_GAME_NAME,
  STEAM_GAME_URL,
} from "@/lib/author";

export const metadata: Metadata = {
  title: "About SteamPulse · Methodology",
  description:
    "How SteamPulse turns Steam reviews into structured game intelligence: methodology, sources, and who builds it.",
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
            className="font-serif text-h1 font-bold text-foreground mb-4 leading-tight"
            style={{ letterSpacing: "-0.03em" }}
          >
            About SteamPulse
          </h1>
          <p className="text-base text-muted-foreground leading-relaxed">
            Structured player intelligence across the Steam catalog.
          </p>
        </header>

        <section className="space-y-4" id="what">
          <h2 className="text-xs uppercase tracking-widest font-mono text-teal">
            What SteamPulse is
          </h2>
          <p className="text-base text-foreground/80 leading-relaxed">
            SteamPulse is deep market research for indie Steam devs. Point it
            at a game and it returns the design strengths, gameplay friction,
            churn triggers, player wishlists, and developer priorities. Every
            claim is anchored to a counted review quote.
          </p>
          <p className="text-base text-foreground/80 leading-relaxed">
            Each report is produced through automated review-corpus analysis
            and benchmarked against its genre cohort. A human editor reviews
            every published synthesis before it ships. The pipeline is
            AI-assisted, not AI-only.
          </p>
        </section>

        <section className="space-y-4" id="methodology">
          <h2 className="text-xs uppercase tracking-widest font-mono text-teal">
            Methodology
          </h2>
          <p className="text-base text-foreground/80 leading-relaxed">
            Every report starts from public Steam data (store metadata, price,
            tags, and the full review corpus) and combines automated
            review-corpus analysis with editorial review. Cross-game patterns
            are surfaced only when there is sufficient supporting evidence
            across the corpus, so anecdotes never pose as trends.
          </p>
          <p className="text-base text-foreground/80 leading-relaxed">
            Steam-sourced facts (sentiment %, review totals, recent trend,
            playtime distribution) are shown as reported by Steam, with
            per-source crawl timestamps. LLM-synthesised facts are labelled
            separately so you always know what is data and what is
            interpretation. Known limitations: sample skews toward reviewers
            who post publicly on Steam, recent-review weighting trails behind
            a week or two, and the corpus is Steam-only.
          </p>
        </section>

        <section className="space-y-4" id="author">
          <h2 className="text-xs uppercase tracking-widest font-mono text-teal">
            Who made this
          </h2>
          <p className="text-base text-foreground/80 leading-relaxed">
            SteamPulse is built and operated by {AUTHOR_NAME}, a one-person
            shop. SteamPulse was built on a break from his own game,{" "}
            <a
              href={STEAM_GAME_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="text-teal underline underline-offset-2 hover:text-foreground transition-colors"
            >
              {STEAM_GAME_NAME}
            </a>
            , currently in development with a free demo on Steam.
          </p>
        </section>

        <section className="space-y-4" id="contact">
          <h2 className="text-xs uppercase tracking-widest font-mono text-teal">
            Contact
          </h2>
          <p className="text-base text-foreground/80 leading-relaxed">
            Questions, corrections, or a report request:{" "}
            <a
              href={`mailto:${CONTACT_EMAIL}`}
              className="underline underline-offset-2 hover:text-foreground transition-colors"
            >
              {CONTACT_EMAIL}
            </a>
            .
          </p>
        </section>
      </main>
    </div>
  );
}
