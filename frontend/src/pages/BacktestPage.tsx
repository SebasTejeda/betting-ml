import { ApiError } from "../api/client";
import { useBacktest } from "../api/hooks";
import { Card, Empty, ErrorBox, Loading, PageTitle } from "../components/ui";
import { pct } from "../lib/format";

type Result = {
  scenario: string;
  variant: string;
  threshold: number;
  n_bets: number;
  roi_flat: number | null;
  roi_ci_low: number | null;
  roi_ci_high: number | null;
  clv_mean: number | null;
  clv_ci_low: number | null;
  clv_ci_high: number | null;
  clv_positive_rate: number | null;
};
type MarginBlock = {
  margins?: Record<string, { n_matches: number; margin_mean: number | null }>;
  best_vs_avg?: { uplift_mean: number; uplift_median: number };
};
type Report = {
  level?: string;
  conclusion?: string;
  primary_strategy?: string;
  test?: { season?: string; n_matches?: number; results?: Record<string, Result> };
  margins?: {
    validation?: MarginBlock;
    current?: MarginBlock;
    current_season?: string;
    validation_seasons?: string[];
  };
};

const SCENARIO: Record<string, string> = {
  max: "Mejor cuota del mercado",
  b365: "Bet365",
  avg: "Cuota promedio",
};
const VARIANT: Record<string, string> = {
  none: "sin filtro",
  champion: "filtro del modelo E12 (no validado)",
  champion_no_odds: "filtro del modelo sin cuotas (no validado)",
};

function ci(low: number | null, high: number | null): string {
  return low === null || high === null ? "" : ` [${pct(low, 1)}, ${pct(high, 1)}]`;
}

export function BacktestPage() {
  const backtest = useBacktest();
  if (backtest.isPending) return <Loading what="el backtest" />;
  if (backtest.isError) {
    if (backtest.error instanceof ApiError && backtest.error.status === 404) {
      return <Empty>Aún no se ha ejecutado el backtest final.</Empty>;
    }
    return <ErrorBox error={backtest.error} />;
  }
  const report = backtest.data as Report;
  const results = Object.values(report.test?.results ?? {});
  const margins = report.margins;
  return (
    <>
      <PageTitle>Backtest contra Pinnacle</PageTitle>
      <Card className="mb-4">
        <p>
          Conclusión: <strong>{report.conclusion ?? "—"}</strong> · nivel{" "}
          <strong>{report.level ?? "—"}</strong>
        </p>
        <p className="mt-1 text-sm text-slate-600">
          La estrategia principal ({report.primary_strategy ?? "—"}) no le ganó a la cuota de cierre
          en la temporada de prueba {report.test?.season ?? ""}. Por eso la señal de valor se
          muestra solo como EXPERIMENTAL y en papel. La variante con el filtro del modelo E12 tiene
          muy pocas apuestas y se eligió después de ver el resultado: no está validada.
        </p>
      </Card>
      {margins && (
        <Card className="mb-4">
          <h2 className="mb-2 font-semibold">Por qué el comparador: margen pagado</h2>
          <MarginTable margins={margins} />
        </Card>
      )}
      <Card>
        <h2 className="mb-2 font-semibold">
          Resultados en prueba ({report.test?.season ?? "—"}, una sola evaluación)
        </h2>
        {results.length === 0 ? (
          <Empty>Sin resultados.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <caption className="sr-only">
                Resultados por escenario con intervalos de confianza
              </caption>
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-700">
                  <th scope="col" className="p-2">
                    Escenario
                  </th>
                  <th scope="col" className="p-2">
                    Apuestas
                  </th>
                  <th scope="col" className="p-2">
                    CLV medio [IC 95 %]
                  </th>
                  <th scope="col" className="p-2">
                    % CLV positivo
                  </th>
                  <th scope="col" className="p-2">
                    ROI plano [IC 95 %]
                  </th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr key={`${r.scenario}|${r.variant}`} className="border-b border-slate-100">
                    <th scope="row" className="p-2 text-left font-normal">
                      {SCENARIO[r.scenario] ?? r.scenario} · {VARIANT[r.variant] ?? r.variant}
                    </th>
                    <td className="p-2 tabular-nums">{r.n_bets}</td>
                    <td className="p-2 tabular-nums">
                      {pct(r.clv_mean, 2, true)}
                      <span className="text-xs text-slate-600">
                        {ci(r.clv_ci_low, r.clv_ci_high)}
                      </span>
                    </td>
                    <td className="p-2 tabular-nums">{pct(r.clv_positive_rate, 0)}</td>
                    <td className="p-2 tabular-nums">
                      {pct(r.roi_flat, 1, true)}
                      <span className="text-xs text-slate-600">
                        {ci(r.roi_ci_low, r.roi_ci_high)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-xs text-slate-600">
          Con pocas decenas de apuestas los intervalos son muy anchos: ningún resultado de esta
          tabla es evidencia de una ventaja.
        </p>
      </Card>
    </>
  );
}

function MarginTable({ margins }: { margins: NonNullable<Report["margins"]> }) {
  const rows: [string, MarginBlock | undefined][] = [
    [`Validación (${margins.validation_seasons?.join(", ") ?? "—"})`, margins.validation],
    [`Temporada actual (${margins.current_season ?? "—"})`, margins.current],
  ];
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">Margen medio por tipo de cuota</caption>
        <thead>
          <tr className="border-b border-slate-200 text-left text-slate-700">
            <th scope="col" className="p-2">
              Periodo
            </th>
            <th scope="col" className="p-2">
              Margen cuota promedio
            </th>
            <th scope="col" className="p-2">
              Margen mejor cuota
            </th>
            <th scope="col" className="p-2">
              La mejor paga vs promedio
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, block]) => (
            <tr key={label} className="border-b border-slate-100">
              <th scope="row" className="p-2 text-left font-normal">
                {label}
              </th>
              <td className="p-2 tabular-nums">{pct(block?.margins?.avg?.margin_mean)}</td>
              <td className="p-2 tabular-nums">{pct(block?.margins?.max?.margin_mean)}</td>
              <td className="p-2 tabular-nums">{pct(block?.best_vs_avg?.uplift_mean, 1, true)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
