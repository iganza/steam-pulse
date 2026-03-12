import { Gem } from "lucide-react";

interface HiddenGemBadgeProps {
  score: number;
  className?: string;
}

function getGemLabel(score: number): string {
  if (score >= 85) return "Hidden Gem";
  if (score >= 70) return "Underrated";
  if (score >= 50) return "Worth a Look";
  return "";
}

export function HiddenGemBadge({ score, className = "" }: HiddenGemBadgeProps) {
  const label = getGemLabel(score);
  if (!label) return null;

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono uppercase tracking-widest ${className}`}
      style={{
        background: "rgba(201, 151, 60, 0.12)",
        border: "1px solid rgba(201, 151, 60, 0.35)",
        color: "#c9973c",
      }}
    >
      <Gem className="w-3 h-3" />
      {label} · {score}
    </span>
  );
}
