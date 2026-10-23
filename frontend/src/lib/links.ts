import type { Outcome } from "../api/types";

export type BetDraft = {
  matchId: string;
  outcome?: Outcome;
  bookmaker?: string;
  odds?: number;
  /** The bet comes from the experimental signal: it is registered as paper by default. */
  fromSignal?: boolean;
};

export function calculatorLink(draft: BetDraft): string {
  const params = new URLSearchParams({ match: draft.matchId });
  if (draft.outcome) params.set("outcome", draft.outcome);
  if (draft.bookmaker) params.set("bookmaker", draft.bookmaker);
  if (draft.odds) params.set("odds", String(draft.odds));
  if (draft.fromSignal) params.set("signal", "1");
  return `/calculator?${params.toString()}`;
}

export function readDraft(params: URLSearchParams): BetDraft | null {
  const matchId = params.get("match");
  if (!matchId) return null;
  const outcome = params.get("outcome");
  const odds = Number(params.get("odds"));
  return {
    matchId,
    outcome: outcome === "home" || outcome === "draw" || outcome === "away" ? outcome : undefined,
    bookmaker: params.get("bookmaker") ?? undefined,
    odds: Number.isFinite(odds) && odds > 1 ? odds : undefined,
    fromSignal: params.get("signal") === "1",
  };
}

/** Link to the match analysis (spec 003); with the match id the analysis uses its date. */
export function analysisLink(home: string, away: string, matchId?: string): string {
  const params = new URLSearchParams({ home, away });
  if (matchId) params.set("match", matchId);
  return `/analysis?${params.toString()}`;
}
