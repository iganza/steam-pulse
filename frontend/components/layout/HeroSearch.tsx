"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { SearchAutocomplete } from "./SearchAutocomplete";

export function HeroSearch() {
  const [query, setQuery] = useState("");
  const router = useRouter();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (query.trim()) router.push(`/search?q=${encodeURIComponent(query.trim())}`);
  }

  return (
    <SearchAutocomplete
      value={query}
      onChange={setQuery}
      onSubmit={handleSubmit}
      className="max-w-xl mx-auto"
      inputClassName="py-4 text-base"
      placeholder="Search 100,000+ Steam games..."
    />
  );
}
