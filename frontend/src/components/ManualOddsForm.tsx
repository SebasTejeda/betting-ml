import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { useBookmakers, useCalculator } from "../api/hooks";
import { OUTCOME_LABEL, OUTCOMES, type CalculatorResult, type Outcome } from "../api/types";
import { odds as fmtOdds, pct } from "../lib/format";
import { ErrorBox, ExperimentalBadge } from "./ui";

const schema = z.object({
  outcome: z.enum(["home", "draw", "away"]),
  bookmaker: z.string().min(1, "Elige una casa"),
  odds: z.coerce.number<string>().gt(1, "La cuota debe ser mayor que 1").lt(1000, "Cuota inválida"),
});
type FormValues = z.infer<typeof schema>;

const VERDICT_TEXT: Record<CalculatorResult["verdict"], string> = {
  valor: "por encima de la cuota justa",
  justo: "cerca de la cuota justa",
  evitar: "por debajo de la cuota justa",
};

type Props = {
  matchId: string;
  defaultOutcome?: Outcome;
  defaultBookmaker?: string;
  defaultOdds?: number;
  onEvaluated?: (input: FormValues, result: CalculatorResult) => void;
};

/** Evaluates a price typed by hand (Peruvian bookmakers) against the reference (US4). */
export function ManualOddsForm({
  matchId,
  defaultOutcome,
  defaultBookmaker,
  defaultOdds,
  onEvaluated,
}: Props) {
  const bookmakers = useBookmakers();
  const calculator = useCalculator();
  const manual = (bookmakers.data ?? []).filter((b) => b.source === "manual");
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<z.input<typeof schema>, unknown, FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      outcome: defaultOutcome ?? "home",
      bookmaker: defaultBookmaker ?? "",
      odds: defaultOdds ? String(defaultOdds) : "",
    },
  });

  const submit = handleSubmit((values) =>
    calculator.mutate(
      { match_id: matchId, ...values },
      { onSuccess: (result) => onEvaluated?.(values, result) },
    ),
  );

  return (
    <div className="flex flex-col gap-3">
      <form className="flex flex-wrap items-end gap-3" onSubmit={submit} noValidate>
        <label className="flex flex-col text-sm">
          Resultado
          <select className="rounded border border-slate-300 px-2 py-1" {...register("outcome")}>
            {OUTCOMES.map((o) => (
              <option key={o} value={o}>
                {OUTCOME_LABEL[o]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-sm">
          Casa
          <select className="rounded border border-slate-300 px-2 py-1" {...register("bookmaker")}>
            <option value="">Elige…</option>
            {manual.map((b) => (
              <option key={b.key} value={b.key}>
                {b.name}
              </option>
            ))}
          </select>
          {errors.bookmaker && (
            <span className="text-xs text-red-700">{errors.bookmaker.message}</span>
          )}
        </label>
        <label className="flex flex-col text-sm">
          Cuota
          <input
            inputMode="decimal"
            className="w-24 rounded border border-slate-300 px-2 py-1"
            {...register("odds")}
          />
          {errors.odds && <span className="text-xs text-red-700">{errors.odds.message}</span>}
        </label>
        <button
          type="submit"
          className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          disabled={calculator.isPending}
        >
          Evaluar
        </button>
      </form>
      {calculator.isError && <ErrorBox error={calculator.error} />}
      {calculator.data && <CalculationResult result={calculator.data} />}
    </div>
  );
}

export function CalculationResult({ result }: { result: CalculatorResult }) {
  return (
    <div
      className="rounded border border-slate-200 bg-slate-50 p-3 text-sm"
      aria-label="Resultado"
      role="region"
    >
      <p>
        Cuota justa ({result.reference}): <strong>{fmtOdds(result.fair_odds)}</strong> ·
        probabilidad {pct(result.fair_probability)} · EV {pct(result.ev, 1, true)}
      </p>
      {result.best_available && (
        <p>
          Mejor cuota disponible: <strong>{fmtOdds(result.best_available.odds)}</strong> en{" "}
          {result.best_available.bookmaker}
        </p>
      )}
      <p className="mt-2 flex flex-wrap items-center gap-2">
        <ExperimentalBadge />
        <span>
          Tu cuota está {VERDICT_TEXT[result.verdict]}
          {result.model_agrees !== null &&
            ` · el modelo ${result.model_agrees ? "coincide" : "no coincide"}`}
        </span>
      </p>
    </div>
  );
}
