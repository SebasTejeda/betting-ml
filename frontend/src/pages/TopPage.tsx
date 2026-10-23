import { NotebookPen, SearchX } from "lucide-react";
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
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { kickoff, odds, todayLima } from "../lib/format";
import { calculatorLink } from "../lib/links";
import { topRows, type TopRow as Row } from "../lib/top";

// Rank · match · pick · house · odds · EV · action: one grid so every row lines up.
const COLUMNS =
  "md:grid md:grid-cols-[2rem_minmax(0,2.2fr)_minmax(0,0.8fr)_minmax(0,0.9fr)_4rem_minmax(0,1.4fr)_9.5rem] md:items-center md:gap-4";

export function TopPage() {
  const [date, setDate] = useState(todayLima());
  const [league, setLeague] = useState("");
  const [accessibleOnly, setAccessibleOnly] = useState(true);
  const comparator = useComparator({ date, league, accessibleOnly, onlyValue: true });
  const rows = comparator.data ? topRows(comparator.data.matches) : [];

  return (
    <>
      <PageTitle description="Las cuotas con EV positivo de la señal para la fecha elegida, de todas las ligas, ordenadas por EV.">
        Top del día
      </PageTitle>
      <div className="mt-4 mb-6 flex flex-col gap-2 rounded-lg bg-experimental-soft px-4 py-3 sm:flex-row sm:items-start sm:gap-3">
        <ExperimentalBadge className="shrink-0" />
        <p className="text-sm text-foreground">
          Esta lista no tiene evidencia de ventaja: el backtest no la validó. Sirve para anotar
          apuestas <strong>en papel</strong> y medir su CLV hasta llegar a 100. Un EV alto con
          cuotas altas suele ser ruido.
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
        <Card className="gap-0 py-0">
          <div aria-hidden className={`${COLUMNS} hidden border-b px-4 py-2.5 md:grid`}>
            {["#", "Partido", "Resultado", "Casa", "Cuota", "EV", ""].map((label, i) => (
              <span key={i} className={`eyebrow ${label === "Cuota" ? "text-right" : ""}`}>
                {label}
              </span>
            ))}
          </div>
          <ol aria-label="Top del día" className="divide-y">
            {rows.map((row, index) => (
              <li key={`${row.match.match_id}-${row.bet.outcome}`}>
                <TopRow row={row} rank={index + 1} />
              </li>
            ))}
          </ol>
        </Card>
      )}
    </>
  );
}

function TopRow({ row, rank }: { row: Row; rank: number }) {
  const { match, bet } = row;
  return (
    <div
      className={`${COLUMNS} flex flex-col gap-3 px-4 py-3.5 transition-colors duration-150 hover:bg-muted/40`}
    >
      <span className="num hidden text-sm text-muted-foreground md:block">{rank}</span>
      <Link to={`/match/${match.match_id}`} className="group flex min-w-0 flex-col gap-0.5">
        <span className="truncate font-medium group-hover:underline">
          {match.home_team} – {match.away_team}
        </span>
        <span className="num text-xs text-muted-foreground">
          {match.league} · {kickoff(match.kickoff)}
        </span>
      </Link>
      {/* On phones the three figures sit in a row with their own labels. */}
      <dl className="grid grid-cols-3 gap-2 text-sm md:col-span-3 md:grid-cols-subgrid md:gap-4">
        <div className="min-w-0">
          <dt className="text-xs text-muted-foreground md:sr-only">Resultado</dt>
          <dd className="font-medium">{OUTCOME_LABEL[bet.outcome]}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-xs text-muted-foreground md:sr-only">Casa</dt>
          <dd className="truncate">{bet.bookmaker}</dd>
        </div>
        <div className="md:text-right">
          <dt className="text-xs text-muted-foreground md:sr-only">Cuota</dt>
          <dd className="num font-semibold">{odds(bet.odds)}</dd>
        </div>
      </dl>
      <div className="flex flex-wrap items-center gap-2">
        <EvValue ev={bet.ev} className="font-semibold" />
        <ModelBadge agrees={bet.model_agrees} />
      </div>
      <Button asChild variant="outline" size="sm" className="w-fit">
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
    </div>
  );
}
