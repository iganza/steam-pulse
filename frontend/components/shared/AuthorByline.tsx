import Link from "next/link";
import { AUTHOR_NAME, METHODOLOGY_PATH } from "@/lib/author";

interface AuthorBylineProps {
  className?: string;
}

export function AuthorByline({ className }: AuthorBylineProps) {
  return (
    <p
      className={
        className ??
        "text-xs font-mono uppercase tracking-widest text-muted-foreground"
      }
      data-testid="author-byline"
    >
      Analysis by{" "}
      <span className="font-medium text-foreground">{AUTHOR_NAME}</span>
      {" · "}
      <Link
        href={METHODOLOGY_PATH}
        className="underline underline-offset-2 hover:text-foreground transition-colors"
      >
        Methodology &rarr;
      </Link>
    </p>
  );
}
