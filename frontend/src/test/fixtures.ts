import type {
  AdviceItem,
  Analysis,
  MarketSummary,
  TeamForm,
  Bet,
  Bookmaker,
  Budget,
  CalculatorResult,
  Comparator,
  ComparatorDetail,
  Settings,
  Summary,
} from "../api/types";

export const MATCH_ID = "E0-2026-10-10-arsenal-chelsea";

export const leagues = [
  { code: "E0", name: "Premier League", country: "England", teams: 20 },
  { code: "SP1", name: "La Liga", country: "Spain", teams: 20 },
];

export const budget: Budget = {
  credits_remaining: 498,
  credits_used_month: 2,
  min_reserve: 50,
  last_refresh: "2026-10-09T13:02:00Z",
  low: false,
};

export const bookmakers: Bookmaker[] = [
  { key: "pinnacle", name: "Pinnacle", role: "reference", accessible: false, source: "api" },
  { key: "betsson", name: "Betsson", role: "soft", accessible: true, source: "api" },
  { key: "teapuesto", name: "Te Apuesto", role: "soft", accessible: true, source: "manual" },
  { key: "inkabet", name: "Inkabet", role: "soft", accessible: true, source: "manual" },
];

const match = {
  match_id: MATCH_ID,
  league: "E0",
  kickoff: "2026-10-10T11:30:00Z",
  home_team: "Arsenal",
  away_team: "Chelsea",
  fair: {
    source: "pinnacle",
    probabilities: { home: 0.514, draw: 0.256, away: 0.23 },
    odds: { home: 1.95, draw: 3.91, away: 4.35 },
  },
  model: { probabilities: { home: 0.51, draw: 0.25, away: 0.24 }, version: "E12-test" },
  best: {
    home: { bookmaker: "betsson", odds: 1.98, ev: 0.0177 },
    draw: { bookmaker: "coolbet", odds: 3.95, ev: 0.0112 },
    away: { bookmaker: "betsson", odds: 4.6, ev: 0.058 },
  },
  margins: { best_combined: 0.0035, average: 0.048, best_vs_average_uplift: 0.041 },
  experimental_signal: {
    label: "EXPERIMENTAL — solo papel",
    bets: [
      {
        outcome: "away" as const,
        bookmaker: "betsson",
        odds: 4.6,
        ev: 0.058,
        model_agrees: true,
        suggested_stake: 2.01,
      },
    ],
  },
  warning: null,
};

export const comparator: Comparator = {
  date: "2026-10-10",
  snapshot_at: "2026-10-09T13:02:00Z",
  reference: "pinnacle",
  count: 2,
  matches: [
    match,
    {
      ...match,
      match_id: "E0-2026-10-10-leeds-everton",
      home_team: "Leeds",
      away_team: "Everton",
      fair: null,
      experimental_signal: null,
      warning: "Sin cuota de referencia",
    },
  ],
};

export const detail: ComparatorDetail = {
  ...match,
  bookmakers: [
    {
      key: "betsson",
      accessible: true,
      odds: { home: 1.98, draw: 3.4, away: 4.6 },
      margin: 0.0166,
      updated_at: "2026-10-09T13:00:00Z",
    },
    {
      key: "pinnacle",
      accessible: false,
      odds: { home: 1.95, draw: 3.85, away: 4.3 },
      margin: 0.0249,
      updated_at: "2026-10-09T13:00:00Z",
    },
  ],
  reference_history: [
    { at: "2026-10-08T20:00:00Z", odds: { home: 1.97, draw: 3.9, away: 4.3 } },
    { at: "2026-10-09T13:00:00Z", odds: { home: 1.95, draw: 3.85, away: 4.3 } },
  ],
};

export const calculation: CalculatorResult = {
  fair_probability: 0.23,
  fair_odds: 4.35,
  ev: 0.012,
  verdict: "justo",
  experimental: true,
  label: "EXPERIMENTAL — solo papel",
  suggested_stake: 0,
  model_probability: 0.2333,
  model_agrees: true,
  reference: "pinnacle",
  best_available: { bookmaker: "betsson", odds: 4.6, ev: 0.058 },
};

export function bet(overrides: Partial<Bet> = {}): Bet {
  return {
    id: 1,
    created_at: "2026-10-09T15:00:00Z",
    match_id: MATCH_ID,
    league: "E0",
    home_team: "Arsenal",
    away_team: "Chelsea",
    kickoff: "2026-10-10T11:30:00Z",
    outcome: "away",
    market: "h2h",
    bookmaker: "teapuesto",
    odds: 4.4,
    stake: 5,
    kind: "real",
    status: "pendiente",
    note: null,
    from_experimental_signal: false,
    fair_probability: 0.23,
    ev: 0.012,
    clv: null,
    clv_source: null,
    profit: null,
    settled_at: null,
    result_source: null,
    sin_referencia: false,
    version: 1,
    warnings: [],
    ...overrides,
  };
}

export const summary: Summary = {
  bets: 12,
  settled: 10,
  staked: 100,
  profit: -8.4,
  roi: -0.084,
  clv_mean: 0.021,
  clv_positive_rate: 0.6,
  bankroll: {
    initial: 500,
    current: 491.6,
    series: [
      { date: "2026-10-01", value: 500 },
      { date: "2026-10-05", value: 491.6 },
    ],
  },
  by_league: [{ league: "E0", bets: 10, roi: -0.08, clv_mean: 0.02 }],
  by_market: [],
  by_bookmaker: [{ bookmaker: "teapuesto", bets: 10, roi: -0.08, clv_mean: 0.02 }],
  month: { loss_limit: 100, current_loss: 8.4, remaining: 91.6 },
  experimental_signal: { paper_bets: 23, target: 100, clv_mean: 0.012, evidence_met: false },
  best_odds_uplift_mean: 0.038,
  note: "Con menos de 300 apuestas el ROI es mayormente ruido; mira el CLV.",
};

export const settings: Settings = {
  bankroll_initial: 500,
  currency: "PEN",
  monthly_loss_limit: 100,
  max_stake_pct: 0.02,
  kelly_fraction: 0.25,
  min_edge: 0.02,
  version: 3,
  monthly_loss_limit_in_force: 100,
};

// --- spec 003: match analysis
const FORM_SUMMARY = {
  n: 6,
  goals_for_avg: 2.17,
  goals_against_avg: 1.17,
  xg_for_avg: 2.32,
  xg_against_avg: 1.23,
  over25_pct: 0.67,
  btts_pct: 0.67,
  scored_2plus: 3,
  failed_to_score: 1,
  clean_sheets: 1,
  streak: "WWLWWL",
};

function teamForm(team: string, venue: "home" | "away"): TeamForm {
  return {
    team,
    last6: [
      {
        date: "2026-10-18",
        opponent: "Sevilla",
        competition: "SP1",
        venue,
        goals_for: 4,
        goals_against: 1,
        xg_for: 2.1,
        xg_against: 0.8,
        result: "W",
      },
      {
        date: "2026-10-10",
        opponent: "Villarreal",
        competition: "SP1",
        venue,
        goals_for: 0,
        goals_against: 1,
        xg_for: null,
        xg_against: null,
        result: "L",
      },
    ],
    summary: FORM_SUMMARY,
    summary_venue: { ...FORM_SUMMARY, venue, fallback_to_all: false },
    warnings: [],
  };
}

export const MOST_LIKELY: AdviceItem = {
  label: "Ambos marcan: sí",
  market: "btts",
  selection: "yes",
  line: null,
  probability: 0.75,
  fair_odds: 1.33,
  best_odds: 1.28,
  bookmaker: "betsson",
  ev: -0.04,
  verdict: "evitar",
  confidence: "media",
  experimental: true,
  price_comment:
    "Probable (75 %), pero la cuota 1.28 paga menos de lo justo (1.33): EV -4.0 %. No conviene.",
  reasons: [
    {
      stance: "for",
      text: "El modelo espera al menos 1.9 goles de cada equipo.",
      evidence: { lambda_min: 1.91 },
    },
    {
      stance: "against",
      text: "Barcelona no recibió goles en 3 de sus últimos 6 partidos de visita.",
      evidence: {
        away: "Barcelona",
        away_clean_sheets: 3,
        away_n: 6,
        away_venue_text: " de visita",
      },
    },
  ],
  warnings: [],
};

export function analysis(overrides: Partial<Analysis> = {}): Analysis {
  return {
    match: {
      match_id: "SP1-2026-10-26-real-madrid-barcelona",
      competition: "SP1",
      kickoff: null,
      date: "2026-10-26",
      home_team: "Real Madrid",
      away_team: "Barcelona",
      cross_league: false,
      ratings: null,
      expected_goals: { home: 2.09, away: 1.91 },
      model: "dixon_coles_xg",
      odds_snapshot_at: null,
      warnings: [],
    },
    best_options: [],
    best_options_note: "Los consejos de valor están desactivados.",
    most_likely: [MOST_LIKELY],
    no_value_message: null,
    markets: [
      {
        market: "btts",
        name: "Ambos marcan",
        confidence: "media",
        experimental: true,
        selections: [
          {
            selection: "yes",
            line: null,
            label: "Ambos marcan: sí",
            probability: 0.75,
            fair_odds: 1.33,
            best_odds: 1.28,
            bookmaker: "betsson",
            ev: -0.04,
            verdict: "evitar",
            confidence: "media",
            information_only: false,
          },
        ],
      },
      {
        market: "totals",
        name: "Más/Menos goles",
        confidence: "baja",
        experimental: true,
        selections: [
          {
            selection: "over",
            line: 4.5,
            label: "Más de 4.5 goles",
            probability: 0.37,
            fair_odds: 2.7,
            best_odds: null,
            bookmaker: null,
            ev: null,
            verdict: "sin_cuota",
            confidence: "baja",
            information_only: true,
          },
        ],
      },
    ],
    form: {
      home: teamForm("Real Madrid", "home"),
      away: teamForm("Barcelona", "away"),
      h2h: { matches: [], note: "Los enfrentamientos directos tienen poco poder predictivo." },
    },
    ...overrides,
  };
}

export const marketSummary: MarketSummary = {
  market: "totals",
  bets: 12,
  settled: 10,
  roi: -0.05,
  clv_mean_pinnacle: null,
  clv_n_pinnacle: 0,
  clv_mean_market_average: 0.012,
  clv_n_market_average: 9,
  clv_mean_other: null,
  clv_n_other: 0,
  paper_with_clv: 9,
  paper_clv_mean: 0.012,
  evidence_target: 100,
  evidence_met: false,
};
