"use client";

import {
  BarChart3,
  Swords,
  Table,
  Target,
  PieChart,
  TrendingUp,
  Hammer,
} from "lucide-react";

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  BarChart3,
  Swords,
  Table,
  Target,
  PieChart,
  TrendingUp,
  Hammer,
};

export function LensIcon({
  name,
  className,
}: {
  name: string;
  className?: string;
}) {
  const Icon = ICON_MAP[name];
  if (!Icon) return null;
  return <Icon className={className} />;
}
