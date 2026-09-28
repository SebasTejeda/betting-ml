import { Clock, Info, ListOrdered, NotebookPen, SearchX } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { useComparator } from "../api/hooks";
import { OUTCOME_LABEL } from "../api/types";
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
import { kickoff, odds, todayLima } from "../lib/format";
import { calculatorLink } from "../lib/links";
import { topRows, type TopRow as Row } from "../lib/top";

export function TopPage() {
  const [date, setDate] = useState(todayLima());
  const [league, setLeague] = useState("");
  const [accessibleOnly, setAccessibleOnly] = useState(true);
  const comparator = useComparator({ date, league, accessibleOnly, onlyValue: true });
  const rows = comparator.data ? topRows(comparator.data.matches) : [];

  return (
    <>
      <PageTitle
        icon={ListOrdered}
        description="Todas las cuotas con EV positivo de la señal para la fecha elegida, de todas las ligas, ordenadas por EV."
      >
        Top del día
      </PageTitle>
      <div className="mb-5 flex flex-col gap-2 rounded-xl border border-experimental-border bg-experimental-soft/60 p-4">
        <ExperimentalBadge className="text-sm" />
        <p className="flex items-start gap-2 text-sm text-foreground">
          <Info aria-hidden className="mt-0.5 size-4 shrink-0 text-experimental" />
          <span>
            Esta lista no tiene evidencia de ventaja: el backtest no la validó. Sirve para anotar
            apuestas <strong>en papel</strong> y medir su CLV hasta llegar a 100. Un EV alto con
            cuotas altas suele ser ruido.
          </span>
        </p>
      </div>
      <MatchFilters
        date={date}
        onDate={setDate}
        league={league}
        onLeague={setLeague}
        accessibleOnly={accessibleOnly}
        onAccessibleOnly={setAccessibleOnly}
      />
      {comparator.isPending ? (
        <Loading what="el top del día" variant="table" />
      ) : comparator.isError ? (
        <ErrorBox error={comparator.error} />
      ) : rows.length === 0 ? (
        <Empty icon={SearchX} title="Nada con EV positivo">
          No hay cuotas con EV positivo para esta fecha. Prueba otra fecha o actualiza las cuotas en
          Hoy.
        </Empty>
      ) : (
        <ol aria-label="Top del día" className="flex flex-col gap-3">
          {rows.map((row, index) => (
            <li key={`${row.match.match_id}-${row.bet.outcome}`}>
              <TopRow row={row} rank={index + 1} />
            </li>
          ))}
        </ol>
      )}
    </>
  );
}

function TopRow({ row, rank }: { row: Row; rank: number }) {
  const { match, bet } = row;
  return (
    <Card className="flex flex-col gap-3 px-4 shadow-sm md:grid md:grid-cols-[2.5rem_minmax(0,2fr)_minmax(0,1.3fr)_auto_auto] md:items-center md:gap-4">
      <span className="hidden text-lg font-semibold text-muted-foreground tabular-nums md:block">
        {rank}
      </span>
      <Link to={`/match/${match.match_id}`} className="group flex min-w-0 flex-col gap-1">
        <span className="flex items-center gap-2 text-xs text-muted-foreground">
          <Badge variant="secondary">{match.league}</Badge>
          <Clock aria-hidden className="size-3.5" />
          {kickoff(match.kickoff)}
        </span>
        <span className="flex items-center gap-2 font-medium">
          <TeamAvatar name={match.home_team} size="sm" />
          <span className="truncate group-hover:underline">
            {match.home_team} – {match.away_team}
          </span>
          <TeamAvatar name={match.away_team} size="sm" />
        </span>
      </Link>
      <dl className="grid grid-cols-3 gap-2 text-sm">
        <div>
          <dt className="text-xs text-muted-foreground">Resultado</dt>
          <dd className="font-medium">{OUTCOME_LABEL[bet.outcome]}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Casa</dt>
          <dd className="truncate">{bet.bookmaker}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Cuota</dt>
          <dd className="font-semibold tabular-nums">{odds(bet.odds)}</dd>
        </div>
      </dl>
      <div className="flex flex-wrap items-center gap-2">
        <EvValue ev={bet.ev} className="font-semibold" />
        <ModelBadge agrees={bet.model_agrees} />
      </div>
      <Button asChild variant="outline" size="sm">
        <Link
          to={calculatorLink({
            matchId: match.match_id,
            outcome: bet.outcome,
            bookmaker: bet.bookmaker,
            odds: bet.odds,
            fromSignal: true,
          })}
        >
          <NotebookPen aria-hidden />
          Registrar en papel
        </Link>
      </Button>
    </Card>
  );
}
