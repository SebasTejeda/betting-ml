import {
  ArrowRight,
  CalendarX2,
  NotebookPen,
  RefreshCw,
  Sparkles,
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
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { kickoff, odds, pct, todayLima } from "../lib/format";
import { analysisLink, calculatorLink } from "../lib/links";

export function TodayPage() {
  const [date, setDate] = useState(todayLima());
  const [league, setLeague] = useState("");
  const [accessibleOnly, setAccessibleOnly] = useState(true);
  const comparator = useComparator({ date, league, accessibleOnly });

  return (
    <>
      <PageTitle
        description="La mejor cuota disponible por resultado y el margen que cobra cada casa. Elegir la mejor casa en vez de una promedio es la ventaja medida (ver Backtest)."
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
          <p className="num mb-4 flex flex-wrap gap-x-2 text-xs text-muted-foreground">
            <span className="font-medium text-foreground">{comparator.data.count} partidos</span>
            <span aria-hidden>·</span>
            <span>
              cuotas del {comparator.data.snapshot_at ? kickoff(comparator.data.snapshot_at) : "—"}
            </span>
            <span aria-hidden>·</span>
            <span>referencia {comparator.data.reference}</span>
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
    <div className="flex flex-col items-start gap-1.5 text-sm sm:items-end">
      <Button
        type="button"
        variant="outline"
        disabled={refresh.isPending || budget.data?.low}
        onClick={() => refresh.mutate(league || undefined)}
      >
        <RefreshCw aria-hidden className={refresh.isPending ? "animate-spin" : undefined} />
        {refresh.isPending ? "Actualizando…" : "Actualizar cuotas"}
      </Button>
      <span className="num text-xs text-muted-foreground">
        {budget.data
          ? `Créditos: ${remaining ?? "sin datos"} (reserva ${budget.data.min_reserve}) · ~2 por liga`
          : "Créditos: …"}
      </span>
      {budget.data?.low && (
        <span className="text-xs text-negative">Créditos bajo la reserva: refresco bloqueado.</span>
      )}
      {refresh.isError && <RefreshError error={refresh.error} />}
      {refresh.isSuccess && (
        <span role="status" className="text-xs text-muted-foreground">
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

/** Best price for one outcome: the price leads, the house and the fair odds follow. */
function OddsCell({ match, outcome }: { match: ComparatorMatch; outcome: Outcome }) {
  const best = match.best[outcome];
  return (
    <div className="flex min-w-0 flex-col gap-0.5 px-3 py-2.5">
      <span className="eyebrow">{OUTCOME_LABEL[outcome]}</span>
      {best ? (
        <>
          <span className="num text-lg leading-tight font-semibold">{odds(best.odds)}</span>
          <span className="truncate text-xs text-muted-foreground">{best.bookmaker}</span>
          {match.fair && (
            <span className="num text-xs text-muted-foreground">
              justa {odds(match.fair.odds[outcome])}
            </span>
          )}
          {best.ev !== null && <EvValue ev={best.ev} className="text-xs" />}
        </>
      ) : (
        <span className="text-lg leading-tight text-muted-foreground">—</span>
      )}
    </div>
  );
}

function MatchCard({ match }: { match: ComparatorMatch }) {
  const signal = match.experimental_signal;
  const m = match.margins;
  const name = `${match.home_team} – ${match.away_team}`;
  return (
    <Card className="h-full gap-0 py-0 transition-colors duration-150 hover:border-foreground/20">
      <div className="flex flex-col gap-3 px-4 pt-4">
        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">{match.league}</span>
          <span className="num">{kickoff(match.kickoff)}</span>
        </div>
        <Link
          to={`/match/${match.match_id}`}
          className="group flex flex-col gap-2 rounded-md transition-colors duration-150"
        >
          <span className="sr-only">{name}</span>
          {[match.home_team, match.away_team].map((team) => (
            <span key={team} aria-hidden className="flex items-center gap-2.5 font-medium">
              <TeamAvatar name={team} size="sm" />
              <span className="truncate group-hover:underline">{team}</span>
            </span>
          ))}
        </Link>
        {match.warning && (
          <p className="flex items-center gap-1.5 text-xs text-experimental">
            <TriangleAlert aria-hidden className="size-3.5" />
            {match.warning}
          </p>
        )}
      </div>
      <div className="mx-4 mt-4 grid grid-cols-3 divide-x overflow-hidden rounded-lg border">
        {OUTCOMES.map((o) => (
          <OddsCell key={o} match={match} outcome={o} />
        ))}
      </div>
      <p className="num mx-4 mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>
          Margen <strong className="font-medium text-foreground">{pct(m.best_combined)}</strong> con
          las mejores · {pct(m.average)} promedio
        </span>
        {m.best_vs_average_uplift !== null && (
          <span className="font-medium text-positive">
            Pagan {pct(m.best_vs_average_uplift, 1, true)} vs promedio
          </span>
        )}
      </p>
      {signal && signal.bets.length > 0 && (
        <div className="mx-4 mt-3 flex flex-col gap-2 rounded-lg bg-experimental-soft px-3 py-2.5">
          <ExperimentalBadge />
          {signal.bets.map((bet) => (
            <div key={bet.outcome} className="flex flex-wrap items-center gap-2 text-xs">
              <Link
                className="num inline-flex items-center gap-1 font-medium text-foreground underline-offset-2 hover:underline"
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
      {/* Actions pinned to the bottom so the cards of a row line up. */}
      <div className="mt-auto pt-3">
        <div className="flex items-center justify-between gap-2 border-t px-2 py-1.5">
          <Button asChild variant="ghost" size="sm" className="text-primary hover:text-primary">
            <Link to={analysisLink(match.home_team, match.away_team, match.match_id)}>
              <Sparkles aria-hidden />
              Analizar
              <span className="sr-only"> {name}</span>
            </Link>
          </Button>
          <Button asChild variant="ghost" size="sm" className="text-muted-foreground">
            <Link to={`/match/${match.match_id}`}>
              Cuotas por casa
              <span className="sr-only"> de {name}</span>
              <ArrowRight aria-hidden />
            </Link>
          </Button>
        </div>
      </div>
    </Card>
  );
}
