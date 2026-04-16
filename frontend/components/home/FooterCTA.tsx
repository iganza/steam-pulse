import { HeroSearch } from "@/components/layout/HeroSearch";

export function FooterCTA() {
  return (
    <section className="text-center py-12">
      <h2 className="font-serif text-2xl font-semibold mb-2">
        100,000+ games. Free to explore.
      </h2>
      <p className="text-sm text-muted-foreground mb-6">
        Search any Steam game and see what players really think.
      </p>
      <div className="max-w-xl mx-auto">
        <HeroSearch />
      </div>
    </section>
  );
}
