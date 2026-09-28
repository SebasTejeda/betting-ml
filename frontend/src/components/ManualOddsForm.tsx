import { zodResolver } from "@hookform/resolvers/zod";
import { CircleCheck, CircleX, type LucideIcon, Scale } from "lucide-react";
import type { ReactNode } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { useBookmakers, useCalculator } from "../api/hooks";
import { OUTCOME_LABEL, OUTCOMES, type CalculatorResult, type Outcome } from "../api/types";
import { odds as fmtOdds, pct } from "../lib/format";
import { cn } from "../lib/utils";
import { ErrorBox, EvValue, ExperimentalBadge, ModelBadge } from "./common";
import { Button } from "./ui/button";

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
    <div className="flex flex-col gap-4">
      <form
        className="grid grid-cols-2 items-end gap-3 sm:grid-cols-[1fr_1.4fr_0.8fr_auto]"
        onSubmit={submit}
        noValidate
      >
        <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Resultado
          <select className="field" {...register("outcome")}>
            {OUTCOMES.map((o) => (
              <option key={o} value={o}>
                {OUTCOME_LABEL[o]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Casa
          <select className="field" {...register("bookmaker")}>
            <option value="">Elige…</option>
            {manual.map((b) => (
              <option key={b.key} value={b.key}>
                {b.name}
              </option>
            ))}
          </select>
          {errors.bookmaker && (
            <span className="text-xs font-normal text-negative">{errors.bookmaker.message}</span>
          )}
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Cuota
          <input inputMode="decimal" className="field tabular-nums" {...register("odds")} />
          {errors.odds && (
            <span className="text-xs font-normal text-negative">{errors.odds.message}</span>
          )}
        </label>
        <Button type="submit" size="lg" disabled={calculator.isPending}>
          <Scale aria-hidden />
          Evaluar
        </Button>
      </form>
      {calculator.isError && <ErrorBox error={calculator.error} />}
      {calculator.data && <CalculationResult result={calculator.data} />}
    </div>
  );
}

const VERDICT_STYLE: Record<
  CalculatorResult["verdict"],
  { icon: LucideIcon; tone: string; box: string }
> = {
  valor: {
    icon: CircleCheck,
    tone: "text-positive",
    box: "border-positive/40 bg-positive-soft/60",
  },
  justo: { icon: Scale, tone: "text-info", box: "border-info/40 bg-info-soft/60" },
  evitar: { icon: CircleX, tone: "text-negative", box: "border-negative/40 bg-negative-soft/60" },
};

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-xl font-semibold tabular-nums">{children}</dd>
    </div>
  );
}

export function CalculationResult({ result }: { result: CalculatorResult }) {
  const style = VERDICT_STYLE[result.verdict];
  const Icon = style.icon;
  return (
    <div
      className={cn("flex flex-col gap-4 rounded-xl border p-4", style.box)}
      aria-label="Resultado"
      role="region"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className={cn("flex items-center gap-2 text-lg font-semibold", style.tone)}>
          <Icon aria-hidden className="size-6" />
          Tu cuota está {VERDICT_TEXT[result.verdict]}
        </p>
        <ExperimentalBadge />
      </div>
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label={`Cuota justa (${result.reference})`}>{fmtOdds(result.fair_odds)}</Stat>
        <Stat label="Probabilidad justa">{pct(result.fair_probability)}</Stat>
        <Stat label="EV">
          <EvValue ev={result.ev} className="text-xl" />
        </Stat>
        <Stat label="Stake sugerido">
          {result.suggested_stake > 0 ? result.suggested_stake.toFixed(2) : "—"}
        </Stat>
      </dl>
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        {result.best_available && (
          <span>
            Mejor cuota disponible:{" "}
            <strong className="text-foreground">{fmtOdds(result.best_available.odds)}</strong> en{" "}
            {result.best_available.bookmaker}
          </span>
        )}
        <ModelBadge agrees={result.model_agrees} />
      </div>
    </div>
  );
}
