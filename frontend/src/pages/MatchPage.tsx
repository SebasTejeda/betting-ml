import { ArrowLeft, ChevronDown, SearchX, Sparkles, TriangleAlert } from "lucide-react";
import { useState } from "react";
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
import { Empty, ErrorBox, ExperimentalBadge, Loading, Panel } from "../components/common";
import { ManualOddsForm } from "../components/ManualOddsForm";
import { SplitBar } from "../components/OutcomeSplit";
import { TeamAvatar } from "../components/TeamAvatar";
import { Button } from "../components/ui/button";
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
import { OUTCOME_STROKE, OUTCOME_TONE } from "../lib/outcome";
import { analysisLink, calculatorLink } from "../lib/links";
import { cn } from "../lib/utils";

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
  const signal = match.experimental_signal;
  return (
    <div className="flex flex-col gap-5">
      <Link
        to="/"
        className="inline-flex w-fit items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft aria-hidden className="size-4" />
        Hoy
      </Link>
      <Scoreboard match={match} />
      <div className="grid gap-5 lg:grid-cols-5">
        <Panel title="Probabilidades 1X2" className="lg:col-span-2">
          <ReferenceAndModel match={match} />
        </Panel>
        <Panel title="Cuota de referencia en el tiempo" className="lg:col-span-3">
          <ReferenceChart match={match} />
        </Panel>
      </div>
      <div className="grid items-start gap-5 lg:grid-cols-5">
        <Panel title="Cuotas por casa" className="lg:col-span-3">
          <BooksTable match={match} />
        </Panel>
        <div className="flex flex-col gap-5 lg:col-span-2">
          <Panel title="Calculadora rápida (casas peruanas)">
            <ManualOddsForm matchId={match.match_id} />
            <Link
              to={calculatorLink({ matchId: match.match_id })}
              className="mt-4 inline-block text-sm text-primary underline-offset-2 hover:underline"
            >
              Abrir en la calculadora para registrar la apuesta
            </Link>
          </Panel>
          {signal && signal.bets.length > 0 && (
            <Panel
              title="Señal de valor"
              action={<ExperimentalBadge />}
              className="border-experimental-border"
            >
              <p className="mb-3 text-sm text-muted-foreground">
                Sin evidencia todavía: se anota en papel para medir su CLV.
              </p>
              <ul className="flex flex-col gap-2 text-sm">
                {signal.bets.map((bet) => (
                  <li key={bet.outcome}>
                    <Link
                      className="num font-medium underline-offset-2 hover:underline"
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
    </div>
  );
}

function Scoreboard({ match }: { match: ComparatorDetail }) {
  // The fair price leads (it is the measured edge); the model is the second opinion.
  const split = match.fair?.probabilities ?? match.model?.probabilities;
  const source = match.fair
    ? `Probabilidad justa (${match.fair.source})`
    : "Probabilidad según el modelo";
  return (
    <Card className="gap-6 p-5 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">{match.league}</span>
          <span aria-hidden>·</span>
          <span className="num">{kickoff(match.kickoff)}</span>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link to={analysisLink(match.home_team, match.away_team, match.match_id)}>
            <Sparkles aria-hidden />
            Analizar el partido
            <span className="sr-only"> (mercados, forma y lo más probable)</span>
          </Link>
        </Button>
      </div>
      <h1 className="sr-only">
        {match.home_team} – {match.away_team}
      </h1>
      <div aria-hidden className="grid grid-cols-[1fr_auto_1fr] items-center gap-4">
        <Team name={match.home_team} side="Local" />
        <span className="text-sm text-muted-foreground">vs</span>
        <Team name={match.away_team} side="Visita" end />
      </div>
      {split && (
        <div className="flex flex-col gap-3 border-t pt-5">
          <p className="eyebrow">{source}</p>
          <div className="grid grid-cols-3 gap-3">
            {OUTCOMES.map((o) => (
              <div
                key={o}
                className={cn(
                  "flex flex-col",
                  o === "draw" && "items-center",
                  o === "away" && "items-end",
                )}
              >
                <span className="num text-2xl font-semibold tracking-tight sm:text-3xl">
                  {pct(split[o], 0)}
                </span>
                <span className="text-xs text-muted-foreground">{OUTCOME_LABEL[o]}</span>
              </div>
            ))}
          </div>
          <SplitBar values={split} />
        </div>
      )}
      {match.warning && (
        <p className="flex items-center gap-2 rounded-lg bg-experimental-soft px-3 py-2.5 text-sm text-experimental">
          <TriangleAlert aria-hidden className="size-4 shrink-0" />
          {match.warning}
        </p>
      )}
    </Card>
  );
}

function Team({ name, side, end = false }: { name: string; side: string; end?: boolean }) {
  return (
    <div className={cn("flex min-w-0 items-center gap-3", end && "flex-row-reverse text-right")}>
      <TeamAvatar name={name} size="lg" />
      <div className={cn("flex min-w-0 flex-col gap-0.5", end && "items-end")}>
        <span className="truncate text-lg font-semibold tracking-tight sm:text-xl">{name}</span>
        <span className="text-xs text-muted-foreground">{side}</span>
      </div>
    </div>
  );
}

function ReferenceAndModel({ match }: { match: ComparatorDetail }) {
  if (!match.fair && !match.model) {
    return <Empty>Sin cuota de referencia ni opinión del modelo para este partido.</Empty>;
  }
  const fair = match.fair;
  const model = match.model;
  return (
    <div className="flex flex-col gap-3">
      <Table aria-label="Referencia y modelo">
        <TableHeader>
          <TableRow>
            <TableHead>Resultado</TableHead>
            <TableHead className="text-right">Cuota justa</TableHead>
            <TableHead className="text-right">Justa</TableHead>
            <TableHead className="text-right">Modelo</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {OUTCOMES.map((o) => (
            <TableRow key={o}>
              <TableHead scope="row" className="text-foreground">
                <span className="inline-flex items-center gap-2">
                  <span aria-hidden className={cn("size-2 rounded-full", OUTCOME_TONE[o])} />
                  {OUTCOME_LABEL[o]}
                </span>
              </TableHead>
              <TableCell className="num text-right font-semibold">
                {fair ? odds(fair.odds[o]) : "—"}
              </TableCell>
              <TableCell className="num text-right">
                {fair ? pct(fair.probabilities[o]) : "Sin referencia"}
              </TableCell>
              <TableCell className="num text-right text-muted-foreground">
                {model ? pct(model.probabilities[o]) : "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="text-xs text-muted-foreground">
        {fair ? `Justa: ${fair.source}, sin margen` : "Sin cuota de referencia"}
        {model && ` · Modelo: ${model.version ?? "—"}`}
      </p>
    </div>
  );
}

function BooksTable({ match }: { match: ComparatorDetail }) {
  const [showReference, setShowReference] = useState(false);
  if (match.bookmakers.length === 0) return <Empty>Sin cuotas de casas para este partido.</Empty>;
  const bestKey = (o: (typeof OUTCOMES)[number]) => match.best[o]?.bookmaker;
  // Houses you can use from Peru first; the rest are only a price reference.
  const accessible = match.bookmakers.filter((b) => b.accessible);
  const reference = match.bookmakers.filter((b) => !b.accessible);
  const rows =
    showReference || accessible.length === 0 ? [...accessible, ...reference] : accessible;
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
          {rows.map((book) => (
            <TableRow key={book.key}>
              <TableHead scope="row" className="text-foreground">
                {book.key}
                {!book.accessible && (
                  <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                    (referencia)
                  </span>
                )}
              </TableHead>
              {OUTCOMES.map((o) => {
                const isBest = bestKey(o) === book.key;
                return (
                  <TableCell key={o} className="num text-right">
                    <span
                      className={cn(
                        "inline-block rounded-md px-2 py-0.5",
                        isBest && "bg-accent font-semibold text-accent-foreground",
                      )}
                    >
                      {odds(book.odds[o])}
                    </span>
                    {isBest && <span className="sr-only"> (mejor cuota)</span>}
                  </TableCell>
                );
              })}
              <TableCell className="num text-right text-muted-foreground">
                {pct(book.margin)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <p className="num text-xs text-muted-foreground">
          Margen de la mejor combinación: {pct(match.margins.best_combined)} · promedio:{" "}
          {pct(match.margins.average)}
        </p>
        {reference.length > 0 && accessible.length > 0 && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-expanded={showReference}
            onClick={() => setShowReference((v) => !v)}
          >
            {showReference ? "Ocultar" : "Ver"} {reference.length} casas de referencia
            <ChevronDown
              aria-hidden
              className={cn("transition-transform duration-150", showReference && "rotate-180")}
            />
          </Button>
        )}
      </div>
    </>
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
    <div className="h-60" aria-label="Gráfico de la cuota de referencia" role="img">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ left: -12, right: 8, top: 8 }}>
          <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
          <XAxis
            dataKey="at"
            fontSize={11}
            stroke="var(--chart-text)"
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            domain={["auto", "auto"]}
            fontSize={11}
            stroke="var(--chart-text)"
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            contentStyle={{
              background: "var(--popover)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              color: "var(--popover-foreground)",
              fontSize: 12,
            }}
          />
          <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
          {OUTCOMES.map((o) => (
            <Line
              key={o}
              type="monotone"
              dataKey={OUTCOME_LABEL[o]}
              stroke={OUTCOME_STROKE[o]}
              strokeWidth={2}
              dot={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
