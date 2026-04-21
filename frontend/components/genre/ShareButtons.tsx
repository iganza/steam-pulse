"use client";

import { useState } from "react";
import { Link as LinkIcon, Check } from "lucide-react";

interface Props {
  url: string;
  title: string;
  subredditSlug?: string;
}

export function ShareButtons({ url, title, subredditSlug }: Props) {
  const [copied, setCopied] = useState(false);
  const encodedUrl = encodeURIComponent(url);
  const encodedTitle = encodeURIComponent(title);

  const twitter = `https://twitter.com/intent/tweet?text=${encodedTitle}&url=${encodedUrl}`;
  const bluesky = `https://bsky.app/intent/compose?text=${encodedTitle}%20${encodedUrl}`;
  const redditGamedev = `https://www.reddit.com/r/gamedev/submit?title=${encodedTitle}&url=${encodedUrl}`;
  const redditGenre = subredditSlug
    ? `https://www.reddit.com/r/${subredditSlug}/submit?title=${encodedTitle}&url=${encodedUrl}`
    : null;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard API unavailable — silently skip
    }
  };

  const btn =
    "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-mono uppercase tracking-widest transition-colors";
  const btnStyle = {
    background: "var(--card)",
    border: "1px solid var(--border)",
    color: "var(--foreground)",
  };

  return (
    <div
      className="flex flex-wrap gap-2"
      data-testid="share-buttons"
    >
      <a className={btn} style={btnStyle} href={twitter} target="_blank" rel="noopener noreferrer">Twitter / X</a>
      <a className={btn} style={btnStyle} href={bluesky} target="_blank" rel="noopener noreferrer">Bluesky</a>
      <a className={btn} style={btnStyle} href={redditGamedev} target="_blank" rel="noopener noreferrer">r/gamedev</a>
      {redditGenre && (
        <a className={btn} style={btnStyle} href={redditGenre} target="_blank" rel="noopener noreferrer">
          r/{subredditSlug}
        </a>
      )}
      <button type="button" className={btn} style={btnStyle} onClick={copy}>
        {copied ? <Check className="w-3 h-3" /> : <LinkIcon className="w-3 h-3" />}
        {copied ? "Copied" : "Copy link"}
      </button>
    </div>
  );
}
