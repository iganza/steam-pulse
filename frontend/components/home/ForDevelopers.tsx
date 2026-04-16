import Link from "next/link";
import { BarChart3, Users, TrendingUp, ChevronRight } from "lucide-react";

const VALUE_PROPS = [
  {
    icon: BarChart3,
    title: "Understand your players",
    description:
      "Review intelligence, sentiment trends, playtime analysis, and churn detection — structured from raw player feedback.",
  },
  {
    icon: Users,
    title: "Know your competition",
    description:
      "Audience overlap reveals which games your reviewers actually play and what they think about them.",
  },
  {
    icon: TrendingUp,
    title: "Read the market",
    description:
      "Genre trends, pricing analysis, release timing patterns, and platform coverage — across the full Steam catalog.",
  },
] as const;

export function ForDevelopers() {
  return (
    <section>
      <div className="text-center mb-8">
        <h2 className="font-serif text-2xl font-semibold mb-2">
          Built for the people who make games
        </h2>
        <p className="text-sm text-muted-foreground max-w-lg mx-auto">
          Game intelligence that helps you ship better, position smarter, and understand your audience.
        </p>
      </div>

      <div className="grid md:grid-cols-3 gap-4 mb-8">
        {VALUE_PROPS.map((prop) => (
          <div
            key={prop.title}
            className="rounded-xl p-5"
            style={{
              background: "var(--card)",
              border: "1px solid var(--border)",
            }}
          >
            <prop.icon className="w-5 h-5 mb-3" style={{ color: "var(--teal)" }} />
            <h3 className="text-sm font-semibold mb-2">{prop.title}</h3>
            <p className="text-xs text-muted-foreground leading-relaxed">
              {prop.description}
            </p>
          </div>
        ))}
      </div>

      <div className="text-center">
        <Link
          href="/pro"
          className="inline-flex items-center gap-1 px-5 py-2.5 rounded-lg text-sm font-medium transition-colors"
          style={{
            background: "var(--teal)",
            color: "var(--background)",
          }}
        >
          Join the Pro waitlist <ChevronRight className="w-3 h-3" />
        </Link>
      </div>
    </section>
  );
}
