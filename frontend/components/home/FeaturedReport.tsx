import Link from "next/link";
import { ArrowRight } from "lucide-react";
import type { GenreInsights } from "@/lib/types";

interface Props {
  insights: GenreInsights;
}

export function FeaturedReport({ insights }: Props) {
  const href = `/genre/${insights.slug}`;
  const positivePct = Math.round(insights.avg_positive_pct);
  const medianReviews = insights.median_review_count.toLocaleString();

  return (
    <section>
      <Link
        href={href}
        className="group block rounded-2xl p-8 md:p-10 transition-all duration-200 hover:scale-[1.005]"
        style={{
          background: "var(--card)",
          border: "1px solid var(--border)",
        }}
      >
        <p
          className="text-xs font-mono uppercase tracking-widest mb-4"
          style={{ color: "var(--teal)" }}
        >
          Featured Report · New
        </p>

        <h2
          className="font-serif text-2xl md:text-3xl font-bold mb-4 leading-tight"
          style={{ letterSpacing: "-0.02em" }}
        >
          What {insights.display_name} Players Want, Hate, and Praise
        </h2>

        <p className="text-base text-muted-foreground mb-6 max-w-2xl">
          A whole-niche synthesis of every player review across the
          {" "}{insights.display_name.toLowerCase()} catalog: friction
          patterns, wishlist gaps, benchmark games, and ranked dev priorities.
        </p>

        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 mb-6 text-xs font-mono uppercase tracking-widest text-muted-foreground">
          <span>{insights.input_count} games synthesised</span>
          <span>·</span>
          <span>{positivePct}% positive</span>
          <span>·</span>
          <span>median {medianReviews} reviews/game</span>
        </div>

        <span
          className="inline-flex items-center gap-2 text-sm font-mono uppercase tracking-widest text-foreground group-hover:gap-3 transition-all"
        >
          Read the free synthesis
          <ArrowRight className="w-4 h-4" />
        </span>
      </Link>
    </section>
  );
}
