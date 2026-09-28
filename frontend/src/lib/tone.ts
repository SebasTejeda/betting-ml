/** Text color token for a signed figure (EV, CLV, profit): never the only signal. */
export function evTone(ev: number | null | undefined): string {
  if (ev === null || ev === undefined) return "text-muted-foreground";
  return ev > 0 ? "text-positive" : ev < 0 ? "text-negative" : "text-foreground";
}
