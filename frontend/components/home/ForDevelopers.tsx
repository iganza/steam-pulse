import Link from "next/link";
import { ArrowRight, Eye, Users, LineChart } from "lucide-react";

interface ValueProp {
  icon: React.ReactNode;
  title: string;
  body: string;
}

const VALUE_PROPS: ValueProp[] = [
  {
    icon: <Eye className="w-4 h-4 text-teal" />,
    title: "Understand your players",
    body: "Review intelligence, sentiment trends, playtime analysis, churn detection.",
  },
  {
    icon: <Users className="w-4 h-4 text-teal" />,
    title: "Know your competition",
    body: "Audience overlap shows which games your reviewers actually play.",
  },
  {
    icon: <LineChart className="w-4 h-4 text-teal" />,
    title: "Read the market",
    body: "Genre trends, pricing analysis, release timing, platform coverage.",
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
      <div className="mb-8">
        <p className="text-xs font-mono uppercase tracking-widest mb-2 text-teal">
          For game developers
        </p>
        <h2 className="font-serif text-2xl md:text-3xl font-semibold text-foreground">
          Built for the people who make games
        </h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        {VALUE_PROPS.map((vp) => (
          <div key={vp.title} className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              {vp.icon}
              <h3 className="text-sm font-semibold text-foreground">{vp.title}</h3>
            </div>
            <p className="text-sm text-muted-foreground leading-relaxed">
              {vp.body}
            </p>
          </div>
        ))}
      </div>

      <Link
        href="/pro"
        className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-mono uppercase tracking-wider transition-all duration-200 hover:scale-[1.02] bg-teal text-background"
      >
        Join the Pro waitlist
        <ArrowRight className="w-4 h-4" />
      </Link>
    </section>
  );
}
