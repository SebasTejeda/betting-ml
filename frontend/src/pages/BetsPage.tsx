import {
  Ban,
  ChartColumn,
  CircleCheck,
  CircleMinus,
  CircleX,
  Coins,
  FlaskConical,
  Gauge,
  Hash,
  Hourglass,
  Info,
  type LucideIcon,
  Percent,
  RefreshCw,
  Trash2,
  TrendingUp,
  Wallet,
} from "lucide-react";
import { useId, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
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
import { OUTCOME_LABEL, type Bet, type Summary } from "../api/types";
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
        icon={Wallet}
        aside={
          <div className="flex flex-col items-start gap-1 text-sm sm:items-end">
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
              <span role="status" className="text-xs text-positive">
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
      <div
        role="group"
        aria-label="Tipo de apuestas"
        className="mb-4 inline-flex rounded-lg border bg-card p-1 shadow-sm"
      >
        {(["real", "paper", "all"] as const).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={kind === value}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm transition-colors duration-150",
              kind === value
                ? "bg-secondary font-medium text-foreground shadow-xs"
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
      <p className="mb-4 flex items-start gap-2 rounded-lg border border-info/30 bg-info-soft/60 p-3 text-sm">
        <Info aria-hidden className="mt-0.5 size-4 shrink-0 text-info" />
        <span>
          Con menos de 300 apuestas el ROI es mayormente ruido: mira el CLV (si le ganas a la cuota
          de cierre de la referencia).
        </span>
      </p>
      {summary.isPending ? (
        <Loading what="el resumen" variant="cards" />
      ) : summary.isError ? (
        <ErrorBox error={summary.error} />
      ) : (
        <SummaryPanel summary={summary.data} currency={currency} />
      )}
      <Panel
        title="Apuestas"
        icon={Hash}
        className="mt-4"
        action={
          <label className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
            Estado
            <select
              className="field h-8 w-36"
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
        <p className="mt-4 text-xs text-muted-foreground">
          Liquidar a mano solo es posible después del inicio del partido, y borrar solo antes. Una
          apuesta marcada a mano como ganada o nula cuenta como perdida para el límite mensual hasta
          que se confirme con el resultado oficial, y una apuesta real sin liquidar de un partido ya
          terminado (más de 3 h) también cuenta como perdida hasta liquidarla. Si un partido se
          aplaza, márcala como nula.
        </p>
      </Panel>
    </>
  );
}

function Kpi({
  label,
  value,
  icon: Icon,
  tone,
  hint,
}: {
  label: string;
  value: string;
  icon: LucideIcon;
  tone?: string;
  hint?: string;
}) {
  return (
    <Card className="gap-1 px-4 shadow-sm">
      <dt className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Icon aria-hidden className="size-3.5" />
        {label}
      </dt>
      <dd className={cn("text-2xl font-semibold tracking-tight tabular-nums", tone)}>{value}</dd>
      {hint && <dd className="text-xs text-muted-foreground">{hint}</dd>}
    </Card>
  );
}

function SummaryPanel({ summary, currency }: { summary: Summary; currency: string }) {
  const month = summary.month;
  const used = month.loss_limit > 0 ? Math.min(1, month.current_loss / month.loss_limit) : 1;
  const signal = summary.experimental_signal;
  return (
    <div className="flex flex-col gap-4">
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6" aria-label="Indicadores">
        <Kpi
          label="Apuestas (liquidadas)"
          icon={Hash}
          value={`${summary.bets} (${summary.settled})`}
        />
        <Kpi
          label="CLV medio"
          icon={TrendingUp}
          value={pct(summary.clv_mean, 2, true)}
          tone={evTone(summary.clv_mean)}
        />
        <Kpi label="% CLV positivo" icon={Percent} value={pct(summary.clv_positive_rate, 0)} />
        <Kpi
          label="Beneficio"
          icon={Coins}
          value={money(summary.profit, currency)}
          tone={evTone(summary.profit)}
        />
        <Kpi
          label="ROI"
          icon={ChartColumn}
          value={pct(summary.roi, 1, true)}
          tone={evTone(summary.roi)}
          hint="ruido con pocas apuestas"
        />
        <Kpi
          label="Mejor cuota vs promedio"
          icon={Gauge}
          value={pct(summary.best_odds_uplift_mean, 1, true)}
        />
      </dl>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Límite mensual" icon={Ban}>
          <p className="mb-3 text-sm">
            Pérdida del mes: <strong>{money(month.current_loss, currency)}</strong> de{" "}
            {money(month.loss_limit, currency)}
          </p>
          <Meter
            label="Uso del límite mensual"
            value={Math.round(used * 100)}
            tone={used >= 1 ? "negative" : used >= 0.8 ? "experimental" : "positive"}
          />
          <p className="mt-2 text-xs text-muted-foreground">
            Disponible: {money(month.remaining, currency)}
            {month.remaining <= 0 && " · apuestas reales bloqueadas hasta el mes siguiente"}
          </p>
        </Panel>
        <Panel
          title="Progreso de la señal"
          icon={FlaskConical}
          action={<ExperimentalBadge />}
          className="border border-experimental-border"
        >
          <p className="mb-3 text-sm">
            <strong className="text-2xl font-semibold tabular-nums">
              {signal.paper_bets}/{signal.target}
            </strong>{" "}
            apuestas en papel liquidadas · CLV acumulado{" "}
            <strong className={evTone(signal.clv_mean)}>{pct(signal.clv_mean, 2, true)}</strong>
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
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Bankroll" icon={Wallet} className="lg:col-span-2">
          {summary.bankroll.series.length < 2 ? (
            <Empty icon={ChartColumn}>Aún no hay apuestas liquidadas.</Empty>
          ) : (
            <BankrollChart series={summary.bankroll.series} currency={currency} />
          )}
        </Panel>
        <Panel title="Por liga y casa (CLV medio)" icon={ChartColumn}>
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
    </div>
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
              <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.45} />
              <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" vertical={false} />
          <XAxis dataKey="date" fontSize={11} stroke="var(--chart-text)" tickLine={false} />
          <YAxis
            domain={["auto", "auto"]}
            fontSize={11}
            stroke="var(--chart-text)"
            tickLine={false}
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
      <p className="mb-1 text-xs font-medium text-muted-foreground">{label}</p>
      <div className="h-28" role="img" aria-label={label}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ left: -20, right: 4 }}>
            <XAxis dataKey="name" fontSize={11} stroke="var(--chart-text)" tickLine={false} />
            <YAxis fontSize={11} unit="%" stroke="var(--chart-text)" tickLine={false} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              cursor={{ fill: "var(--muted)" }}
              formatter={(v) => `${Number(v).toFixed(2)} %`}
            />
            <Bar dataKey="clv" name="CLV medio" fill="var(--chart-2)" radius={[4, 4, 0, 0]} />
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
              onSettle={(status) => update.mutate({ id: bet.id, patch: { status } })}
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
        <div className="text-xs text-muted-foreground">
          {bet.league} · {kickoff(bet.kickoff)}
        </div>
      </TableCell>
      <TableCell className="min-w-40 whitespace-normal">
        {OUTCOME_LABEL[bet.outcome]} <span className="tabular-nums">{odds(bet.odds)}</span> ·{" "}
        {bet.bookmaker}
        <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
          <Badge variant="outline" className="font-normal">
            {bet.kind === "paper" ? "Papel" : "Real"}
          </Badge>
          {bet.from_experimental_signal && <ExperimentalBadge />}
          {bet.sin_referencia && <span className="text-experimental">sin cuota de referencia</span>}
        </div>
      </TableCell>
      <TableCell className="text-right tabular-nums">{money(bet.stake, currency)}</TableCell>
      <TableCell className="whitespace-normal">
        <StatusBadge status={bet.status} />
        {bet.result_source === "manual" && (
          <div className="mt-1 text-xs text-experimental">a mano, sin confirmar</div>
        )}
      </TableCell>
      <TableCell className={cn("text-right tabular-nums", evTone(bet.profit))}>
        {money(bet.profit, currency)}
      </TableCell>
      <TableCell className={cn("text-right tabular-nums", evTone(bet.clv))}>
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
              className="field h-7 w-28 px-2 text-xs"
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
            variant="destructive"
            size="sm"
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
