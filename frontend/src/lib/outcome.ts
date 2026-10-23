/** 1X2 tones shared by bars and charts. Neutral on purpose: a probability is not a
 *  recommendation (constitution XIII), and amber/green already mean "experimental"/"gain". */
export const OUTCOME_TONE = {
  home: "bg-primary",
  draw: "bg-muted-foreground/45",
  away: "bg-chart-2",
} as const;

export const OUTCOME_STROKE = {
  home: "var(--chart-1)",
  draw: "var(--muted-foreground)",
  away: "var(--chart-2)",
} as const;
