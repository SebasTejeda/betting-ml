import {
  ChevronDown,
  Clock,
  Gauge,
  History,
  Info,
  ListChecks,
  NotebookPen,
  RefreshCw,
  Search,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  TriangleAlert,
} from "lucide-react";
import { useId, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  useAnalysis,
  useEventOddsEstimate,
  useFixture,
  useRefreshEventOdds,
  useTeamSearch,
  type AnalysisParams,
} from "../api/hooks";
import {
  CONFIDENCE_LABEL,
  MARKET_LABEL,
  type AdviceItem,
  type Analysis,
  type Confidence,
  type FormMatch,
  type MarketGroup,
  type MarketSelection,
  type Reason,
  type TeamForm,
} from "../api/types";
import {
  Empty,
  ErrorBox,
  EvValue,
  EXPERIMENTAL_LABEL,
  ExperimentalBadge,
  Loading,
  PageTitle,
  Panel,
} from "../components/common";
import { RegisterBetForm } from "../components/RegisterBetForm";
import { TeamAvatar } from "../components/TeamAvatar";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../components/ui/table";
import { odds as fmtOdds, pct } from "../lib/format";
import { cn } from "../lib/utils";

const COMPETITIONS = [
  { value: "", label: "Automática" },
  { value: "UCL", label: "Champions League" },
  { value: "UEL", label: "Europa League" },
];

/** Analysis of a match (spec 003): markets, the most likely selections with an honest price,
 *  recent form and head-to-head. "Mejores opciones" stays disabled until there is evidence. */
export function AnalysisPage() {
  const [params, setParams] = useSearchParams();
  const home = params.get("home") ?? "";
  const away = params.get("away") ?? "";
  const date = params.get("date") ?? "";
  const competition = params.get("competition") ?? "";
  const matchParam = params.get("match") ?? "";
  const searchOnly = !home || !away;

  // Without an explicit date/match, look for the next fixture between both teams first.
  const needsFixture = !searchOnly && !matchParam && !date;
  const fixture = useFixture(needsFixture ? home : "", needsFixture ? away : "");
  const query: AnalysisParams | null = useMemo(() => {
    if (searchOnly) return null;
    if (matchParam) return { home, away, matchId: matchParam };
    if (date) return { home, away, date, competition };
    if (fixture.isPending && fixture.fetchStatus !== "idle") return null;
    const found = fixture.data?.found ? fixture.data : null;
    return found
      ? { home, away, matchId: found.match_id ?? undefined }
      : { home, away, competition };
  }, [
    searchOnly,
    matchParam,
    date,
    competition,
    home,
    away,
    fixture.data,
    fixture.isPending,
    fixture.fetchStatus,
  ]);
  const analysis = useAnalysis(query);

  return (
    <div className="flex flex-col gap-4">
      <PageTitle
        icon={Sparkles}
        description="Elige dos equipos: probabilidades de muchos mercados, lo más probable con su precio honesto y la forma reciente. Son probabilidades, no certezas."
      >
        Análisis de partido
      </PageTitle>
      <SearchForm
        // Remount when the URL changes (e.g. "Analizar" from another page) to show it.
        key={`${home}|${away}|${date}|${competition}`}
        initial={{ home, away, date, competition }}
        onSubmit={(next) => {
          const out = new URLSearchParams();
          out.set("home", next.home);
          out.set("away", next.away);
          if (next.date) out.set("date", next.date);
          if (next.competition) out.set("competition", next.competition);
          setParams(out);
        }}
      />
      {searchOnly ? (
        <Empty icon={Search} title="Elige un partido">
          Escribe el local y la visita (por ejemplo, Real Madrid y RB Leipzig).
        </Empty>
      ) : analysis.isPending || query === null ? (
        <Loading what="el análisis" />
      ) : analysis.isError ? (
        <AnalysisError error={analysis.error} />
      ) : (
        <AnalysisView data={analysis.data} />
      )}
    </div>
  );
}

type SearchValues = { home: string; away: string; date: string; competition: string };

function SearchForm({
  initial,
  onSubmit,
}: {
  initial: SearchValues;
  onSubmit: (values: SearchValues) => void;
}) {
  const [values, setValues] = useState(initial);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (values.home.trim() && values.away.trim()) onSubmit(values);
  };
  return (
    <Card className="px-4 py-4 shadow-sm">
      <form
        className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_10rem_11rem_auto] lg:items-end"
        onSubmit={submit}
        aria-label="Buscar partido"
      >
        <TeamInput
          label="Local"
          value={values.home}
          onChange={(home) => setValues((v) => ({ ...v, home }))}
        />
        <TeamInput
          label="Visita"
          value={values.away}
          onChange={(away) => setValues((v) => ({ ...v, away }))}
        />
        <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Fecha (opcional)
          <input
            type="date"
            className="field"
            value={values.date}
            onChange={(e) => setValues((v) => ({ ...v, date: e.target.value }))}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Competición
          <select
            className="field"
            value={values.competition}
            onChange={(e) => setValues((v) => ({ ...v, competition: e.target.value }))}
          >
            {COMPETITIONS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" size="lg">
          <Search aria-hidden />
          Analizar
        </Button>
      </form>
    </Card>
  );
}

function TeamInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const listId = useId();
  const hits = useTeamSearch(value);
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
      {label}
      <input
        className="field"
        list={listId}
        autoComplete="off"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Escribe al menos 2 letras"
      />
      <datalist id={listId}>
        {(hits.data ?? []).map((t) => (
          <option key={`${t.league}-${t.name}`} value={t.name}>
            {t.league}
          </option>
        ))}
      </datalist>
    </label>
  );
}

function AnalysisError({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.code === "TEAM_NOT_FOUND") {
    return (
      <Empty icon={Search} title="Equipo no encontrado">
        {error.message}. Revisa el nombre o elige uno de la lista.
      </Empty>
    );
  }
  if (error instanceof ApiError && error.code === "RATINGS_UNAVAILABLE") {
    return (
      <Empty icon={TriangleAlert} title="Sin rating para este partido">
        Uno de los equipos no tiene rating o su liga no está en el catálogo: no hay análisis entre
        ligas para este partido.
      </Empty>
    );
  }
  return <ErrorBox error={error} />;
}

function AnalysisView({ data }: { data: Analysis }) {
  return (
    <div className="flex flex-col gap-4">
      <Scoreboard data={data} />
      <EventOdds data={data} />
      <div className="grid gap-4 lg:grid-cols-2">
        <BestOptions data={data} />
        <MostLikely data={data} />
      </div>
      <FormPanel data={data} />
      <MarketsPanel data={data} />
    </div>
  );
}

function Scoreboard({ data }: { data: Analysis }) {
  const m = data.match;
  return (
    <Card className="gap-4 bg-linear-to-b from-secondary/60 to-card px-4 py-6 shadow-sm">
      <div className="flex flex-wrap items-center justify-center gap-2 text-xs text-muted-foreground">
        <Badge variant="secondary">{m.competition}</Badge>
        <Clock aria-hidden className="size-3.5" />
        {m.date}
        {m.cross_league && (
          <Badge variant="outline" className="border-experimental-border text-experimental">
            Entre ligas
          </Badge>
        )}
      </div>
      <h2 className="sr-only">
        {m.home_team} – {m.away_team}
      </h2>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
        <TeamSide
          name={m.home_team}
          side="Local"
          goals={m.expected_goals.home}
          rating={m.ratings?.home}
        />
        <span aria-hidden className="text-2xl font-light text-muted-foreground">
          vs
        </span>
        <TeamSide
          name={m.away_team}
          side="Visita"
          goals={m.expected_goals.away}
          rating={m.ratings?.away}
        />
      </div>
      {m.warnings.length > 0 && (
        <ul className="mx-auto flex max-w-3xl flex-col gap-1 text-sm text-experimental">
          {m.warnings.map((w) => (
            <li key={w} className="flex items-start gap-1.5">
              <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
              {w}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function TeamSide({
  name,
  side,
  goals,
  rating,
}: {
  name: string;
  side: string;
  goals: number;
  rating?: number;
}) {
  return (
    <div className="flex flex-col items-center gap-1.5 text-center">
      <TeamAvatar name={name} size="lg" />
      <span className="text-base font-semibold sm:text-xl">{name}</span>
      <span className="text-xs text-muted-foreground">{side}</span>
      <span className="text-sm tabular-nums">
        <span className="sr-only">Goles esperados: </span>
        <strong className="text-lg">{goals.toFixed(2)}</strong>{" "}
        <span className="text-xs text-muted-foreground">goles esperados</span>
      </span>
      {rating !== undefined && (
        <span className="text-xs text-muted-foreground tabular-nums">Elo {rating.toFixed(0)}</span>
      )}
    </div>
  );
}

function EventOdds({ data }: { data: Analysis }) {
  const m = data.match;
  const estimate = useEventOddsEstimate(m.match_id);
  const refresh = useRefreshEventOdds();
  return (
    <Card className="flex flex-col gap-2 px-4 py-3 text-sm shadow-sm sm:flex-row sm:items-center sm:justify-between">
      <span className="text-muted-foreground">
        {m.odds_snapshot_at
          ? `Cuotas por evento del ${new Date(m.odds_snapshot_at).toLocaleString("es-PE")}.`
          : "Sin cuotas por evento: se usan las cuotas 1X2 del comparador o solo cuotas justas."}
        {estimate.data && (
          <>
            {" "}
            Actualizar cuesta unos {estimate.data.estimated_credits} créditos
            {estimate.data.credits_remaining !== null &&
              ` (quedan ${estimate.data.credits_remaining})`}
            .
          </>
        )}
      </span>
      <div className="flex flex-col items-start gap-1 sm:items-end">
        <Button
          type="button"
          variant="outline"
          disabled={refresh.isPending}
          onClick={() =>
            refresh.mutate({ matchId: m.match_id, home: m.home_team, away: m.away_team })
          }
        >
          <RefreshCw aria-hidden className={cn(refresh.isPending && "animate-spin")} />
          Actualizar cuotas de este partido
        </Button>
        {refresh.isError && <ErrorBox error={refresh.error} />}
        {refresh.data && (
          <span role="status" className="text-xs text-muted-foreground">
            {refresh.data.from_cache
              ? "Cuotas recientes en caché: no se gastaron créditos."
              : `Se usaron ${refresh.data.credits_used} créditos.`}
          </span>
        )}
      </div>
    </Card>
  );
}

function BestOptions({ data }: { data: Analysis }) {
  return (
    <Panel title="Mejores opciones" icon={Sparkles} action={<ExperimentalBadge />}>
      {data.best_options.length > 0 ? (
        <div className="flex flex-col gap-3">
          {data.best_options.map((item) => (
            <AdviceCard
              key={`${item.market}-${item.selection}-${item.line}`}
              item={item}
              data={data}
            />
          ))}
        </div>
      ) : (
        <p className="flex items-start gap-2 text-sm text-muted-foreground">
          <Info aria-hidden className="mt-0.5 size-4 shrink-0" />
          {data.best_options_note ?? data.no_value_message}
        </p>
      )}
    </Panel>
  );
}

function MostLikely({ data }: { data: Analysis }) {
  return (
    <Panel title="Lo más probable" icon={ListChecks}>
      <p className="mb-3 text-xs text-muted-foreground">
        Lo más probable no es lo mismo que lo mejor: cada opción dice si su cuota la paga bien o
        mal.
      </p>
      {data.most_likely.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Ninguna selección tiene confianza suficiente para destacarla. La tabla de mercados queda
          como información.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {data.most_likely.map((item) => (
            <AdviceCard
              key={`${item.market}-${item.selection}-${item.line}`}
              item={item}
              data={data}
            />
          ))}
        </div>
      )}
    </Panel>
  );
}

function AdviceCard({ item, data }: { item: AdviceItem; data: Analysis }) {
  const [open, setOpen] = useState(false);
  return (
    <article className="flex flex-col gap-2 rounded-xl border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium">{item.label}</h3>
        <div className="flex flex-wrap items-center gap-1.5">
          <ConfidenceBadge level={item.confidence as Confidence} />
          {item.verdict === "valor" && <ExperimentalBadge />}
        </div>
      </div>
      <ProbabilityBar probability={item.probability} />
      <p className="text-sm">{item.price_comment}</p>
      {item.reasons.length > 0 && (
        <ul className="flex flex-col gap-1 text-sm">
          {item.reasons.map((reason) => (
            <ReasonLine key={reason.text} reason={reason} />
          ))}
        </ul>
      )}
      {item.warnings.map((w) => (
        <p key={w} className="flex items-start gap-1.5 text-xs text-experimental">
          <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          {w}
        </p>
      ))}
      <div>
        <Button type="button" variant="ghost" size="sm" onClick={() => setOpen((v) => !v)}>
          <NotebookPen aria-hidden />
          Registrar en papel
        </Button>
      </div>
      {open && <SelectionBetForm data={data} item={item} />}
    </article>
  );
}

function SelectionBetForm({
  data,
  item,
}: {
  data: Analysis;
  item: Pick<
    AdviceItem,
    "market" | "selection" | "line" | "label" | "best_odds" | "bookmaker" | "verdict"
  >;
}) {
  const h2h = item.market === "h2h";
  return (
    <RegisterBetForm
      matchId={data.match.match_id}
      market={item.market}
      outcome={h2h ? (item.selection as "home" | "draw" | "away") : undefined}
      selection={h2h ? null : item.selection}
      line={item.line}
      label={item.label}
      odds={item.best_odds}
      bookmaker={item.bookmaker}
      fromSignal={item.verdict === "valor"}
      defaultKind="paper"
    />
  );
}

function ReasonLine({ reason }: { reason: Reason }) {
  const Icon = reason.stance === "for" ? ThumbsUp : reason.stance === "against" ? ThumbsDown : Info;
  const label = { for: "A favor", against: "En contra", context: "Contexto" }[reason.stance];
  return (
    <li className="flex items-start gap-2">
      <Icon
        aria-label={label}
        className={cn(
          "mt-0.5 size-4 shrink-0",
          reason.stance === "for" && "text-positive",
          reason.stance === "against" && "text-negative",
          reason.stance === "context" && "text-muted-foreground",
        )}
      />
      <span>{reason.text}</span>
    </li>
  );
}

function ConfidenceBadge({ level }: { level: Confidence }) {
  return (
    <Badge
      variant={level === "baja" ? "outline" : "secondary"}
      className={cn(level === "baja" && "text-muted-foreground")}
    >
      <Gauge aria-hidden />
      {CONFIDENCE_LABEL[level]}
    </Badge>
  );
}

function ProbabilityBar({ probability }: { probability: number }) {
  return (
    <div className="flex items-center gap-2">
      <div
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(probability * 100)}
        aria-label="Probabilidad del modelo"
        className="h-2 flex-1 overflow-hidden rounded-full bg-muted"
      >
        <div className="h-full bg-primary" style={{ width: `${probability * 100}%` }} />
      </div>
      <span className="w-12 text-right text-sm font-medium tabular-nums">
        {pct(probability, 0)}
      </span>
    </div>
  );
}

// ------------------------------------------------------------------------------ form

const RESULT_STYLE: Record<FormMatch["result"], string> = {
  W: "bg-positive text-white",
  D: "bg-muted-foreground/70 text-white",
  L: "bg-negative text-white",
};
const RESULT_LABEL: Record<FormMatch["result"], string> = { W: "V", D: "E", L: "D" };

function FormPanel({ data }: { data: Analysis }) {
  const h2h = data.form.h2h;
  return (
    <Panel title="Forma reciente" icon={History}>
      <div className="grid gap-4 md:grid-cols-2">
        <TeamFormCard form={data.form.home} />
        <TeamFormCard form={data.form.away} />
      </div>
      <details className="mt-4 rounded-lg border p-3 text-sm">
        <summary className="cursor-pointer font-medium">
          Enfrentamientos directos ({h2h.matches.length})
        </summary>
        <p className="mt-2 text-xs text-muted-foreground">{h2h.note}</p>
        {h2h.matches.length === 0 ? (
          <p className="mt-2 text-muted-foreground">Sin enfrentamientos en los últimos 5 años.</p>
        ) : (
          <ul className="mt-2 flex flex-col gap-1 tabular-nums">
            {h2h.matches.map((m) => (
              <li key={`${m.date}-${m.home_team}`}>
                {m.date} · {m.competition} · {m.home_team} {m.home_goals}–{m.away_goals}{" "}
                {m.away_team}
              </li>
            ))}
          </ul>
        )}
      </details>
    </Panel>
  );
}

function TeamFormCard({ form }: { form: TeamForm }) {
  const s = form.summary;
  const v = form.summary_venue;
  const venue = v.venue === "home" ? "de local" : "de visita";
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <TeamAvatar name={form.team} size="sm" />
        <h3 className="font-medium">{form.team}</h3>
      </div>
      {form.last6.length === 0 ? (
        <p className="text-sm text-muted-foreground">Sin partidos previos con datos.</p>
      ) : (
        <ol className="flex flex-wrap gap-1.5" aria-label={`Últimos partidos de ${form.team}`}>
          {form.last6.map((m) => (
            <li
              key={`${m.date}-${m.opponent}`}
              title={`${m.date} · ${m.competition} · ${m.venue === "home" ? "local" : "visita"} vs ${m.opponent} ${m.goals_for}-${m.goals_against}`}
              className={cn(
                "flex size-8 items-center justify-center rounded-md text-xs font-semibold",
                RESULT_STYLE[m.result],
              )}
            >
              <span aria-hidden>{RESULT_LABEL[m.result]}</span>
              <span className="sr-only">
                {m.result === "W" ? "Victoria" : m.result === "D" ? "Empate" : "Derrota"} ante{" "}
                {m.opponent} {m.goals_for}-{m.goals_against}
              </span>
            </li>
          ))}
        </ol>
      )}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <Stat
          label="Goles a favor / en contra"
          value={`${num(s.goals_for_avg)} / ${num(s.goals_against_avg)}`}
        />
        <Stat
          label="xG a favor / en contra"
          value={`${num(s.xg_for_avg)} / ${num(s.xg_against_avg)}`}
        />
        <Stat label="Partidos con +2.5 goles" value={pct(s.over25_pct, 0)} />
        <Stat label="Ambos marcan" value={pct(s.btts_pct, 0)} />
        <Stat label="Marcó 2 o más" value={`${s.scored_2plus} de ${s.n}`} />
        <Stat
          label={
            v.fallback_to_all ? "Goles a favor (todos sus partidos)" : `Goles a favor ${venue}`
          }
          value={num(v.goals_for_avg)}
        />
      </dl>
      {form.warnings.map((w) => (
        <p key={w} className="text-xs text-experimental">
          {w}
        </p>
      ))}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right font-medium tabular-nums">{value}</dd>
    </>
  );
}

function num(value: number | null | undefined): string {
  return value === null || value === undefined ? "sin dato" : value.toFixed(2);
}

// ------------------------------------------------------------------------------ markets

function MarketsPanel({ data }: { data: Analysis }) {
  return (
    <Panel title="Mercados" icon={ListChecks}>
      <p className="mb-3 text-xs text-muted-foreground">
        Probabilidad del modelo, cuota justa (1/p), mejor cuota disponible y EV. Los mercados de
        confianza baja son solo información. {EXPERIMENTAL_LABEL}.
      </p>
      <div className="flex flex-col gap-2">
        {data.markets.map((market) => (
          <MarketGroupTable
            key={market.market}
            market={market}
            data={data}
            open={market.market === "h2h" || market.market === "totals"}
          />
        ))}
      </div>
    </Panel>
  );
}

function MarketGroupTable({
  market,
  data,
  open,
}: {
  market: MarketGroup;
  data: Analysis;
  open: boolean;
}) {
  const [sortByEv, setSortByEv] = useState(false);
  const [registering, setRegistering] = useState<string | null>(null);
  const rows = sortByEv
    ? [...market.selections].sort((a, b) => (b.ev ?? -Infinity) - (a.ev ?? -Infinity))
    : market.selections;
  return (
    <details open={open} className="group rounded-lg border">
      <summary className="flex cursor-pointer items-center justify-between gap-2 px-3 py-2 font-medium">
        <span>{market.name || MARKET_LABEL[market.market]}</span>
        <ChevronDown aria-hidden className="size-4 transition-transform group-open:rotate-180" />
      </summary>
      <div className="flex justify-end px-3">
        <Button type="button" variant="ghost" size="sm" onClick={() => setSortByEv((v) => !v)}>
          Ordenar por {sortByEv ? "probabilidad" : "EV"}
        </Button>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Selección</TableHead>
            <TableHead className="min-w-32">Probabilidad</TableHead>
            <TableHead className="text-right">Cuota justa</TableHead>
            <TableHead className="text-right">Mejor cuota</TableHead>
            <TableHead className="text-right">EV</TableHead>
            <TableHead>Confianza</TableHead>
            <TableHead>
              <span className="sr-only">Registrar</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((s) => {
            const key = `${s.selection}-${s.line}`;
            return (
              <SelectionRow
                key={key}
                s={s}
                onRegister={() => setRegistering(registering === key ? null : key)}
                form={
                  registering === key ? (
                    <SelectionBetForm data={data} item={{ market: market.market, ...s }} />
                  ) : null
                }
              />
            );
          })}
        </TableBody>
      </Table>
    </details>
  );
}

function SelectionRow({
  s,
  onRegister,
  form,
}: {
  s: MarketSelection;
  onRegister: () => void;
  form: ReactNode;
}) {
  return (
    <>
      <TableRow className={cn(s.information_only && "text-muted-foreground")}>
        <TableCell className="min-w-40 whitespace-normal">{s.label}</TableCell>
        <TableCell>
          <ProbabilityBar probability={s.probability} />
        </TableCell>
        <TableCell className="text-right tabular-nums">{fmtOdds(s.fair_odds)}</TableCell>
        <TableCell className="text-right tabular-nums">
          {s.best_odds ? (
            <>
              {fmtOdds(s.best_odds)}
              <span className="block text-xs text-muted-foreground">{s.bookmaker}</span>
            </>
          ) : (
            <span className="text-xs">sin cuota</span>
          )}
        </TableCell>
        <TableCell className="text-right">
          <EvValue ev={s.ev} />
        </TableCell>
        <TableCell>
          <ConfidenceBadge level={s.confidence as Confidence} />
        </TableCell>
        <TableCell>
          <Button type="button" variant="ghost" size="sm" onClick={onRegister}>
            <NotebookPen aria-hidden />
            Registrar
          </Button>
        </TableCell>
      </TableRow>
      {form && (
        <TableRow>
          <TableCell colSpan={7} className="whitespace-normal">
            {form}
          </TableCell>
        </TableRow>
      )}
    </>
  );
}
