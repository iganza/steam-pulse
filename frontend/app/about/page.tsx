import type { Metadata } from "next";
import { AUTHOR_NAME, STEAM_GAME_NAME, STEAM_GAME_URL } from "@/lib/author";
import { ContactEmail } from "@/components/ContactEmail";

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
            Structured intelligence across the Steam catalog.
          </p>
        </header>

        <section className="space-y-4" id="what">
          <h2 className="text-xs uppercase tracking-widest font-mono text-teal">
            What SteamPulse is
          </h2>
          <p className="text-base text-foreground/80 leading-relaxed">
            SteamPulse is deep market research for indie Steam devs,
            publishers, and the marketers who back them.
          </p>
          <p className="text-base text-foreground/80 leading-relaxed">
            Point it at a game and it returns the design strengths, gameplay
            friction, promise gaps, churn triggers, player wishlists,
            developer priorities, and audience overlap.
          </p>
          <p className="text-base text-foreground/80 leading-relaxed">
            Every point is grounded in the game&apos;s store metadata and
            player reviews.
          </p>
        </section>

        <section className="space-y-4" id="methodology">
          <h2 className="text-xs uppercase tracking-widest font-mono text-teal">
            Methodology
          </h2>
          <p className="text-base text-foreground/80 leading-relaxed">
            Every report starts from public Steam data: store metadata,
            price, tags, and player reviews.
          </p>
          <p className="text-base text-foreground/80 leading-relaxed">
            We process that data with standard analytics and machine-learning
            techniques, then run it through an LLM pipeline that summarizes,
            categorizes, and extracts evidence. A human editor reviews every
            report for quality and consistency before it ships.
          </p>
        </section>

        <section className="space-y-4" id="author">
          <h2 className="text-xs uppercase tracking-widest font-mono text-teal">
            Who made this
          </h2>
          <p className="text-base text-foreground/80 leading-relaxed">
            SteamPulse is built and operated by {AUTHOR_NAME}, a working
            game developer. SteamPulse was built on a break from his own
            game,{" "}
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
            <ContactEmail className="underline underline-offset-2 hover:text-foreground transition-colors" />
            .
          </p>
        </section>
      </main>
    </div>
  );
}
