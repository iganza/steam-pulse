import Link from "next/link";
import Image from "next/image";
import type { BenchmarkGame } from "@/lib/types";
import { slugifyName } from "./slugify";

interface Props {
  items: BenchmarkGame[];
}

export function BenchmarkGames({ items }: Props) {
  return (
    <section aria-labelledby="benchmarks-heading" className="mb-14">
      <h2
        id="benchmarks-heading"
        className="font-serif text-2xl md:text-3xl font-semibold mb-2"
        style={{ letterSpacing: "-0.02em" }}
      >
        Benchmark Games
      </h2>
      <p className="text-sm text-muted-foreground font-mono mb-6">
        The games the rest of the cohort is measured against.
      </p>
      <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4 list-none p-0">
        {items.map((game) => {
          const slug = slugifyName(game.name);
          const href = `/games/${game.appid}/${slug}`;
          const coverImage = `https://cdn.akamai.steamstatic.com/steam/apps/${game.appid}/header.jpg`;
          return (
            <li key={game.appid}>
              <Link
                href={href}
                className="group flex flex-col rounded-xl overflow-hidden h-full transition-all duration-300 hover:scale-[1.02]"
                style={{ background: "var(--card)", border: "1px solid var(--border)" }}
                prefetch
              >
                <div className="relative aspect-[460/215] overflow-hidden bg-secondary">
                  <Image
                    src={coverImage}
                    alt={`${game.name} cover art`}
                    fill
                    sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 20vw"
                    className="object-cover transition-transform duration-500 group-hover:scale-105"
                  />
                </div>
                <div className="p-4 flex-1 flex flex-col gap-2">
                  <h3 className="font-serif text-base font-semibold line-clamp-1">
                    {game.name}
                  </h3>
                  <p className="text-sm text-foreground/75 line-clamp-4 flex-1">
                    {game.why_benchmark}
                  </p>
                  <span className="text-xs font-mono text-muted-foreground group-hover:text-foreground transition-colors">
                    Read the per-game analysis →
                  </span>
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
