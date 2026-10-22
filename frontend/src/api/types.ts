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

// --- spec 003: match analysis
export type TeamHit = S["TeamOut"];
export type Fixture = S["FixtureOut"];
export type Analysis = S["AnalysisOut"];
export type AnalysisMatch = S["AnalysisMatchOut"];
export type AdviceItem = S["AdviceItemOut"];
export type Reason = S["ReasonOut"];
export type MarketGroup = S["MarketOut"];
export type MarketSelection = S["SelectionOut"];
export type TeamForm = S["TeamFormOut"];
export type FormMatch = S["FormMatchOut"];
export type EventOddsEstimate = S["EstimateOut"];
export type EventOddsRefresh = S["EventRefreshOut"];
export type MarketSummary = S["MarketSummaryOut"];
export type Confidence = "alta" | "media" | "baja";

export const CONFIDENCE_LABEL: Record<Confidence, string> = {
  alta: "Confianza alta",
  media: "Confianza media",
  baja: "Solo información",
};

export const MARKET_LABEL: Record<string, string> = {
  h2h: "1X2",
  double_chance: "Doble oportunidad",
  draw_no_bet: "Empate no apuesta",
  totals: "Más/Menos goles",
  btts: "Ambos marcan",
  team_totals: "Goles de cada equipo",
  european_handicap: "Hándicap europeo",
  correct_score: "Marcador exacto",
};
