"use client";

import { useState } from "react";
import { Link2, Check } from "lucide-react";

interface Props {
  title: string;
  url: string;
  genreSlug: string;
}

export function ShareButtons({ title, url, genreSlug }: Props) {
  const [copied, setCopied] = useState(false);

  const encodedUrl = encodeURIComponent(url);
  const encodedText = encodeURIComponent(title);
  const twitter = `https://twitter.com/intent/tweet?text=${encodedText}&url=${encodedUrl}`;
  const bluesky = `https://bsky.app/intent/compose?text=${encodeURIComponent(`${title} ${url}`)}`;
  const redditGamedev = `https://www.reddit.com/r/gamedev/submit?title=${encodedText}&url=${encodedUrl}`;
  const redditGenre = `https://www.reddit.com/r/${encodeURIComponent(genreSlug.replace(/-/g, ""))}/submit?title=${encodedText}&url=${encodedUrl}`;

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // no-op — fallback would require a selection trick; not worth the size.
    }
  }

  const btn =
    "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-mono border border-border hover:border-foreground/40 hover:text-foreground transition-colors";

  return (
    <div
      role="group"
      aria-label="Share"
      className="flex flex-wrap gap-2 text-muted-foreground"
    >
      <a href={twitter} target="_blank" rel="noopener noreferrer" className={btn}>
        Share on X
      </a>
      <a href={bluesky} target="_blank" rel="noopener noreferrer" className={btn}>
        Share on Bluesky
      </a>
      <a href={redditGamedev} target="_blank" rel="noopener noreferrer" className={btn}>
        r/gamedev
      </a>
      <a href={redditGenre} target="_blank" rel="noopener noreferrer" className={btn}>
        r/{genreSlug.replace(/-/g, "")}
      </a>
      <button type="button" onClick={onCopy} className={btn} aria-label="Copy link">
        {copied ? <Check className="w-3 h-3" /> : <Link2 className="w-3 h-3" />}
        {copied ? "Copied" : "Copy link"}
      </button>
    </div>
  );
}
