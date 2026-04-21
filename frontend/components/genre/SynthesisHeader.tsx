import { ShareButtons } from "./ShareButtons";
import type { GenreSynthesisRow } from "@/lib/types";

interface Props {
  row: GenreSynthesisRow;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function SynthesisHeader({ row }: Props) {
  const pageUrl = `https://steampulse.io/genre/${row.slug}/`;
  const title = `What ${row.display_name} Players Want, Hate, and Praise`;

  return (
    <header className="mb-10">
      <h1
        className="font-serif text-3xl md:text-5xl font-bold mb-5 leading-tight"
        style={{ letterSpacing: "-0.03em" }}
      >
        {title}
      </h1>
      <p className="text-base md:text-lg text-foreground/80 mb-5 max-w-[62ch]">
        {row.narrative_summary}
      </p>
      <p className="text-sm text-muted-foreground font-mono mb-5">
        Synthesised from {row.input_count.toLocaleString()} games · median{" "}
        {row.median_review_count.toLocaleString()} reviews per game · last updated{" "}
        {formatDate(row.computed_at)}
      </p>
      <ShareButtons title={title} url={pageUrl} genreSlug={row.slug} />
    </header>
  );
}
