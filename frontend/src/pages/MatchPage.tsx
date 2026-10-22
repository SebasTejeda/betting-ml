import {
  Calculator,
  ChartLine,
  Clock,
  NotebookPen,
  Scale,
  SearchX,
  Table2,
  TriangleAlert,
  Sparkles,
} from "lucide-react";
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
import { OUTCOME_LABEL, OUTCOMES, type ComparatorDetail, type Triple } from "../api/types";
import { Empty, ErrorBox, ExperimentalBadge, Loading, Panel } from "../components/common";
import { ManualOddsForm } from "../components/ManualOddsForm";
import { TeamAvatar } from "../components/TeamAvatar";
import { Badge } from "../components/ui/badge";
import { Card } from "../components/ui/card";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../components/ui/table";
import { kickoff, odds, pct } from "../lib/format";
import { analysisLink, calculatorLink } from "../lib/links";
import { cn } from "../lib/utils";

const OUTCOME_COLOR = {
  home: "bg-chart-1",
  draw: "bg-chart-3",
  away: "bg-chart-2",
} as const;

export function MatchPage() {
  const { matchId = "" } = useParams();
  const detail = useMatchDetail(matchId);

  if (detail.isPending) return <Loading what="el partido" />;
  if (detail.isError) {
    if (detail.error instanceof ApiError && detail.error.status === 404) {
      return (
        <Empty icon={SearchX} title="No lo encontramos">
          Partido no encontrado o sin cuotas. Vuelve a Hoy y actualiza las cuotas.
        </Empty>
      );
    }
    return <ErrorBox error={detail.error} />;
  }
  const match = detail.data;
  return (
    <div className="flex flex-col gap-4">
      <Scoreboard match={match} />
      <div className="grid gap-4 lg:grid-cols-5">
        <Panel title="Probabilidades 1X2" icon={Scale} className="lg:col-span-2">
          <ReferenceAndModel match={match} />
        </Panel>
        <Panel title="Cuota de referencia en el tiempo" icon={ChartLine} className="lg:col-span-3">
          <ReferenceChart match={match} />
        </Panel>
      </div>
      <Panel title="Cuotas por casa" icon={Table2}>
        <BooksTable match={match} />
      </Panel>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Calculadora rápida (casas peruanas)" icon={Calculator}>
          <ManualOddsForm matchId={match.match_id} />
          <Link
            to={calculatorLink({ matchId: match.match_id })}
            className="mt-3 inline-block text-sm text-primary underline-offset-2 hover:underline"
          >
            Abrir en la calculadora para registrar la apuesta
          </Link>
        </Panel>
        {match.experimental_signal && match.experimental_signal.bets.length > 0 && (
          <Panel
            title="Señal de valor"
            icon={NotebookPen}
            action={<ExperimentalBadge />}
            className="border border-experimental-border"
          >
            <p className="mb-3 text-sm text-muted-foreground">
              Sin evidencia todavía: se anota en papel para medir su CLV.
            </p>
            <ul className="flex flex-col gap-2 text-sm">
              {match.experimental_signal.bets.map((bet) => (
                <li key={bet.outcome} className="flex flex-wrap items-center gap-2">
                  <Link
                    className="font-medium underline-offset-2 hover:underline"
                    to={calculatorLink({
                      matchId: match.match_id,
                      outcome: bet.outcome,
                      bookmaker: bet.bookmaker,
                      odds: bet.odds,
                      fromSignal: true,
                    })}
                  >
                    {OUTCOME_LABEL[bet.outcome]} {odds(bet.odds)} en {bet.bookmaker} · EV{" "}
                    {pct(bet.ev, 1, true)}
                    {bet.model_agrees !== null &&
                      ` · el modelo ${bet.model_agrees ? "coincide" : "no coincide"}`}{" "}
                    · anotar en papel
                  </Link>
                </li>
              ))}
            </ul>
          </Panel>
        )}
      </div>
    </div>
  );
}

function Scoreboard({ match }: { match: ComparatorDetail }) {
  return (
    <Card className="gap-4 bg-linear-to-b from-secondary/60 to-card px-4 py-6 shadow-sm">
      <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
        <Badge variant="secondary">{match.league}</Badge>
        <Clock aria-hidden className="size-3.5" />
        {kickoff(match.kickoff)}
      </div>
      <h1 className="sr-only">
        {match.home_team} – {match.away_team}
      </h1>
      <div aria-hidden className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
        <div className="flex flex-col items-center gap-2 text-center">
          <TeamAvatar name={match.home_team} size="lg" />
          <span className="text-base font-semibold sm:text-xl">{match.home_team}</span>
          <span className="text-xs text-muted-foreground">Local</span>
        </div>
        <span className="text-2xl font-light text-muted-foreground">vs</span>
        <div className="flex flex-col items-center gap-2 text-center">
          <TeamAvatar name={match.away_team} size="lg" />
          <span className="text-base font-semibold sm:text-xl">{match.away_team}</span>
          <span className="text-xs text-muted-foreground">Visita</span>
        </div>
      </div>
      <Link
        to={analysisLink(match.home_team, match.away_team, match.match_id)}
        className="mx-auto inline-flex items-center gap-1 text-sm font-medium text-primary underline-offset-2 hover:underline"
      >
        <Sparkles aria-hidden className="size-4" />
        Analizar el partido (mercados, forma y lo más probable)
      </Link>
      {match.warning && (
        <p className="flex items-center justify-center gap-1 text-sm text-experimental">
          <TriangleAlert aria-hidden className="size-4" />
          {match.warning}
        </p>
      )}
    </Card>
  );
}

function ProbBar({ label, probs }: { label: string; probs: Triple }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div aria-hidden className="flex h-3 w-full overflow-hidden rounded-full bg-muted">
        {OUTCOMES.map((o) => (
          <div
            key={o}
            className={cn("h-full transition-[width] duration-200", OUTCOME_COLOR[o])}
            style={{ width: `${100 * (probs[o] ?? 0)}%` }}
          />
        ))}
      </div>
    </div>
  );
}

function ReferenceAndModel({ match }: { match: ComparatorDetail }) {
  if (!match.fair && !match.model) {
    return <Empty>Sin cuota de referencia ni opinión del modelo para este partido.</Empty>;
  }
  return (
    <div className="flex flex-col gap-4">
      {match.fair && (
        <ProbBar label={`Justa (${match.fair.source})`} probs={match.fair.probabilities} />
      )}
      {match.model && (
        <ProbBar
          label={`Modelo (${match.model.version ?? "—"})`}
          probs={match.model.probabilities}
        />
      )}
      <dl
        className="grid gap-2 text-sm sm:grid-cols-3 lg:grid-cols-1"
        aria-label="Referencia y modelo"
      >
        {OUTCOMES.map((o) => (
          <div key={o} className="rounded-lg bg-secondary/50 p-2">
            <dt className="flex items-center gap-1.5 font-medium">
              <span aria-hidden className={cn("size-2.5 rounded-full", OUTCOME_COLOR[o])} />
              {OUTCOME_LABEL[o]}
            </dt>
            <dd className="text-xs">
              {match.fair
                ? `Justa (${match.fair.source}): ${odds(match.fair.odds[o])} · ${pct(match.fair.probabilities[o])}`
                : "Sin referencia"}
            </dd>
            {match.model && (
              <dd className="text-xs text-muted-foreground">
                Modelo ({match.model.version ?? "—"}): {pct(match.model.probabilities[o])}
              </dd>
            )}
          </div>
        ))}
      </dl>
    </div>
  );
}

function BooksTable({ match }: { match: ComparatorDetail }) {
  if (match.bookmakers.length === 0) return <Empty>Sin cuotas de casas para este partido.</Empty>;
  const bestKey = (o: (typeof OUTCOMES)[number]) => match.best[o]?.bookmaker;
  return (
    <>
      <Table>
        <TableCaption className="sr-only">
          Cuotas de cada casa por resultado y su margen
        </TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>Casa</TableHead>
            {OUTCOMES.map((o) => (
              <TableHead key={o} className="text-right">
                {OUTCOME_LABEL[o]}
              </TableHead>
            ))}
            <TableHead className="text-right">Margen</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {match.bookmakers.map((book) => (
            <TableRow key={book.key}>
              <TableHead scope="row" className="font-medium text-foreground">
                {book.key}
                {!book.accessible && (
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    (referencia)
                  </span>
                )}
              </TableHead>
              {OUTCOMES.map((o) => {
                const isBest = bestKey(o) === book.key;
                return (
                  <TableCell key={o} className="text-right tabular-nums">
                    <span
                      className={cn(
                        "inline-block rounded-md px-2 py-0.5",
                        isBest && "bg-positive-soft font-semibold text-positive",
                      )}
                    >
                      {odds(book.odds[o])}
                    </span>
                    {isBest && <span className="sr-only"> (mejor cuota)</span>}
                  </TableCell>
                );
              })}
              <TableCell className="text-right text-muted-foreground tabular-nums">
                {pct(book.margin)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="mt-3 text-xs text-muted-foreground">
        Margen de la mejor combinación: {pct(match.margins.best_combined)} · promedio:{" "}
        {pct(match.margins.average)}
      </p>
    </>
  );
}

function ReferenceChart({ match }: { match: ComparatorDetail }) {
  if (match.reference_history.length < 2) {
    return <Empty icon={ChartLine}>Aún no hay suficientes snapshots de la referencia.</Empty>;
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
        <LineChart data={data} margin={{ left: -12, right: 8, top: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
          <XAxis dataKey="at" fontSize={11} stroke="var(--chart-text)" tickLine={false} />
          <YAxis
            domain={["auto", "auto"]}
            fontSize={11}
            stroke="var(--chart-text)"
            tickLine={false}
          />
          <Tooltip
            contentStyle={{
              background: "var(--popover)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              color: "var(--popover-foreground)",
            }}
          />
          <Legend />
          <Line
            type="monotone"
            dataKey="Local"
            stroke="var(--chart-1)"
            strokeWidth={2}
            dot={false}
          />
          <Line
            type="monotone"
            dataKey="Empate"
            stroke="var(--chart-3)"
            strokeWidth={2}
            dot={false}
          />
          <Line
            type="monotone"
            dataKey="Visita"
            stroke="var(--chart-2)"
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
