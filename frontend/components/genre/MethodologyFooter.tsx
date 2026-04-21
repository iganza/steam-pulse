export function MethodologyFooter() {
  return (
    <footer
      aria-labelledby="methodology-heading"
      className="mt-4 pt-8 border-t border-border text-sm text-muted-foreground max-w-[72ch]"
    >
      <h2
        id="methodology-heading"
        className="font-serif text-lg font-semibold text-foreground mb-3"
      >
        How this page is built
      </h2>
      <p className="mb-3">
        A three-phase LLM pipeline synthesises the review corpus of every qualifying
        game in the cohort. Per-game reports are merged into cross-genre patterns;
        only signals that surface in at least three games make the cut. Every
        friction, wishlist, benchmark, and churn claim links back to the specific
        per-game analysis it came from.
      </p>
      <p className="mb-3">
        The synthesis refreshes weekly as new reviews and new games enter the cohort.
      </p>
      <p>
        Notice an issue? Email{" "}
        <a
          href="mailto:feedback@steampulse.io"
          className="underline hover:text-foreground"
        >
          feedback@steampulse.io
        </a>
        .
      </p>
    </footer>
  );
}
