import {
  CalendarDays,
  CalendarX2,
  Clock,
  NotebookPen,
  RefreshCw,
  TriangleAlert,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import { useBudget, useComparator, useRefreshOdds } from "../api/hooks";
import { OUTCOME_LABEL, OUTCOMES, type ComparatorMatch, type Outcome } from "../api/types";
import {
  Empty,
  ErrorBox,
  EvValue,
  ExperimentalBadge,
  Loading,
  ModelBadge,
  PageTitle,
} from "../components/common";
import { MatchFilters } from "../components/MatchFilters";
import { TeamAvatar } from "../components/TeamAvatar";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { kickoff, odds, pct, todayLima } from "../lib/format";
import { calculatorLink } from "../lib/links";

export function TodayPage() {
  const [date, setDate] = useState(todayLima());
  const [league, setLeague] = useState("");
  const [accessibleOnly, setAccessibleOnly] = useState(true);
  const comparator = useComparator({ date, league, accessibleOnly });

  return (
    <>
      <PageTitle
        icon={CalendarDays}
        description="La mejor cuota disponible por resultado y cuánto margen cobra cada casa. Elegir la mejor casa en vez de una promedio es la ventaja medida (ver Backtest)."
        aside={<RefreshButton league={league} />}
      >
        Hoy
      </PageTitle>
      <MatchFilters
        date={date}
        onDate={setDate}
        league={league}
        onLeague={setLeague}
        accessibleOnly={accessibleOnly}
        onAccessibleOnly={setAccessibleOnly}
      />
      {comparator.isPending ? (
        <Loading what="partidos" variant="cards" />
      ) : comparator.isError ? (
        <ErrorBox error={comparator.error} />
      ) : comparator.data.matches.length === 0 ? (
        <Empty icon={CalendarX2} title="Sin partidos para esta fecha">
          No hay partidos con cuotas para esta fecha. Actualiza las cuotas o elige otra fecha.
        </Empty>
      ) : (
        <>
          <p className="mb-3 text-xs text-muted-foreground">
            Cuotas del {comparator.data.snapshot_at ? kickoff(comparator.data.snapshot_at) : "—"} ·
            referencia {comparator.data.reference} · {comparator.data.count} partidos
          </p>
          <ul aria-label="Partidos" className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {comparator.data.matches.map((match) => (
              <li key={match.match_id}>
                <MatchCard match={match} />
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

function RefreshButton({ league }: { league: string }) {
  const budget = useBudget();
  const refresh = useRefreshOdds();
  const remaining = budget.data?.credits_remaining;
  return (
    <div className="flex flex-col items-start gap-1 text-sm sm:items-end">
      <Button
        type="button"
        variant="outline"
        disabled={refresh.isPending || budget.data?.low}
        onClick={() => refresh.mutate(league || undefined)}
      >
        <RefreshCw aria-hidden className={refresh.isPending ? "animate-spin" : undefined} />
        {refresh.isPending ? "Actualizando…" : "Actualizar cuotas"}
      </Button>
      <span className="text-xs text-muted-foreground">
        {budget.data
          ? `Créditos: ${remaining ?? "sin datos"} (reserva ${budget.data.min_reserve}) · ~2 por liga`
          : "Créditos: …"}
      </span>
      {budget.data?.low && (
        <span className="text-xs text-negative">Créditos bajo la reserva: refresco bloqueado.</span>
      )}
      {refresh.isError && <RefreshError error={refresh.error} />}
      {refresh.isSuccess && (
        <span role="status" className="text-xs text-positive">
          {refresh.data.events} partidos actualizados ({refresh.data.credits_used} créditos)
          {refresh.data.unmapped_teams.length > 0 &&
            ` · equipos sin mapear: ${refresh.data.unmapped_teams.join(", ")}`}
        </span>
      )}
    </div>
  );
}

function RefreshError({ error }: { error: Error }) {
  if (error instanceof ApiError && error.code === "ODDS_BUDGET_LOW") {
    return (
      <span role="alert" className="max-w-xs text-right text-xs text-negative">
        {error.message}
      </span>
    );
  }
  return <ErrorBox error={error} />;
}

function OddsChip({ match, outcome }: { match: ComparatorMatch; outcome: Outcome }) {
  const best = match.best[outcome];
  return (
    <div className="flex flex-col items-center gap-0.5 rounded-lg border bg-secondary/40 px-2 py-2 text-center transition-colors duration-150">
      <span className="text-[0.7rem] font-medium tracking-wide text-muted-foreground uppercase">
        {OUTCOME_LABEL[outcome]}
      </span>
      {best ? (
        <>
          <span className="text-lg leading-tight font-semibold tabular-nums">
            {odds(best.odds)}
          </span>
          <span className="max-w-full truncate text-xs text-muted-foreground">
            {best.bookmaker}
          </span>
          {match.fair && (
            <span className="text-[0.7rem] text-muted-foreground">
              justa {odds(match.fair.odds[outcome])}
            </span>
          )}
          {best.ev !== null && <EvValue ev={best.ev} className="text-[0.7rem]" />}
        </>
      ) : (
        <span className="text-muted-foreground">—</span>
      )}
    </div>
  );
}

function MatchCard({ match }: { match: ComparatorMatch }) {
  const signal = match.experimental_signal;
  const m = match.margins;
  return (
    <Card className="h-full gap-3 px-4 shadow-sm transition-shadow duration-150 hover:shadow-md">
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <Badge variant="secondary">{match.league}</Badge>
        <span className="flex items-center gap-1">
          <Clock aria-hidden className="size-3.5" />
          {kickoff(match.kickoff)}
        </span>
      </div>
      <Link
        to={`/match/${match.match_id}`}
        className="group flex flex-col gap-2 rounded-lg transition-colors duration-150"
      >
        <span className="sr-only">
          {match.home_team} – {match.away_team}
        </span>
        {[match.home_team, match.away_team].map((team) => (
          <span key={team} aria-hidden className="flex items-center gap-2 font-medium">
            <TeamAvatar name={team} size="sm" />
            <span className="group-hover:underline">{team}</span>
          </span>
        ))}
      </Link>
      {match.warning && (
        <p className="flex items-center gap-1 text-xs text-experimental">
          <TriangleAlert aria-hidden className="size-3.5" />
          {match.warning}
        </p>
      )}
      <div className="grid grid-cols-3 gap-2">
        {OUTCOMES.map((o) => (
          <OddsChip key={o} match={match} outcome={o} />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>
          Mejor combinación: <strong className="text-foreground">{pct(m.best_combined)}</strong>
        </span>
        <span>Promedio: {pct(m.average)}</span>
        {m.best_vs_average_uplift !== null && (
          <span className="font-medium text-positive">
            Pagan {pct(m.best_vs_average_uplift, 1, true)} vs promedio
          </span>
        )}
      </div>
      {signal && signal.bets.length > 0 && (
        <div className="flex flex-col gap-2 rounded-lg border border-experimental-border bg-experimental-soft/60 p-2">
          <ExperimentalBadge />
          {signal.bets.map((bet) => (
            <div key={bet.outcome} className="flex flex-wrap items-center gap-2 text-xs">
              <Link
                className="inline-flex items-center gap-1 font-medium text-foreground underline-offset-2 hover:underline"
                to={calculatorLink({
                  matchId: match.match_id,
                  outcome: bet.outcome,
                  bookmaker: bet.bookmaker,
                  odds: bet.odds,
                  fromSignal: true,
                })}
              >
                <NotebookPen aria-hidden className="size-3.5" />
                {OUTCOME_LABEL[bet.outcome]} {odds(bet.odds)} en {bet.bookmaker} · EV{" "}
                {pct(bet.ev, 1, true)} · anotar en papel
              </Link>
              <ModelBadge agrees={bet.model_agrees} />
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
