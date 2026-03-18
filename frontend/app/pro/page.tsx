import type { Metadata } from "next";
import { BarChart3, Swords, TrendingUp, Mail } from "lucide-react";

export const metadata: Metadata = {
  title: "Pro \u2014 For Developers",
  description: "SteamPulse Pro: genre intelligence, developer analytics, and trend analysis for game developers.",
  openGraph: {
    title: "SteamPulse Pro — Game Intelligence for Developers",
    description: "Genre intelligence, developer analytics, and trend analysis for indie game developers.",
    url: "https://steampulse.io/pro",
    images: [{ url: "/og-default.png", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "SteamPulse Pro — Game Intelligence for Developers",
    description: "Genre intelligence, developer analytics, and trend analysis for indie game developers.",
  },
  alternates: { canonical: "https://steampulse.io/pro" },
};

const features = [
  {
    icon: <BarChart3 className="w-6 h-6" />,
    title: "Genre Intelligence",
    description: "Competitive analysis across entire genres. See what players want that no game currently delivers. Identify whitespace opportunities and feature gaps.",
  },
  {
    icon: <Swords className="w-6 h-6" />,
    title: "Developer Intelligence",
    description: "Cross-portfolio analysis for any developer. Understand sentiment patterns, track competitor catalogs, and benchmark your games against the field.",
  },
  {
    icon: <TrendingUp className="w-6 h-6" />,
    title: "Trend Analysis",
    description: "Track what\u2019s rising and falling across the Steam catalog. Spot emerging player preferences before they become obvious. Weekly trend reports delivered to your inbox.",
  },
];

export default function ProPage() {
  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-3xl mx-auto px-6 py-20">
        <p className="font-mono text-[11px] uppercase tracking-[0.25em] text-muted-foreground mb-4 text-center">
          SteamPulse Pro
        </p>
        <h1
          className="font-serif text-4xl md:text-5xl font-bold text-foreground mb-6 leading-tight text-center"
          style={{ letterSpacing: "-0.03em" }}
        >
          Intelligence for
          <br />
          <span style={{ color: "var(--teal)" }}>game developers</span>
        </h1>
        <p className="text-base text-muted-foreground leading-relaxed text-center max-w-lg mx-auto mb-16">
          Go beyond per-game reports. Analyze entire genres, track competitors, and spot trends across the Steam catalog.
        </p>

        <div className="space-y-8 mb-20">
          {features.map((feature) => (
            <div
              key={feature.title}
              className="p-6 rounded-xl"
              style={{ background: "var(--card)", border: "1px solid var(--border)" }}
            >
              <div className="flex items-start gap-4">
                <div
                  className="flex-shrink-0 w-10 h-10 rounded-lg flex items-center justify-center"
                  style={{
                    background: "rgba(45,185,212,0.1)",
                    color: "var(--teal)",
                  }}
                >
                  {feature.icon}
                </div>
                <div>
                  <h2 className="font-serif text-lg font-semibold mb-2">{feature.title}</h2>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    {feature.description}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Waitlist CTA */}
        <div className="text-center">
          <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground mb-4">
            Coming soon
          </p>
          <h2 className="font-serif text-2xl font-bold mb-6">Join the waitlist</h2>
          <div className="flex items-center gap-2 max-w-sm mx-auto">
            <div className="relative flex-1">
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
              <input
                type="email"
                placeholder="your@email.com"
                className="w-full pl-10 pr-3 py-3 rounded-lg bg-card border border-border text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-teal-400/30"
              />
            </div>
            <button
              type="button"
              className="px-5 py-3 rounded-lg text-sm font-mono font-medium flex-shrink-0"
              style={{ background: "var(--teal)", color: "#0c0c0f" }}
            >
              Notify me
            </button>
          </div>
          <p className="text-xs text-muted-foreground mt-3">
            No spam. We&apos;ll email you once when Pro launches.
          </p>
        </div>
      </div>
    </div>
  );
}
