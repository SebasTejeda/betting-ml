import type { components } from "./schema";

type S = components["schemas"];

export type Outcome = "home" | "draw" | "away";
export type Triple = S["betting_ml__api__schemas_002__Triple"];
export type Bookmaker = S["BookmakerOut"];
export type Budget = S["BudgetOut"];
export type RefreshResult = S["RefreshOut"];
export type Comparator = S["ComparatorOut"];
export type ComparatorMatch = S["ComparatorMatchOut"];
export type ComparatorDetail = S["ComparatorDetailOut"];
export type CalculatorIn = S["CalculatorIn"];
export type CalculatorResult = S["CalculatorOut"];
export type BetIn = S["BetIn"];
export type Bet = S["BetOut"];
export type BetPage = S["BetPage"];
export type BetPatch = S["BetPatch"];
export type SettleResult = S["SettleOut"];
export type Summary = S["SummaryOut"];
export type Settings = S["SettingsOut"];
export type SettingsIn = S["SettingsIO"];

export const OUTCOMES: Outcome[] = ["home", "draw", "away"];
export const OUTCOME_LABEL: Record<Outcome, string> = {
  home: "Local",
  draw: "Empate",
  away: "Visita",
};
