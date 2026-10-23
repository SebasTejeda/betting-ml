import {
  ChartColumn,
  CircleCheck,
  CircleMinus,
  CircleX,
  Hourglass,
  type LucideIcon,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useId, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  useBets,
  useDeleteBet,
  useSettings,
  useSettleBets,
  useSummary,
  useUpdateBet,
  type BetsParams,
  type SummaryKind,
} from "../api/hooks";
import {
  MARKET_LABEL,
  OUTCOME_LABEL,
  type Bet,
  type MarketSummary,
  type Summary,
} from "../api/types";
import {
  Empty,
  ErrorBox,
  ExperimentalBadge,
  Loading,
  Meter,
  PageTitle,
  Panel,
} from "../components/common";
import { Badge } from "../components/ui/badge";
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
import { kickoff, money, odds, pct } from "../lib/format";
import { evTone } from "../lib/tone";
import { cn } from "../lib/utils";

const STATUS_LABEL: Record<string, string> = {
  pendiente: "Pendiente",
  ganada: "Ganada",
  perdida: "Perdida",
  nula: "Nula",
};

const STATUS_STYLE: Record<string, { icon: LucideIcon; className: string }> = {
  pendiente: { icon: Hourglass, className: "bg-info-soft text-info" },
  ganada: { icon: CircleCheck, className: "bg-positive-soft text-positive" },
  perdida: { icon: CircleX, className: "bg-negative-soft text-negative" },
  nula: { icon: CircleMinus, className: "bg-secondary text-muted-foreground" },
};

const TOOLTIP_STYLE = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  color: "var(--popover-foreground)",
};

// The API keeps the market codes; the page speaks Spanish (unknown codes are shown as they are).
const SELECTION_WORD: Record<string, string> = {
  over: "más de",
  under: "menos de",
  yes: "sí",
  no: "no",
  home: "local",
  draw: "empate",
  away: "visita",
};

/** Bets on the spec-003 markets: "Más/Menos goles · más de 2.5". */
function selectionLabel(bet: Bet): string {
  const line = bet.line === null || bet.line === undefined ? "" : ` ${bet.line}`;
  const selection = bet.selection ? (SELECTION_WORD[bet.selection] ?? bet.selection) : "";
  return `${MARKET_LABEL[bet.market] ?? bet.market} · ${selection}${line}`;
}

export function BetsPage() {
  const [kind, setKind] = useState<SummaryKind>("real");
  const [status, setStatus] = useState<BetsParams["status"]>(undefined);
  const [page, setPage] = useState(1);
  const settings = useSettings();
  const currency = settings.data?.currency ?? "PEN";
  const summary = useSummary(kind);
  const settle = useSettleBets();

  return (
    <>
      <PageTitle
        description="Tu diario de apuestas reales y en papel: el CLV dice si le ganas a la cuota de cierre, y el límite mensual protege tu bankroll."
        aside={
          <div className="flex flex-col items-start gap-1.5 text-sm sm:items-end">
            <Button
              type="button"
              variant="outline"
              disabled={settle.isPending}
              onClick={() => settle.mutate()}
            >
              <RefreshCw aria-hidden className={settle.isPending ? "animate-spin" : undefined} />
              Liquidar con resultados oficiales
            </Button>
            {settle.isSuccess && (
              <span role="status" className="text-xs text-muted-foreground">
                {settle.data.settled} liquidadas · {settle.data.clv_computed} con CLV ·{" "}
                {settle.data.still_pending} pendientes
                {settle.data.corrected > 0 && ` · ${settle.data.corrected} corregidas`}
              </span>
            )}
            {settle.isError && <ErrorBox error={settle.error} />}
          </div>
        }
      >
        Mis apuestas
      </PageTitle>
      <div className="mt-5 mb-5 flex flex-wrap items-center justify-between gap-3 border-b pb-5">
        <div
          role="group"
          aria-label="Tipo de apuestas"
          className="inline-flex rounded-lg bg-muted p-1"
        >
          {(["real", "paper", "all"] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={kind === value}
              className={cn(
                "min-h-10 rounded-md px-3.5 text-sm transition-colors duration-150 md:min-h-8",
                kind === value
                  ? "bg-card font-medium text-foreground shadow-xs ring-1 ring-border"
                  : "text-muted-foreground hover:text-foreground",
              )}
              onClick={() => {
                setKind(value);
                setPage(1);
              }}
            >
              {value === "real" ? "Reales" : value === "paper" ? "En papel" : "Todas"}
            </button>
          ))}
        </div>
        <p className="max-w-md text-xs text-muted-foreground">
          Con menos de 300 apuestas el ROI es mayormente ruido: mira el CLV (si le ganas a la cuota
          de cierre de la referencia).
        </p>
      </div>
      <div className="flex flex-col gap-5">
        {summary.isPending ? (
          <Loading what="el resumen" variant="cards" />
        ) : summary.isError ? (
          <ErrorBox error={summary.error} />
        ) : (
          <SummaryFigures summary={summary.data} currency={currency} />
        )}
        {/* The bets stay usable even when the summary fails. */}
        <Panel
          title="Apuestas"
          action={
            <label className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
              Estado
              <select
                className="field h-10 w-36 md:h-8"
                value={status ?? ""}
                onChange={(event) => {
                  setStatus((event.target.value || undefined) as BetsParams["status"]);
                  setPage(1);
                }}
              >
                <option value="">Todos</option>
                {Object.entries(STATUS_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          }
        >
          <BetsTable
            params={{ kind: kind === "all" ? undefined : kind, status, page }}
            currency={currency}
            onPage={setPage}
          />
          <p className="mt-4 border-t pt-3 text-xs text-muted-foreground">
            Liquidar a mano solo es posible después del inicio del partido, y borrar solo antes. Una
            apuesta marcada a mano como ganada o nula cuenta como perdida para el límite mensual
            hasta que se confirme con el resultado oficial, y una apuesta real sin liquidar de un
            partido ya terminado (más de 3 h) también cuenta como perdida hasta liquidarla. Si un
            partido se aplaza, márcala como nula.
          </p>
        </Panel>
        {summary.data && <SummaryCharts summary={summary.data} currency={currency} />}
      </div>
    </>
  );
}

function Kpi({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: string;
  tone?: string;
  hint?: string;
}) {
  return (
    // gap-px over a border-coloured grid: one hairline between figures, in every layout.
    <div className="flex flex-col gap-1 bg-card px-4 py-4 sm:px-5">
      <dt className="eyebrow">{label}</dt>
      <dd className={cn("num text-2xl font-semibold tracking-tight", tone)}>{value}</dd>
      {hint && <dd className="text-xs text-muted-foreground">{hint}</dd>}
    </div>
  );
}

function SummaryFigures({ summary, currency }: { summary: Summary; currency: string }) {
  const month = summary.month;
  const used = month.loss_limit > 0 ? Math.min(1, month.current_loss / month.loss_limit) : 1;
  const signal = summary.experimental_signal;
  return (
    <div className="flex flex-col gap-5">
      {/* One strip, not six boxes: the figures are read together (CLV first, ROI is noise). */}
      <Card className="py-0">
        <dl
          aria-label="Indicadores"
          className="grid grid-cols-2 gap-px bg-border md:grid-cols-3 xl:grid-cols-6"
        >
          <Kpi label="Apuestas (liquidadas)" value={`${summary.bets} (${summary.settled})`} />
          <Kpi
            label="CLV medio"
            value={pct(summary.clv_mean, 2, true)}
            tone={evTone(summary.clv_mean)}
          />
          <Kpi label="% CLV positivo" value={pct(summary.clv_positive_rate, 0)} />
          <Kpi
            label="Beneficio"
            value={money(summary.profit, currency)}
            tone={evTone(summary.profit)}
          />
          <Kpi
            label="ROI"
            value={pct(summary.roi, 1, true)}
            tone={evTone(summary.roi)}
            hint="ruido con pocas apuestas"
          />
          <Kpi
            label="Mejor cuota vs promedio"
            value={pct(summary.best_odds_uplift_mean, 1, true)}
          />
        </dl>
      </Card>
      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Límite mensual">
          <p className="mb-3 flex flex-wrap items-baseline gap-x-1.5 text-sm text-muted-foreground">
            Pérdida del mes:
            <strong className="num text-2xl font-semibold tracking-tight text-foreground">
              {money(month.current_loss, currency)}
            </strong>
            <span className="num">de {money(month.loss_limit, currency)}</span>
          </p>
          {/* Blue while there is room; amber from 80 %, red at the limit. */}
          <Meter
            label="Uso del límite mensual"
            value={Math.round(used * 100)}
            tone={used >= 1 ? "negative" : used >= 0.8 ? "experimental" : "primary"}
          />
          <p className="num mt-2 text-xs text-muted-foreground">
            Disponible: {money(month.remaining, currency)}
            {month.remaining <= 0 && " · apuestas reales bloqueadas hasta el mes siguiente"}
          </p>
        </Panel>
        <Panel title="Progreso de la señal" action={<ExperimentalBadge />}>
          <p className="mb-3 flex flex-wrap items-baseline gap-x-1.5 text-sm text-muted-foreground">
            <strong className="num text-2xl font-semibold tracking-tight text-foreground">
              {signal.paper_bets}/{signal.target}
            </strong>
            apuestas en papel liquidadas · CLV acumulado
            <strong className={cn("num", evTone(signal.clv_mean))}>
              {pct(signal.clv_mean, 2, true)}
            </strong>
          </p>
          <Meter
            label="Apuestas en papel de la señal"
            value={signal.paper_bets}
            max={signal.target}
            tone="experimental"
          />
          <p className="mt-2 text-xs text-muted-foreground">
            {signal.evidence_met
              ? "Condición cumplida: 100 apuestas en papel con CLV medio positivo."
              : "Sin evidencia todavía. Al llegar a 100 apuestas en papel con CLV positivo habrá evidencia real."}
          </p>
        </Panel>
      </div>
    </div>
  );
}

function SummaryCharts({ summary, currency }: { summary: Summary; currency: string }) {
  const nothingSettled =
    summary.bankroll.series.length < 2 &&
    summary.by_league.length === 0 &&
    summary.by_bookmaker.length === 0;
  return (
    <>
      {nothingSettled ? (
        // One quiet line instead of two empty chart panels.
        <Panel title="Bankroll y CLV por liga y casa">
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <ChartColumn aria-hidden className="size-4 shrink-0" />
            Aún no hay apuestas liquidadas: la curva de bankroll y el CLV por liga y casa aparecen
            al liquidar las primeras.
          </p>
        </Panel>
      ) : (
        <div className="grid gap-5 lg:grid-cols-3">
          <Panel title="Bankroll" className="lg:col-span-2">
            {summary.bankroll.series.length < 2 ? (
              <Empty icon={ChartColumn}>Aún no hay apuestas liquidadas.</Empty>
            ) : (
              <BankrollChart series={summary.bankroll.series} currency={currency} />
            )}
          </Panel>
          <Panel title="Por liga y casa (CLV medio)">
            {summary.by_league.length === 0 && summary.by_bookmaker.length === 0 ? (
              <Empty>Sin apuestas liquidadas con CLV.</Empty>
            ) : (
              <>
                <GroupBars groups={summary.by_league} name="league" label="Por liga" />
                <GroupBars groups={summary.by_bookmaker} name="bookmaker" label="Por casa" />
              </>
            )}
          </Panel>
        </div>
      )}
      <MarketsEvidence markets={summary.by_market} />
    </>
  );
}

/** Spec 003 US6: CLV and bets per market. A market only leaves EXPERIMENTAL with ≥ 100 paper
 *  bets with mean CLV > 0 (manual change in configs/markets.yaml). */
function MarketsEvidence({ markets }: { markets: MarketSummary[] }) {
  return (
    <Panel title="Evidencia por mercado" action={<ExperimentalBadge />}>
      {markets.length === 0 ? (
        <Empty>Aún no hay apuestas.</Empty>
      ) : (
        <Table>
          <TableCaption className="sr-only">
            Evidencia por mercado: apuestas, ROI y CLV
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>Mercado</TableHead>
              <TableHead className="text-right">Apuestas (liquidadas)</TableHead>
              <TableHead className="text-right">ROI</TableHead>
              <TableHead className="text-right">CLV vs Pinnacle</TableHead>
              <TableHead className="text-right">CLV vs cierre promedio</TableHead>
              <TableHead className="min-w-40">Papel con CLV</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {markets.map((m) => (
              <TableRow key={m.market}>
                <TableCell className="font-medium">{MARKET_LABEL[m.market] ?? m.market}</TableCell>
                <TableCell className="num text-right">
                  {m.bets} ({m.settled})
                </TableCell>
                <TableCell className={cn("num text-right", evTone(m.roi))}>
                  {pct(m.roi, 1, true)}
                </TableCell>
                <TableCell className={cn("num text-right", evTone(m.clv_mean_pinnacle))}>
                  {pct(m.clv_mean_pinnacle, 2, true)}{" "}
                  <span className="text-xs text-muted-foreground">n={m.clv_n_pinnacle}</span>
                </TableCell>
                <TableCell className={cn("num text-right", evTone(m.clv_mean_market_average))}>
                  {pct(m.clv_mean_market_average, 2, true)}{" "}
                  <span className="text-xs text-muted-foreground">n={m.clv_n_market_average}</span>
                </TableCell>
                <TableCell>
                  <Meter
                    label={`Apuestas en papel con CLV en ${MARKET_LABEL[m.market] ?? m.market}`}
                    value={Math.min(m.paper_with_clv, m.evidence_target)}
                    max={m.evidence_target}
                    tone="experimental"
                  />
                  <span className="text-xs text-muted-foreground">
                    {m.paper_with_clv}/{m.evidence_target}
                    {m.evidence_met ? " · condición cumplida" : ""}
                  </span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <ul className="mt-3 flex list-disc flex-col gap-1 pl-5 text-xs text-muted-foreground">
        <li>
          El cierre promedio del mercado es una referencia más débil que Pinnacle: su CLV no
          equivale al de Pinnacle.
        </li>
        <li>
          Por ahora solo 1X2 y Más/Menos 2.5 de partidos de liga tienen CLV; el resto de mercados no
          tiene cierre de referencia.
        </li>
        <li>
          Las apuestas de Champions/Europa League no se liquidan solas: márcalas a mano. Mientras
          estén sin confirmar con un resultado oficial cuentan como pérdida para el límite mensual.
        </li>
      </ul>
    </Panel>
  );
}

function BankrollChart({
  series,
  currency,
}: {
  series: Summary["bankroll"]["series"];
  currency: string;
}) {
  const gradient = useId().replace(/:/g, "");
  return (
    <div className="h-60" role="img" aria-label="Curva de bankroll">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={series} margin={{ left: -8, right: 8, top: 8 }}>
          <defs>
            <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.3} />
              <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
          <XAxis
            dataKey="date"
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
          <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => money(Number(v), currency)} />
          <Area
            type="monotone"
            dataKey="value"
            name="Bankroll"
            stroke="var(--chart-1)"
            strokeWidth={2}
            fill={`url(#${gradient})`}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function GroupBars({
  groups,
  name,
  label,
}: {
  groups: Record<string, unknown>[];
  name: string;
  label: string;
}) {
  if (groups.length === 0) return null;
  const data = groups.map((g) => ({
    name: String(g[name]),
    clv: typeof g["clv_mean"] === "number" ? 100 * g["clv_mean"] : 0,
  }));
  return (
    <div className="mb-3">
      <p className="eyebrow mb-1">{label}</p>
      <div className="h-28" role="img" aria-label={label}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ left: -20, right: 4 }}>
            <XAxis
              dataKey="name"
              fontSize={11}
              stroke="var(--chart-text)"
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              fontSize={11}
              unit="%"
              stroke="var(--chart-text)"
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              cursor={{ fill: "var(--muted)" }}
              formatter={(v) => `${Number(v).toFixed(2)} %`}
            />
            {/* CLV is a signed figure: green above zero, red below (the value is in the tooltip). */}
            <Bar dataKey="clv" name="CLV medio" radius={[4, 4, 0, 0]}>
              {data.map((d) => (
                <Cell key={d.name} fill={d.clv >= 0 ? "var(--positive)" : "var(--negative)"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLE[status] ?? STATUS_STYLE["nula"]!;
  const Icon = style.icon;
  return (
    <Badge className={cn("gap-1 border-transparent", style.className)}>
      <Icon aria-hidden />
      {STATUS_LABEL[status] ?? status}
    </Badge>
  );
}

function BetsTable({
  params,
  currency,
  onPage,
}: {
  params: BetsParams;
  currency: string;
  onPage: (page: number) => void;
}) {
  const bets = useBets(params);
  const update = useUpdateBet();
  const remove = useDeleteBet();

  if (bets.isPending) return <Loading what="apuestas" variant="table" />;
  if (bets.isError) return <ErrorBox error={bets.error} />;
  if (bets.data.items.length === 0) return <Empty>No hay apuestas con estos filtros.</Empty>;
  const pages = Math.max(1, Math.ceil(bets.data.total / bets.data.size));
  return (
    <>
      {update.isError && <ErrorBox error={update.error} />}
      {remove.isError && <ErrorBox error={remove.error} />}
      <Table>
        <TableCaption className="sr-only">Apuestas registradas</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>Partido</TableHead>
            <TableHead>Apuesta</TableHead>
            <TableHead className="text-right">Stake</TableHead>
            <TableHead>Estado</TableHead>
            <TableHead className="text-right">Beneficio</TableHead>
            <TableHead className="text-right">CLV</TableHead>
            <TableHead>Acciones</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {bets.data.items.map((bet) => (
            <BetRow
              key={bet.id}
              bet={bet}
              currency={currency}
              busy={update.isPending || remove.isPending}
              onSettle={(status) =>
                update.mutate({ id: bet.id, patch: { status, version: bet.version } })
              }
              onDelete={() => remove.mutate(bet.id)}
            />
          ))}
        </TableBody>
      </Table>
      {pages > 1 && (
        <nav aria-label="Páginas" className="mt-3 flex items-center gap-2 text-sm">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={params.page <= 1}
            onClick={() => onPage(params.page - 1)}
          >
            Anterior
          </Button>
          <span className="text-muted-foreground">
            Página {params.page} de {pages}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={params.page >= pages}
            onClick={() => onPage(params.page + 1)}
          >
            Siguiente
          </Button>
        </nav>
      )}
    </>
  );
}

function BetRow({
  bet,
  currency,
  busy,
  onSettle,
  onDelete,
}: {
  bet: Bet;
  currency: string;
  busy: boolean;
  onSettle: (status: "ganada" | "perdida" | "nula") => void;
  onDelete: () => void;
}) {
  const [choice, setChoice] = useState<"" | "ganada" | "perdida" | "nula">("");
  const started = bet.kickoff ? new Date(bet.kickoff) <= new Date() : false;
  return (
    <TableRow className="align-top">
      <TableCell className="min-w-44 whitespace-normal">
        <span className="font-medium">
          {bet.home_team && bet.away_team ? `${bet.home_team} – ${bet.away_team}` : bet.match_id}
        </span>
        <div className="num mt-0.5 text-xs text-muted-foreground">
          {bet.league} · {kickoff(bet.kickoff)}
        </div>
      </TableCell>
      <TableCell className="min-w-40 whitespace-normal">
        <span className="font-medium">
          {bet.outcome ? OUTCOME_LABEL[bet.outcome] : selectionLabel(bet)}
        </span>{" "}
        <span className="num font-semibold">{odds(bet.odds)}</span>{" "}
        <span className="text-muted-foreground">· {bet.bookmaker}</span>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          <Badge variant="outline" className="font-normal">
            {bet.kind === "paper" ? "Papel" : "Real"}
          </Badge>
          {bet.from_experimental_signal && <ExperimentalBadge />}
          {bet.sin_referencia && <span className="text-experimental">sin cuota de referencia</span>}
        </div>
      </TableCell>
      <TableCell className="num text-right">{money(bet.stake, currency)}</TableCell>
      <TableCell className="whitespace-normal">
        <StatusBadge status={bet.status} />
        {bet.result_source === "manual" && (
          <div className="mt-1 text-xs text-experimental">a mano, sin confirmar</div>
        )}
      </TableCell>
      <TableCell className={cn("num text-right", evTone(bet.profit))}>
        {money(bet.profit, currency)}
      </TableCell>
      <TableCell className={cn("num text-right", evTone(bet.clv))}>
        {pct(bet.clv, 2, true)}
      </TableCell>
      <TableCell>
        {bet.status === "pendiente" && started && (
          <form
            className="flex items-center gap-1"
            onSubmit={(event) => {
              event.preventDefault();
              if (choice) onSettle(choice);
            }}
          >
            <label className="sr-only" htmlFor={`settle-${bet.id}`}>
              Resultado de la apuesta {bet.id}
            </label>
            <select
              id={`settle-${bet.id}`}
              className="field h-10 w-28 px-2 text-xs md:h-8"
              value={choice}
              onChange={(event) => setChoice(event.target.value as typeof choice)}
            >
              <option value="">Liquidar…</option>
              <option value="ganada">Ganada</option>
              <option value="perdida">Perdida</option>
              <option value="nula">Nula</option>
            </select>
            <Button type="submit" variant="outline" size="sm" disabled={!choice || busy}>
              Guardar
            </Button>
          </form>
        )}
        {bet.status === "pendiente" && !started && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-negative hover:bg-negative-soft hover:text-negative"
            disabled={busy}
            onClick={onDelete}
            aria-label={`Borrar apuesta ${bet.id}`}
          >
            <Trash2 aria-hidden />
            Borrar
          </Button>
        )}
      </TableCell>
    </TableRow>
  );
}
