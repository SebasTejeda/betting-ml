import type { ComparatorMatch } from "../api/types";

type SignalBet = NonNullable<ComparatorMatch["experimental_signal"]>["bets"][number];
export type TopRow = { match: ComparatorMatch; bet: SignalBet };

/** Every positive-EV price of the experimental signal for the day, all leagues, by EV. */
export function topRows(matches: ComparatorMatch[]): TopRow[] {
  return matches
    .flatMap((match) => (match.experimental_signal?.bets ?? []).map((bet) => ({ match, bet })))
    .filter((row) => row.bet.ev > 0)
    .sort((a, b) => b.bet.ev - a.bet.ev);
}
