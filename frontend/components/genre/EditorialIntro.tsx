import { AuthorByline } from "@/components/shared/AuthorByline";
import { ShareButtons } from "@/components/genre/ShareButtons";
import type { GenreInsights } from "@/lib/types";

interface Props {
  insights: GenreInsights;
  shareUrl: string;
}

export function EditorialIntro({ insights, shareUrl }: Props) {
  const intro = insights.editorial_intro.trim() || insights.narrative_summary;
  const updated = new Date(insights.computed_at).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <header className="mb-12">
      <h1
        className="font-serif text-4xl md:text-5xl font-bold mb-4"
        style={{ letterSpacing: "-0.03em" }}
      >
        What {insights.display_name} Players Want, Hate, and Praise
      </h1>

      <AuthorByline />

      <div className="mt-8 space-y-4 text-base leading-relaxed max-w-prose">
        {intro.split(/\n\n+/).map((para, i) => (
          <p key={i}>{para}</p>
        ))}
      </div>

      <p
        className="mt-6 text-xs font-mono uppercase tracking-widest"
        style={{ color: "var(--muted-foreground)" }}
      >
        Synthesised from {insights.input_count} games · median {insights.median_review_count.toLocaleString()} reviews/game · last updated {updated}
      </p>

      <div className="mt-6">
        <ShareButtons url={shareUrl} title={`What ${insights.display_name} Players Want, Hate, and Praise`} />
      </div>
    </header>
  );
}
