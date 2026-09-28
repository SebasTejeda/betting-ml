import { Link, useParams } from "react-router-dom";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ApiError } from "../api/client";
import { useMatchDetail } from "../api/hooks";
import { OUTCOME_LABEL, OUTCOMES, type ComparatorDetail } from "../api/types";
import { ManualOddsForm } from "../components/ManualOddsForm";
import { Card, Empty, ErrorBox, ExperimentalBadge, Loading, PageTitle } from "../components/ui";
import { kickoff, odds, pct } from "../lib/format";
import { calculatorLink } from "../lib/links";

export function MatchPage() {
  const { matchId = "" } = useParams();
  const detail = useMatchDetail(matchId);

  if (detail.isPending) return <Loading what="el partido" />;
  if (detail.isError) {
    if (detail.error instanceof ApiError && detail.error.status === 404) {
      return (
        <Empty>Partido no encontrado o sin cuotas. Vuelve a Hoy y actualiza las cuotas.</Empty>
      );
    }
    return <ErrorBox error={detail.error} />;
  }
  const match = detail.data;
  return (
    <>
      <PageTitle>
        {match.home_team} – {match.away_team}
      </PageTitle>
      <p className="mb-4 text-sm text-slate-600">
        {match.league} · {kickoff(match.kickoff)}
        {match.warning && <span className="ml-2 text-amber-800">{match.warning}</span>}
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="lg:col-span-2">
          <h2 className="mb-2 font-semibold">Cuotas por casa</h2>
          <BooksTable match={match} />
        </Card>
        <Card>
          <h2 className="mb-2 font-semibold">Cuota de referencia en el tiempo</h2>
          <ReferenceChart match={match} />
        </Card>
        <Card>
          <h2 className="mb-2 font-semibold">Calculadora rápida (casas peruanas)</h2>
          <ManualOddsForm matchId={match.match_id} />
          <Link
            to={calculatorLink({ matchId: match.match_id })}
            className="mt-3 inline-block text-sm text-sky-800 underline"
          >
            Abrir en la calculadora para registrar la apuesta
          </Link>
        </Card>
        {match.experimental_signal && match.experimental_signal.bets.length > 0 && (
          <Card className="lg:col-span-2">
            <h2 className="mb-2 flex items-center gap-2 font-semibold">
              Señal de valor <ExperimentalBadge />
            </h2>
            <p className="mb-2 text-sm text-slate-600">
              Sin evidencia todavía: se anota en papel para medir su CLV.
            </p>
            <ul className="text-sm">
              {match.experimental_signal.bets.map((bet) => (
                <li key={bet.outcome}>
                  <Link
                    className="text-sky-800 underline"
                    to={calculatorLink({
                      matchId: match.match_id,
                      outcome: bet.outcome,
                      bookmaker: bet.bookmaker,
                      odds: bet.odds,
                      fromSignal: true,
                    })}
                  >
                    {OUTCOME_LABEL[bet.outcome]} {odds(bet.odds)} en {bet.bookmaker} · EV{" "}
                    {pct(bet.ev, 1, true)} · anotar en papel
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </>
  );
}

function BooksTable({ match }: { match: ComparatorDetail }) {
  if (match.bookmakers.length === 0) return <Empty>Sin cuotas de casas para este partido.</Empty>;
  const bestKey = (o: (typeof OUTCOMES)[number]) => match.best[o]?.bookmaker;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">Cuotas de cada casa por resultado y su margen</caption>
        <thead>
          <tr className="border-b border-slate-200 text-left text-slate-700">
            <th scope="col" className="p-2">
              Casa
            </th>
            {OUTCOMES.map((o) => (
              <th key={o} scope="col" className="p-2">
                {OUTCOME_LABEL[o]}
              </th>
            ))}
            <th scope="col" className="p-2">
              Margen
            </th>
          </tr>
        </thead>
        <tbody>
          {match.bookmakers.map((book) => (
            <tr key={book.key} className="border-b border-slate-100">
              <th scope="row" className="p-2 text-left font-medium">
                {book.key}
                {!book.accessible && (
                  <span className="ml-1 text-xs font-normal text-slate-500">(referencia)</span>
                )}
              </th>
              {OUTCOMES.map((o) => {
                const isBest = bestKey(o) === book.key;
                return (
                  <td
                    key={o}
                    className={`p-2 tabular-nums ${isBest ? "bg-emerald-100 font-semibold text-emerald-900" : ""}`}
                  >
                    {odds(book.odds[o])}
                    {isBest && <span className="sr-only"> (mejor cuota)</span>}
                  </td>
                );
              })}
              <td className="p-2 tabular-nums">{pct(book.margin)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-slate-600">
        Margen de la mejor combinación: {pct(match.margins.best_combined)} · promedio:{" "}
        {pct(match.margins.average)}
      </p>
    </div>
  );
}

function ReferenceChart({ match }: { match: ComparatorDetail }) {
  if (match.reference_history.length < 2) {
    return <Empty>Aún no hay suficientes snapshots de la referencia.</Empty>;
  }
  const data = match.reference_history.map((point) => ({
    at: kickoff(point.at),
    Local: point.odds.home,
    Empate: point.odds.draw,
    Visita: point.odds.away,
  }));
  return (
    <div className="h-64" aria-label="Gráfico de la cuota de referencia" role="img">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="at" fontSize={11} />
          <YAxis domain={["auto", "auto"]} fontSize={11} />
          <Tooltip />
          <Legend />
          <Line type="monotone" dataKey="Local" stroke="#0369a1" />
          <Line type="monotone" dataKey="Empate" stroke="#64748b" />
          <Line type="monotone" dataKey="Visita" stroke="#b45309" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
