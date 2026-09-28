import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import { useBudget, useComparator, useLeagues, useRefreshOdds } from "../api/hooks";
import { OUTCOME_LABEL, OUTCOMES, type ComparatorMatch } from "../api/types";
import { Card, Empty, ErrorBox, ExperimentalBadge, Loading, PageTitle } from "../components/common";
import { kickoff, odds, pct, todayLima } from "../lib/format";
import { calculatorLink } from "../lib/links";

export function TodayPage() {
  const [date, setDate] = useState(todayLima());
  const [league, setLeague] = useState("");
  const [accessibleOnly, setAccessibleOnly] = useState(true);
  const leagues = useLeagues();
  const comparator = useComparator({ date, league, accessibleOnly });

  return (
    <>
      <PageTitle aside={<RefreshButton league={league} />}>Hoy</PageTitle>
      <p className="mb-4 text-sm text-slate-600">
        La mejor cuota disponible por resultado y cuánto margen cobra cada casa. Elegir la mejor
        casa en vez de una promedio es la ventaja medida (ver Backtest).
      </p>
      <div className="mb-4 flex flex-wrap items-end gap-4">
        <label className="flex flex-col text-sm">
          Fecha
          <input
            type="date"
            className="rounded border border-slate-300 px-2 py-1"
            value={date}
            onChange={(event) => setDate(event.target.value || todayLima())}
          />
        </label>
        <label className="flex flex-col text-sm">
          Liga
          <select
            className="rounded border border-slate-300 px-2 py-1"
            value={league}
            onChange={(event) => setLeague(event.target.value)}
          >
            <option value="">Todas</option>
            {leagues.data?.map((item) => (
              <option key={item.code} value={item.code}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={accessibleOnly}
            onChange={(event) => setAccessibleOnly(event.target.checked)}
          />
          Solo casas accesibles desde Perú
        </label>
      </div>
      {comparator.isPending ? (
        <Loading what="partidos" />
      ) : comparator.isError ? (
        <ErrorBox error={comparator.error} />
      ) : comparator.data.matches.length === 0 ? (
        <Empty>
          No hay partidos con cuotas para esta fecha. Actualiza las cuotas o elige otra fecha.
        </Empty>
      ) : (
        <>
          <p className="mb-2 text-xs text-slate-600">
            Cuotas del {comparator.data.snapshot_at ? kickoff(comparator.data.snapshot_at) : "—"} ·
            referencia {comparator.data.reference} · {comparator.data.count} partidos
          </p>
          <MatchesTable matches={comparator.data.matches} />
          <MatchCards matches={comparator.data.matches} />
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
    <div className="flex flex-col items-end gap-1 text-sm">
      <button
        type="button"
        className="rounded bg-sky-700 px-3 py-1.5 font-medium text-white hover:bg-sky-800 disabled:opacity-50"
        disabled={refresh.isPending || budget.data?.low}
        onClick={() => refresh.mutate(league || undefined)}
      >
        {refresh.isPending ? "Actualizando…" : "Actualizar cuotas"}
      </button>
      <span className="text-xs text-slate-600">
        {budget.data
          ? `Créditos: ${remaining ?? "sin datos"} (reserva ${budget.data.min_reserve}) · ~2 por liga`
          : "Créditos: …"}
      </span>
      {budget.data?.low && (
        <span className="text-xs text-red-700">Créditos bajo la reserva: refresco bloqueado.</span>
      )}
      {refresh.isError && <RefreshError error={refresh.error} />}
      {refresh.isSuccess && (
        <span role="status" className="text-xs text-emerald-800">
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
      <span role="alert" className="text-xs text-red-700">
        {error.message}
      </span>
    );
  }
  return <ErrorBox error={error} />;
}

function BestCell({
  match,
  outcome,
}: {
  match: ComparatorMatch;
  outcome: keyof typeof OUTCOME_LABEL;
}) {
  const best = match.best[outcome];
  if (!best) return <span className="text-slate-400">—</span>;
  return (
    <span className="flex flex-col">
      <span className="font-semibold tabular-nums">{odds(best.odds)}</span>
      <span className="text-xs text-slate-600">{best.bookmaker}</span>
      {match.fair && (
        <span className="text-xs text-slate-500">justa {odds(match.fair.odds[outcome])}</span>
      )}
    </span>
  );
}

function Signal({ match }: { match: ComparatorMatch }) {
  const signal = match.experimental_signal;
  if (!signal || signal.bets.length === 0) return null;
  return (
    <div className="flex flex-col gap-1">
      <ExperimentalBadge />
      {signal.bets.map((bet) => (
        <Link
          key={bet.outcome}
          className="text-xs text-sky-800 underline"
          to={calculatorLink({
            matchId: match.match_id,
            outcome: bet.outcome,
            bookmaker: bet.bookmaker,
            odds: bet.odds,
            fromSignal: true,
          })}
        >
          {OUTCOME_LABEL[bet.outcome]} {odds(bet.odds)} · EV {pct(bet.ev, 1, true)}
          {bet.model_agrees !== null &&
            ` · el modelo ${bet.model_agrees ? "coincide" : "no coincide"}`}{" "}
          · anotar en papel
        </Link>
      ))}
    </div>
  );
}

function Margins({ match }: { match: ComparatorMatch }) {
  const m = match.margins;
  return (
    <span className="flex flex-col text-xs">
      <span>
        Mejor combinación: <strong>{pct(m.best_combined)}</strong>
      </span>
      <span className="text-slate-600">Promedio: {pct(m.average)}</span>
      {m.best_vs_average_uplift !== null && (
        <span className="text-emerald-800">
          Pagan {pct(m.best_vs_average_uplift, 1, true)} vs promedio
        </span>
      )}
    </span>
  );
}

function MatchesTable({ matches }: { matches: ComparatorMatch[] }) {
  return (
    <div className="hidden overflow-x-auto md:block">
      <table className="w-full border-collapse bg-white text-sm">
        <caption className="sr-only">Mejor cuota por partido y resultado</caption>
        <thead>
          <tr className="border-b border-slate-200 text-left text-slate-700">
            <th scope="col" className="p-2">
              Partido
            </th>
            {OUTCOMES.map((o) => (
              <th key={o} scope="col" className="p-2">
                {OUTCOME_LABEL[o]}
              </th>
            ))}
            <th scope="col" className="p-2">
              Margen
            </th>
            <th scope="col" className="p-2">
              Señal
            </th>
          </tr>
        </thead>
        <tbody>
          {matches.map((match) => (
            <tr key={match.match_id} className="border-b border-slate-100 align-top">
              <td className="p-2">
                <Link
                  to={`/match/${match.match_id}`}
                  className="font-medium text-sky-800 underline"
                >
                  {match.home_team} – {match.away_team}
                </Link>
                <div className="text-xs text-slate-600">
                  {match.league} · {kickoff(match.kickoff)}
                </div>
                {match.warning && <div className="text-xs text-amber-800">{match.warning}</div>}
              </td>
              {OUTCOMES.map((o) => (
                <td key={o} className="p-2">
                  <BestCell match={match} outcome={o} />
                </td>
              ))}
              <td className="p-2">
                <Margins match={match} />
              </td>
              <td className="p-2">
                <Signal match={match} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MatchCards({ matches }: { matches: ComparatorMatch[] }) {
  return (
    <ul className="flex flex-col gap-3 md:hidden" aria-label="Partidos">
      {matches.map((match) => (
        <li key={match.match_id}>
          <Card>
            <Link to={`/match/${match.match_id}`} className="font-medium text-sky-800 underline">
              {match.home_team} – {match.away_team}
            </Link>
            <div className="mb-2 text-xs text-slate-600">
              {match.league} · {kickoff(match.kickoff)}
            </div>
            {match.warning && <div className="mb-2 text-xs text-amber-800">{match.warning}</div>}
            <dl className="mb-2 grid grid-cols-3 gap-2">
              {OUTCOMES.map((o) => (
                <div key={o}>
                  <dt className="text-xs text-slate-600">{OUTCOME_LABEL[o]}</dt>
                  <dd>
                    <BestCell match={match} outcome={o} />
                  </dd>
                </div>
              ))}
            </dl>
            <Margins match={match} />
            <div className="mt-2">
              <Signal match={match} />
            </div>
          </Card>
        </li>
      ))}
    </ul>
  );
}
