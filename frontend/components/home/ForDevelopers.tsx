import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowRight, BarChart3, Users, TrendingUp } from "lucide-react";

interface ValueProp {
  icon: ReactNode;
  title: string;
  body: string;
}

const VALUE_PROPS: ValueProp[] = [
  {
    icon: <BarChart3 className="w-4 h-4" style={{ color: "var(--teal)" }} />,
    title: "Understand your players",
    body: "Review intelligence, sentiment trends, playtime analysis, and churn detection — distilled from every English-language review.",
  },
  {
    icon: <Users className="w-4 h-4" style={{ color: "var(--teal)" }} />,
    title: "Know your competition",
    body: "Audience overlap shows which games your reviewers actually play. Real reviewer behavior, not survey data.",
  },
  {
    icon: <TrendingUp className="w-4 h-4" style={{ color: "var(--teal)" }} />,
    title: "Read the market",
    body: "Genre trends, pricing analysis, release timing, and platform coverage — across the entire Steam catalog.",
  },
];

export function ForDevelopers() {
  return (
    <section
      className="rounded-2xl p-8 md:p-10"
      style={{
        background: "var(--card)",
        border: "1px solid var(--border)",
      }}
    >
      <p
        className="text-xs font-mono uppercase tracking-widest mb-4"
        style={{ color: "var(--teal)" }}
      >
        For game developers
      </p>

      <h2
        className="font-serif text-2xl md:text-3xl font-bold mb-6 leading-tight"
        style={{ letterSpacing: "-0.02em" }}
      >
        Built for the people who make games
      </h2>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        {VALUE_PROPS.map((prop) => (
          <div
            key={prop.title}
            className="rounded-xl p-5"
            style={{
              background: "var(--background)",
              border: "1px solid var(--border)",
            }}
          >
            <div className="flex items-center gap-2 mb-2">
              {prop.icon}
              <h3 className="text-sm font-semibold text-foreground">
                {prop.title}
              </h3>
            </div>
            <p className="text-sm text-muted-foreground leading-relaxed">
              {prop.body}
            </p>
          </div>
        ))}
      </div>

      <Link
        href="/pro"
        className="group inline-flex items-center gap-2 rounded-xl px-5 py-3 text-sm font-mono uppercase tracking-widest transition-all hover:gap-3"
        style={{
          background: "var(--teal)",
          color: "var(--background)",
        }}
      >
        Join the Pro waitlist
        <ArrowRight className="w-4 h-4" />
      </Link>
    </section>
  );
}
