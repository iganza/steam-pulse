// Okabe-Ito colorblind-safe categorical palette (8 colors).
// https://jfly.uni-koeln.de/color/
// Ordered so adjacent series in a chart have high discriminability.
export const BUILDER_PALETTE = [
  "#0072B2", // blue
  "#E69F00", // orange
  "#009E73", // bluish green
  "#CC79A7", // reddish purple
  "#56B4E9", // sky blue
  "#D55E00", // vermillion
  "#F0E442", // yellow
  "#000000", // black
];

export function colorForIndex(i: number): string {
  return BUILDER_PALETTE[i % BUILDER_PALETTE.length];
}
