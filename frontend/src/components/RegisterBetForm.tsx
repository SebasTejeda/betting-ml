import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";

import { ApiError } from "../api/client";
import { useCreateBet } from "../api/hooks";
import { OUTCOME_LABEL, type Bet, type BetIn, type Outcome } from "../api/types";
import { odds as fmtOdds } from "../lib/format";
import { ErrorBox, ExperimentalBadge } from "./common";

const schema = z.object({
  kind: z.enum(["paper", "real"]),
  stake: z
    .string()
    .trim()
    .regex(/^\d+([.,]\d{1,2})?$/, "Monto inválido (máximo 2 decimales)")
    .transform((v) => Number(v.replace(",", ".")))
    .refine((v) => v > 0, "El stake debe ser mayor que 0"),
  note: z.string().max(500).optional(),
});
type FormValues = z.infer<typeof schema>;

type Props = {
  matchId: string;
  outcome: Outcome;
  bookmaker: string;
  odds: number;
  fromSignal?: boolean;
  suggestedStake?: number;
  /** The match has no reference price (no API odds): shown before registering. */
  noReference?: boolean;
};

/** Registers a bet in the journal. Limits (US6) are enforced by the API:
 *  409 → the user must explicitly confirm; 403 → real bets are blocked (paper still allowed). */
export function RegisterBetForm({
  matchId,
  outcome,
  bookmaker,
  odds,
  fromSignal = false,
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
    formState: { errors },
  } = useForm<z.input<typeof schema>, unknown, FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      kind: fromSignal ? "paper" : "real",
      stake: suggestedStake && suggestedStake > 0 ? suggestedStake.toFixed(2) : "",
      note: "",
    },
  });
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

  const submit = handleSubmit((values) =>
    send({
      match_id: matchId,
      outcome,
      bookmaker,
      odds,
      stake: values.stake,
      kind: values.kind,
      note: values.note || null,
      from_experimental_signal: fromSignal,
      confirm: false,
    }),
  );

  if (saved) {
    return (
      <div role="status" className="rounded border border-emerald-300 bg-emerald-50 p-3 text-sm">
        <p className="font-medium text-emerald-900">
          Apuesta {saved.kind === "paper" ? "en papel" : "real"} registrada (#{saved.id}).
        </p>
        {saved.warnings.length > 0 && (
          <ul className="mt-1 list-disc pl-5 text-amber-900">
            {saved.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}
        <Link to="/bets" className="mt-2 inline-block text-sky-800 underline">
          Ver mis apuestas
        </Link>
      </div>
    );
  }

  const blocked =
    create.error instanceof ApiError && create.error.status === 403 ? create.error : null;

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={submit}
      noValidate
      aria-label="Registrar apuesta"
    >
      <p className="text-sm">
        {OUTCOME_LABEL[outcome]} a <strong>{fmtOdds(odds)}</strong> en {bookmaker}
        {fromSignal && (
          <span className="ml-2">
            <ExperimentalBadge />
          </span>
        )}
      </p>
      {noReference && <NoReferenceNotice />}
      <fieldset className="flex gap-4 text-sm">
        <legend className="mb-1 text-sm">Tipo</legend>
        <label className="flex items-center gap-1">
          <input type="radio" value="paper" {...register("kind")} /> En papel
        </label>
        <label className="flex items-center gap-1">
          <input type="radio" value="real" {...register("kind")} /> Real (dinero)
        </label>
      </fieldset>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col text-sm">
          Stake
          <input
            inputMode="decimal"
            className="w-28 rounded border border-slate-300 px-2 py-1"
            {...register("stake")}
          />
          {errors.stake && <span className="text-xs text-red-700">{errors.stake.message}</span>}
        </label>
        <label className="flex flex-1 flex-col text-sm">
          Nota
          <input className="rounded border border-slate-300 px-2 py-1" {...register("note")} />
        </label>
        <button
          type="submit"
          className="rounded bg-sky-700 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          disabled={create.isPending || pending !== null}
        >
          Registrar apuesta
        </button>
      </div>
      {suggestedStake !== undefined && suggestedStake > 0 && (
        <p className="text-xs text-slate-600">
          Stake sugerido (Kelly fraccional, con tope): {suggestedStake.toFixed(2)}. Es orientativo.
        </p>
      )}
      {pending && (
        <div
          role="alertdialog"
          aria-label="Confirmación"
          className="rounded border border-amber-300 bg-amber-50 p-3 text-sm"
        >
          <ul className="list-disc pl-5 text-amber-900">
            {messages(pending.error).map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              className="rounded border border-slate-300 bg-white px-3 py-1"
              onClick={() => setPending(null)}
            >
              Cancelar
            </button>
            <button
              type="button"
              className="rounded bg-amber-700 px-3 py-1 text-white"
              onClick={() => send({ ...pending.body, confirm: true })}
            >
              Confirmar y registrar
            </button>
          </div>
        </div>
      )}
      {blocked && (
        <div
          role="alert"
          className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900"
        >
          <p className="font-medium">Apuestas reales bloqueadas este mes.</p>
          <p>{blocked.message}</p>
          {kind === "real" && (
            <button
              type="button"
              className="mt-2 rounded border border-slate-300 bg-white px-3 py-1 text-slate-900"
              onClick={() => {
                create.reset();
                setValue("kind", "paper");
              }}
            >
              Cambiar a papel
            </button>
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
      className="rounded border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900"
    >
      <strong>Sin cuota de referencia.</strong> Este partido no tiene cuotas de la API: la apuesta
      cuenta para todos los límites, queda fuera de la señal de valor y su CLV se calculará después
      con el cierre de Pinnacle de football-data si está disponible.
    </p>
  );
}

function messages(error: ApiError): string[] {
  const list = error.details["messages"];
  return Array.isArray(list) && list.length > 0 ? list.map(String) : [error.message];
}
