import { zodResolver } from "@hookform/resolvers/zod";
import { Ban, CircleCheck, NotebookPen, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";

import { ApiError } from "../api/client";
import { useCreateBet } from "../api/hooks";
import { OUTCOME_LABEL, type Bet, type BetIn, type BetMarket, type Outcome } from "../api/types";
import { odds as fmtOdds } from "../lib/format";
import { ErrorBox, ExperimentalBadge } from "./common";
import { Button } from "./ui/button";

const schema = z.object({
  kind: z.enum(["paper", "real"]),
  stake: z
    .string()
    .trim()
    .regex(/^\d+([.,]\d{1,2})?$/, "Monto inválido (máximo 2 decimales)")
    .transform((v) => Number(v.replace(",", ".")))
    .refine((v) => v > 0, "El stake debe ser mayor que 0"),
  note: z.string().max(500).optional(),
  // Only when the selection has no price yet (analysis without odds): typed by the user.
  manualOdds: z.string().optional(),
  manualBookmaker: z.string().max(40).optional(),
});
type FormValues = z.infer<typeof schema>;

type Props = {
  matchId: string;
  /** 1X2 bets (spec 002). For the other markets use `market` + `selection` (+ `line`). */
  outcome?: Outcome;
  market?: BetMarket;
  selection?: string | null;
  line?: number | null;
  /** What is shown to the user ("Real Madrid más de 1.5 goles"); 1X2 uses the outcome name. */
  label?: string;
  /** Without a price the user types the odds and the bookmaker. */
  bookmaker?: string | null;
  odds?: number | null;
  fromSignal?: boolean;
  /** Initial "Tipo" (paper by default from the analysis; the signal is always paper). */
  defaultKind?: "paper" | "real";
  suggestedStake?: number;
  /** The match has no reference price (no API odds): shown before registering. */
  noReference?: boolean;
};

/** Registers a bet in the journal. Limits (US6) are enforced by the API:
 *  409 → the user must explicitly confirm; 403 → real bets are blocked (paper still allowed). */
export function RegisterBetForm({
  matchId,
  outcome,
  market = "h2h",
  selection = null,
  line = null,
  label,
  bookmaker,
  odds,
  fromSignal = false,
  defaultKind,
  suggestedStake,
  noReference = false,
}: Props) {
  const create = useCreateBet();
  const [pending, setPending] = useState<{ body: BetIn; error: ApiError } | null>(null);
  const [saved, setSaved] = useState<Bet | null>(null);
  const {
    register,
    handleSubmit,
    control,
    setValue,
    setError,
    formState: { errors },
  } = useForm<z.input<typeof schema>, unknown, FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      kind: fromSignal ? "paper" : (defaultKind ?? "real"),
      stake: suggestedStake && suggestedStake > 0 ? suggestedStake.toFixed(2) : "",
      note: "",
      manualOdds: "",
      manualBookmaker: "",
    },
  });
  const needsPrice = !odds || !bookmaker;
  const kind = useWatch({ control, name: "kind" });

  function send(body: BetIn) {
    setPending(null);
    create.mutate(body, {
      onSuccess: (bet) => setSaved(bet),
      onError: (error) => {
        if (error instanceof ApiError && error.status === 409) setPending({ body, error });
      },
    });
  }

  const submit = handleSubmit((values) => {
    let price = odds ?? 0;
    let book = bookmaker ?? "";
    if (needsPrice) {
      price = Number((values.manualOdds ?? "").replace(",", "."));
      book = (values.manualBookmaker ?? "").trim();
      if (!Number.isFinite(price) || price <= 1) {
        setError("manualOdds", { message: "Cuota inválida (mayor que 1)" });
        return;
      }
      if (!book) {
        setError("manualBookmaker", { message: "Indica la casa" });
        return;
      }
    }
    send({
      match_id: matchId,
      ...(market === "h2h"
        ? { outcome: outcome ?? null, market: "h2h" }
        : { outcome: null, market, selection, line }),
      bookmaker: book,
      odds: price,
      stake: values.stake,
      kind: values.kind,
      note: values.note || null,
      from_experimental_signal: fromSignal,
      confirm: false,
    });
  });
  const shown = label ?? (outcome ? OUTCOME_LABEL[outcome] : (selection ?? market));

  if (saved) {
    return (
      <div
        role="status"
        className="flex flex-col gap-2 rounded-xl border border-positive/40 bg-positive-soft/60 p-4 text-sm"
      >
        <p className="flex items-center gap-2 font-medium">
          <CircleCheck aria-hidden className="size-5 text-positive" />
          Apuesta {saved.kind === "paper" ? "en papel" : "real"} registrada (#{saved.id}).
        </p>
        {saved.warnings.length > 0 && (
          <ul className="flex flex-col gap-1 pl-7 text-experimental">
            {saved.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}
        <Link to="/bets" className="pl-7 text-primary underline-offset-2 hover:underline">
          Ver mis apuestas
        </Link>
      </div>
    );
  }

  const blocked =
    create.error instanceof ApiError && create.error.status === 403 ? create.error : null;
  const radio =
    "flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors duration-150 has-checked:border-ring has-checked:bg-accent has-checked:text-accent-foreground";

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={submit}
      noValidate
      aria-label="Registrar apuesta"
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span>
          {shown}
          {!needsPrice && (
            <>
              {" "}
              a <strong className="tabular-nums">{fmtOdds(odds)}</strong> en {bookmaker}
            </>
          )}
        </span>
        {fromSignal && <ExperimentalBadge />}
      </div>
      {noReference && <NoReferenceNotice />}
      {needsPrice && (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Cuota que te ofrecen
            <input inputMode="decimal" className="field tabular-nums" {...register("manualOdds")} />
            {errors.manualOdds && (
              <span className="text-xs font-normal text-negative">{errors.manualOdds.message}</span>
            )}
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Casa
            <input className="field" {...register("manualBookmaker")} />
            {errors.manualBookmaker && (
              <span className="text-xs font-normal text-negative">
                {errors.manualBookmaker.message}
              </span>
            )}
          </label>
        </div>
      )}
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-xs font-medium text-muted-foreground">Tipo</legend>
        <div className="grid grid-cols-2 gap-2">
          <label className={radio}>
            <input
              type="radio"
              value="paper"
              className="accent-(--primary)"
              {...register("kind")}
            />{" "}
            En papel
          </label>
          <label className={radio}>
            <input type="radio" value="real" className="accent-(--primary)" {...register("kind")} />{" "}
            Real (dinero)
          </label>
        </div>
      </fieldset>
      <div className="grid gap-3 sm:grid-cols-[8rem_1fr_auto] sm:items-end">
        <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Stake
          <input inputMode="decimal" className="field tabular-nums" {...register("stake")} />
          {errors.stake && (
            <span className="text-xs font-normal text-negative">{errors.stake.message}</span>
          )}
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Nota
          <input className="field" {...register("note")} />
        </label>
        <Button
          type="submit"
          size="lg"
          variant="secondary"
          disabled={create.isPending || pending !== null}
        >
          <NotebookPen aria-hidden />
          Registrar apuesta
        </Button>
      </div>
      {suggestedStake !== undefined && suggestedStake > 0 && (
        <p className="text-xs text-muted-foreground">
          Stake sugerido (Kelly fraccional, con tope): {suggestedStake.toFixed(2)}. Es orientativo.
        </p>
      )}
      {pending && (
        <div
          role="alertdialog"
          aria-label="Confirmación"
          className="flex flex-col gap-3 rounded-xl border border-experimental-border bg-experimental-soft/70 p-4 text-sm"
        >
          <p className="flex items-center gap-2 font-medium text-experimental">
            <TriangleAlert aria-hidden className="size-4" />
            Antes de registrar
          </p>
          <ul className="flex list-disc flex-col gap-1 pl-5">
            {messages(pending.error).map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="secondary" onClick={() => setPending(null)}>
              Cancelar
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => send({ ...pending.body, confirm: true })}
            >
              Confirmar y registrar
            </Button>
          </div>
        </div>
      )}
      {blocked && (
        <div
          role="alert"
          className="flex flex-col gap-2 rounded-xl border border-negative/40 bg-negative-soft/70 p-4 text-sm"
        >
          <p className="flex items-center gap-2 font-medium text-negative">
            <Ban aria-hidden className="size-4" />
            Apuestas reales bloqueadas este mes.
          </p>
          <p>{blocked.message}</p>
          {kind === "real" && (
            <Button
              type="button"
              variant="outline"
              className="w-fit"
              onClick={() => {
                create.reset();
                setValue("kind", "paper");
              }}
            >
              Cambiar a papel
            </Button>
          )}
        </div>
      )}
      {create.isError &&
        !blocked &&
        !pending &&
        !(create.error instanceof ApiError && create.error.status === 409) && (
          <ErrorBox error={create.error} />
        )}
    </form>
  );
}

export function NoReferenceNotice() {
  return (
    <p
      role="note"
      className="flex items-start gap-2 rounded-lg border border-experimental-border bg-experimental-soft/70 p-3 text-sm"
    >
      <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-experimental" />
      <span>
        <strong className="text-experimental">Sin cuota de referencia.</strong> Este partido no
        tiene cuotas de la API: la apuesta cuenta para todos los límites, queda fuera de la señal de
        valor y su CLV se calculará después con el cierre de Pinnacle de football-data si está
        disponible.
      </span>
    </p>
  );
}

function messages(error: ApiError): string[] {
  const list = error.details["messages"];
  return Array.isArray(list) && list.length > 0 ? list.map(String) : [error.message];
}
