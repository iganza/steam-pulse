import { FileText, Layers, Sparkles } from "lucide-react";

interface Capability {
  icon: typeof FileText;
  title: string;
  body?: string;
  teaser?: boolean;
}

const PRO_CAPABILITIES: Capability[] = [
  {
    icon: FileText,
    title: "Reports on any game",
    body: "Full intelligence report for any game in the catalog, on demand.",
  },
  {
    icon: Layers,
    title: "Reports across a genre",
    body: "Full market analysis covering an entire genre.",
  },
  {
    icon: Sparkles,
    title: "More on the way",
    teaser: true,
  },
];

export function ProPreview() {
  return (
    <section aria-labelledby="pro-preview-heading">
      <div className="flex items-baseline justify-between flex-wrap gap-3 mb-3">
        <h2
          id="pro-preview-heading"
          className="font-serif text-lg font-semibold"
        >
          What&apos;s in Pro
        </h2>
        <p className="text-xs font-mono uppercase tracking-widest text-muted-foreground">
          Free reports stay free
        </p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {PRO_CAPABILITIES.map(({ icon: Icon, title, body, teaser }) => (
          <div
            key={title}
            className="rounded-xl p-4 flex gap-3"
            style={{
              background: "var(--card)",
              border: teaser
                ? "1px dashed var(--border)"
                : "1px solid var(--border)",
              opacity: teaser ? 0.7 : 1,
            }}
          >
            <Icon className="w-4 h-4 text-teal shrink-0 mt-0.5" />
            <div>
              <h3 className="font-serif text-sm font-semibold text-foreground mb-1 leading-snug">
                {title}
              </h3>
              {body && (
                <p className="text-xs text-foreground/75 leading-relaxed">
                  {body}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
