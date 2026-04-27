"use client";

import Link from "next/link";
import { AUTHOR_NAME, METHODOLOGY_PATH } from "@/lib/author";

interface AuthorBylineProps {
  className?: string;
  /** Override the Methodology link target. Defaults to the global
   * `/about#methodology` route; pages with their own methodology section
   * (e.g. the genre synthesis page) can pass a local `#methodology` anchor
   * so the in-page section wins over the cross-page one. */
  href?: string;
}

export function AuthorByline({ className, href }: AuthorBylineProps) {
  return (
    <p
      className={
        className ??
        "text-eyebrow"
      }
      data-testid="author-byline"
    >
      Analysis by{" "}
      <span className="font-medium text-foreground">{AUTHOR_NAME}</span>
      {" · "}
      <Link
        href={href ?? METHODOLOGY_PATH}
        className="underline underline-offset-2 hover:text-foreground transition-colors"
      >
        Methodology &rarr;
      </Link>
    </p>
  );
}
