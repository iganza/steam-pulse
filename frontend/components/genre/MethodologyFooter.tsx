import { ContactEmail } from "@/components/ContactEmail";

interface Props {
  displayName: string;
  inputCount: number;
}

export function MethodologyFooter({ displayName, inputCount }: Props) {
  return (
    <section
      id="methodology"
      className="mt-20 pt-10 text-sm leading-relaxed"
      style={{ borderTop: "1px solid var(--border)", color: "var(--muted-foreground)" }}
      data-testid="methodology-footer"
    >
      <h2
        className="font-serif text-xl font-semibold mb-4"
        style={{ color: "var(--foreground)" }}
      >
        Methodology
      </h2>
      <p className="mb-3 max-w-prose">
        This synthesis runs a three-phase LLM pipeline over the {inputCount} {displayName} games in
        the SteamPulse catalog: per-game review mining (Phase 3), cross-game pattern clustering
        (Phase 4), and a curation pass before publication. Only friction and wishlist clusters with
        <code className="mx-1 px-1 py-0.5 rounded font-mono text-xs" style={{ background: "var(--secondary)" }}>
          mention_count &ge; 3
        </code>
        across distinct games ship on the page.
      </p>
      <p className="mb-3 max-w-prose">
        The synthesis refreshes weekly; the editorial framing above is written by a human and
        persists across refreshes. Per-game source reports are linked inline so you can verify
        every quote in context.
      </p>
      <p className="max-w-prose">
        Notice an issue? Email{" "}
        <ContactEmail className="underline underline-offset-2 hover:text-foreground transition-colors" />
        .
      </p>
    </section>
  );
}
