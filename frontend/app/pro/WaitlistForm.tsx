"use client";

import { useState } from "react";
import { Mail } from "lucide-react";

type Status = "idle" | "loading" | "success" | "already_registered" | "error";

export default function WaitlistForm() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>("idle");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email) return;

    setStatus("loading");
    try {
      const res = await fetch("/api/waitlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (!res.ok) {
        setStatus("error");
        return;
      }
      const data = await res.json();
      setStatus(data.status === "already_registered" ? "already_registered" : "success");
    } catch {
      setStatus("error");
    }
  }

  if (status === "success" || status === "already_registered") {
    return (
      <p className="text-base font-mono" style={{ color: "var(--teal)" }}>
        {status === "already_registered"
          ? "You're already on the list — we'll be in touch."
          : "You're on the list. We'll email you when Pro launches."}
      </p>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-center gap-2 max-w-sm mx-auto">
      <div className="relative flex-1">
        <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="your@email.com"
          disabled={status === "loading"}
          className="w-full pl-10 pr-3 py-3 rounded-lg bg-card border border-border text-base text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-teal-400/30 disabled:opacity-60"
        />
      </div>
      <button
        type="submit"
        disabled={status === "loading"}
        className="px-5 py-3 rounded-lg text-base font-mono font-medium flex-shrink-0 disabled:opacity-60"
        style={{ background: "var(--teal)", color: "#0c0c0f" }}
      >
        {status === "loading" ? "..." : "Notify me"}
      </button>
      {status === "error" && (
        <p className="text-sm text-red-400 mt-2 absolute">Something went wrong — please try again.</p>
      )}
    </form>
  );
}
