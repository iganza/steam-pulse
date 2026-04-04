import { FlaskConical } from "lucide-react";

interface EarlyAccessBadgeProps {
  className?: string;
}

export function EarlyAccessBadge({ className = "" }: EarlyAccessBadgeProps) {
  return (
    <span
      data-testid="early-access-badge"
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono uppercase tracking-widest ${className}`}
      style={{
        background: "rgba(56, 152, 236, 0.15)",
        border: "1px solid rgba(56, 152, 236, 0.4)",
        color: "#3898ec",
      }}
    >
      <FlaskConical className="w-3 h-3" />
      Early Access
    </span>
  );
}
