"use client";

import { useEffect, useState } from "react";
import { CONTACT_EMAIL } from "@/lib/author";

interface Props {
  className?: string;
}

export function ContactEmail({ className }: Props) {
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    setHydrated(true);
  }, []);

  const [user, domain] = CONTACT_EMAIL.split("@");

  if (!hydrated) {
    return (
      <span className={className}>
        {user} [at] {domain}
      </span>
    );
  }
  return (
    <a href={`mailto:${user}@${domain}`} className={className}>
      {user}@{domain}
    </a>
  );
}
