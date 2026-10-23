import { SearchX, TriangleAlert } from "lucide-react";

import { ApiError } from "../api/client";
import { useBacktest } from "../api/hooks";
import { Empty, ErrorBox, Loading, PageTitle, Panel } from "../components/common";
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
import { pct } from "../lib/format";
import { evTone } from "../lib/tone";

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
      return <Empty icon={SearchX}>Aún no se ha ejecutado el backtest final.</Empty>;
    }
    return <ErrorBox error={backtest.error} />;
  }
  const report = backtest.data as Report;
  const results = Object.values(report.test?.results ?? {});
  const margins = report.margins;
  return (
    <>
      <PageTitle description="Resultados medidos del comparador y de la señal frente a la cuota de cierre de Pinnacle.">
        Backtest contra Pinnacle
      </PageTitle>
      <Card className="mt-6 mb-5 gap-5 p-5 sm:p-6">
        <dl className="flex flex-wrap gap-x-12 gap-y-4">
          <div className="flex flex-col gap-1">
            <dt className="eyebrow">Conclusión</dt>
            <dd className="text-xl font-semibold tracking-tight">{report.conclusion ?? "—"}</dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="eyebrow">Nivel</dt>
            <dd className="text-xl font-semibold tracking-tight">{report.level ?? "—"}</dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="eyebrow">Temporada de prueba</dt>
            <dd className="num text-xl font-semibold tracking-tight">
              {report.test?.season ?? "—"}
            </dd>
          </div>
        </dl>
        <p className="flex items-start gap-2.5 rounded-lg bg-experimental-soft px-3 py-2.5 text-sm text-foreground">
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-experimental" />
          <span>
            La estrategia principal ({report.primary_strategy ?? "—"}) no le ganó a la cuota de
            cierre en la temporada de prueba {report.test?.season ?? ""}. Por eso la señal de valor
            se muestra solo como EXPERIMENTAL y en papel. La variante con el filtro del modelo E12
            tiene muy pocas apuestas y se eligió después de ver el resultado: no está validada.
          </span>
        </p>
      </Card>
      {margins && (
        <Panel title="Por qué el comparador: margen pagado" className="mb-5">
          <MarginTable margins={margins} />
        </Panel>
      )}
      <Panel title={`Resultados en prueba (${report.test?.season ?? "—"}, una sola evaluación)`}>
        {results.length === 0 ? (
          <Empty>Sin resultados.</Empty>
        ) : (
          <Table>
            <TableCaption className="sr-only">
              Resultados por escenario con intervalos de confianza
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>Escenario</TableHead>
                <TableHead className="text-right">Apuestas</TableHead>
                <TableHead className="text-right">CLV medio [IC 95 %]</TableHead>
                <TableHead className="text-right">% CLV positivo</TableHead>
                <TableHead className="text-right">ROI plano [IC 95 %]</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {results.map((r) => (
                <TableRow key={`${r.scenario}|${r.variant}`}>
                  <TableHead scope="row" className="font-normal whitespace-normal text-foreground">
                    {SCENARIO[r.scenario] ?? r.scenario} ·{" "}
                    <span className={r.variant === "none" ? undefined : "text-experimental"}>
                      {VARIANT[r.variant] ?? r.variant}
                    </span>
                  </TableHead>
                  <TableCell className="num text-right">{r.n_bets}</TableCell>
                  <TableCell className="num text-right">
                    <span className={evTone(r.clv_mean)}>{pct(r.clv_mean, 2, true)}</span>
                    <span className="block text-xs text-muted-foreground">
                      {ci(r.clv_ci_low, r.clv_ci_high)}
                    </span>
                  </TableCell>
                  <TableCell className="num text-right">{pct(r.clv_positive_rate, 0)}</TableCell>
                  <TableCell className="num text-right">
                    <span className={evTone(r.roi_flat)}>{pct(r.roi_flat, 1, true)}</span>
                    <span className="block text-xs text-muted-foreground">
                      {ci(r.roi_ci_low, r.roi_ci_high)}
                    </span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        <p className="mt-3 text-xs text-muted-foreground">
          Con pocas decenas de apuestas los intervalos son muy anchos: ningún resultado de esta
          tabla es evidencia de una ventaja.
        </p>
      </Panel>
    </>
  );
}

function MarginTable({ margins }: { margins: NonNullable<Report["margins"]> }) {
  const rows: [string, MarginBlock | undefined][] = [
    [`Validación (${margins.validation_seasons?.join(", ") ?? "—"})`, margins.validation],
    [`Temporada actual (${margins.current_season ?? "—"})`, margins.current],
  ];
  return (
    <Table>
      <TableCaption className="sr-only">Margen medio por tipo de cuota</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>Periodo</TableHead>
          <TableHead className="text-right">Margen cuota promedio</TableHead>
          <TableHead className="text-right">Margen mejor cuota</TableHead>
          <TableHead className="text-right">La mejor paga vs promedio</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map(([label, block]) => (
          <TableRow key={label}>
            <TableHead scope="row" className="font-normal text-foreground">
              {label}
            </TableHead>
            <TableCell className="num text-right">
              {pct(block?.margins?.avg?.margin_mean)}
            </TableCell>
            <TableCell className="num text-right font-semibold">
              {pct(block?.margins?.max?.margin_mean)}
            </TableCell>
            <TableCell
              className={`num text-right font-semibold ${evTone(block?.best_vs_avg?.uplift_mean)}`}
            >
              {pct(block?.best_vs_avg?.uplift_mean, 1, true)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
