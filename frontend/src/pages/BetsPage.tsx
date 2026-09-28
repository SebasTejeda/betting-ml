import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
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
import { Card, Empty, ErrorBox, ExperimentalBadge, Loading, PageTitle } from "../components/ui";
import { kickoff, money, odds, pct } from "../lib/format";

const STATUS_LABEL: Record<string, string> = {
  pendiente: "Pendiente",
  ganada: "Ganada",
  perdida: "Perdida",
  nula: "Nula",
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
        aside={
          <div className="flex flex-col items-end gap-1 text-sm">
            <button
              type="button"
              className="rounded bg-slate-900 px-3 py-1.5 font-medium text-white disabled:opacity-50"
              disabled={settle.isPending}
              onClick={() => settle.mutate()}
            >
              Liquidar con resultados oficiales
            </button>
            {settle.isSuccess && (
              <span role="status" className="text-xs text-emerald-800">
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
      <div role="group" aria-label="Tipo de apuestas" className="mb-4 flex gap-1">
        {(["real", "paper", "all"] as const).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={kind === value}
            className={`rounded px-3 py-1 text-sm ${
              kind === value ? "bg-slate-900 text-white" : "border border-slate-300 bg-white"
            }`}
            onClick={() => {
              setKind(value);
              setPage(1);
            }}
          >
            {value === "real" ? "Reales" : value === "paper" ? "En papel" : "Todas"}
          </button>
        ))}
      </div>
      <p className="mb-4 rounded border border-sky-200 bg-sky-50 p-2 text-sm text-sky-900">
        Con menos de 300 apuestas el ROI es mayormente ruido: mira el CLV (si le ganas a la cuota de
        cierre de la referencia).
      </p>
      {summary.isPending ? (
        <Loading what="el resumen" />
      ) : summary.isError ? (
        <ErrorBox error={summary.error} />
      ) : (
        <SummaryPanel summary={summary.data} currency={currency} />
      )}
      <Card className="mt-4">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <h2 className="font-semibold">Apuestas</h2>
          <label className="flex flex-col text-sm">
            Estado
            <select
              className="rounded border border-slate-300 px-2 py-1"
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
        </div>
        <BetsTable
          params={{ kind: kind === "all" ? undefined : kind, status, page }}
          currency={currency}
          onPage={setPage}
        />
        <p className="mt-3 text-xs text-slate-600">
          Liquidar a mano solo es posible después del inicio del partido, y borrar solo antes. Una
          apuesta marcada a mano como ganada o nula cuenta como perdida para el límite mensual hasta
          que se confirme con el resultado oficial, y una apuesta real sin liquidar de un partido ya
          terminado (más de 3 h) también cuenta como perdida hasta liquidarla. Si un partido se
          aplaza, márcala como nula.
        </p>
      </Card>
    </>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-200 bg-white p-3">
      <dt className="text-xs text-slate-600">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

function SummaryPanel({ summary, currency }: { summary: Summary; currency: string }) {
  const month = summary.month;
  const used = month.loss_limit > 0 ? Math.min(1, month.current_loss / month.loss_limit) : 1;
  const signal = summary.experimental_signal;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:col-span-2" aria-label="Indicadores">
        <Kpi label="Apuestas (liquidadas)" value={`${summary.bets} (${summary.settled})`} />
        <Kpi label="CLV medio" value={pct(summary.clv_mean, 2, true)} />
        <Kpi label="% CLV positivo" value={pct(summary.clv_positive_rate, 0)} />
        <Kpi label="Beneficio" value={money(summary.profit, currency)} />
        <Kpi label="ROI" value={pct(summary.roi, 1, true)} />
        <Kpi label="Mejor cuota vs promedio" value={pct(summary.best_odds_uplift_mean, 1, true)} />
      </dl>
      <Card>
        <h2 className="mb-2 font-semibold">Límite mensual</h2>
        <p className="text-sm">
          Pérdida del mes: <strong>{money(month.current_loss, currency)}</strong> de{" "}
          {money(month.loss_limit, currency)}
        </p>
        <div
          role="progressbar"
          aria-label="Uso del límite mensual"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(used * 100)}
          className="mt-2 h-2 w-full rounded bg-slate-200"
        >
          <div
            className={`h-2 rounded ${used >= 1 ? "bg-red-600" : used >= 0.8 ? "bg-amber-500" : "bg-emerald-600"}`}
            style={{ width: `${used * 100}%` }}
          />
        </div>
        <p className="mt-1 text-xs text-slate-600">
          Disponible: {money(month.remaining, currency)}
          {month.remaining <= 0 && " · apuestas reales bloqueadas hasta el mes siguiente"}
        </p>
      </Card>
      <Card className="lg:col-span-3">
        <h2 className="mb-1 flex flex-wrap items-center gap-2 font-semibold">
          Progreso de la señal <ExperimentalBadge />
        </h2>
        <p className="text-sm">
          <strong>
            {signal.paper_bets}/{signal.target}
          </strong>{" "}
          apuestas en papel liquidadas · CLV acumulado{" "}
          <strong>{pct(signal.clv_mean, 2, true)}</strong>
        </p>
        <div
          role="progressbar"
          aria-label="Apuestas en papel de la señal"
          aria-valuemin={0}
          aria-valuemax={signal.target}
          aria-valuenow={signal.paper_bets}
          className="mt-2 h-2 w-full rounded bg-slate-200"
        >
          <div
            className="h-2 rounded bg-sky-700"
            style={{ width: `${Math.min(100, (100 * signal.paper_bets) / signal.target)}%` }}
          />
        </div>
        <p className="mt-1 text-xs text-slate-600">
          {signal.evidence_met
            ? "Condición cumplida: 100 apuestas en papel con CLV medio positivo."
            : "Sin evidencia todavía. Al llegar a 100 apuestas en papel con CLV positivo habrá evidencia real."}
        </p>
      </Card>
      <Card className="lg:col-span-2">
        <h2 className="mb-2 font-semibold">Bankroll</h2>
        {summary.bankroll.series.length < 2 ? (
          <Empty>Aún no hay apuestas liquidadas.</Empty>
        ) : (
          <div className="h-56" role="img" aria-label="Curva de bankroll">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={summary.bankroll.series}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" fontSize={11} />
                <YAxis domain={["auto", "auto"]} fontSize={11} />
                <Tooltip formatter={(v) => money(Number(v), currency)} />
                <Line type="monotone" dataKey="value" name="Bankroll" stroke="#0369a1" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>
      <Card>
        <h2 className="mb-2 font-semibold">Por liga y casa (CLV medio)</h2>
        <GroupBars groups={summary.by_league} name="league" label="Por liga" />
        <GroupBars groups={summary.by_bookmaker} name="bookmaker" label="Por casa" />
      </Card>
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
    <div className="mb-2 h-32" role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <XAxis dataKey="name" fontSize={11} />
          <YAxis fontSize={11} unit="%" />
          <Tooltip formatter={(v) => `${Number(v).toFixed(2)} %`} />
          <Bar dataKey="clv" name="CLV medio" fill="#0369a1" />
        </BarChart>
      </ResponsiveContainer>
    </div>
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

  if (bets.isPending) return <Loading what="apuestas" />;
  if (bets.isError) return <ErrorBox error={bets.error} />;
  if (bets.data.items.length === 0) return <Empty>No hay apuestas con estos filtros.</Empty>;
  const pages = Math.max(1, Math.ceil(bets.data.total / bets.data.size));
  return (
    <>
      {update.isError && <ErrorBox error={update.error} />}
      {remove.isError && <ErrorBox error={remove.error} />}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">Apuestas registradas</caption>
          <thead>
            <tr className="border-b border-slate-200 text-left text-slate-700">
              <th scope="col" className="p-2">
                Partido
              </th>
              <th scope="col" className="p-2">
                Apuesta
              </th>
              <th scope="col" className="p-2">
                Stake
              </th>
              <th scope="col" className="p-2">
                Estado
              </th>
              <th scope="col" className="p-2">
                Beneficio
              </th>
              <th scope="col" className="p-2">
                CLV
              </th>
              <th scope="col" className="p-2">
                Acciones
              </th>
            </tr>
          </thead>
          <tbody>
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
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <nav aria-label="Páginas" className="mt-3 flex items-center gap-2 text-sm">
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-1 disabled:opacity-50"
            disabled={params.page <= 1}
            onClick={() => onPage(params.page - 1)}
          >
            Anterior
          </button>
          <span>
            Página {params.page} de {pages}
          </span>
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-1 disabled:opacity-50"
            disabled={params.page >= pages}
            onClick={() => onPage(params.page + 1)}
          >
            Siguiente
          </button>
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
    <tr className="border-b border-slate-100 align-top">
      <td className="p-2">
        {bet.home_team && bet.away_team ? `${bet.home_team} – ${bet.away_team}` : bet.match_id}
        <div className="text-xs text-slate-600">
          {bet.league} · {kickoff(bet.kickoff)}
        </div>
      </td>
      <td className="p-2">
        {OUTCOME_LABEL[bet.outcome]} {odds(bet.odds)} · {bet.bookmaker}
        <div className="flex flex-wrap gap-1 text-xs text-slate-600">
          {bet.kind === "paper" ? "Papel" : "Real"}
          {bet.from_experimental_signal && <ExperimentalBadge />}
        </div>
      </td>
      <td className="p-2 tabular-nums">{money(bet.stake, currency)}</td>
      <td className="p-2">
        {STATUS_LABEL[bet.status] ?? bet.status}
        {bet.result_source === "manual" && (
          <div className="text-xs text-amber-800">a mano, sin confirmar</div>
        )}
      </td>
      <td className="p-2 tabular-nums">{money(bet.profit, currency)}</td>
      <td className="p-2 tabular-nums">{pct(bet.clv, 2, true)}</td>
      <td className="p-2">
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
              className="rounded border border-slate-300 px-1 py-0.5 text-xs"
              value={choice}
              onChange={(event) => setChoice(event.target.value as typeof choice)}
            >
              <option value="">Liquidar…</option>
              <option value="ganada">Ganada</option>
              <option value="perdida">Perdida</option>
              <option value="nula">Nula</option>
            </select>
            <button
              type="submit"
              className="rounded border border-slate-300 px-2 py-0.5 text-xs disabled:opacity-50"
              disabled={!choice || busy}
            >
              Guardar
            </button>
          </form>
        )}
        {bet.status === "pendiente" && !started && (
          <button
            type="button"
            className="rounded border border-red-300 px-2 py-0.5 text-xs text-red-800 disabled:opacity-50"
            disabled={busy}
            onClick={onDelete}
            aria-label={`Borrar apuesta ${bet.id}`}
          >
            Borrar
          </button>
        )}
      </td>
    </tr>
  );
}
