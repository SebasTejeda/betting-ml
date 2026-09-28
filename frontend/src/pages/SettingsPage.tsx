import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { useSaveSettings, useSettings } from "../api/hooks";
import type { Settings } from "../api/types";
import { Card, ErrorBox, Loading, PageTitle } from "../components/common";
import { money } from "../lib/format";

const amount = z
  .string()
  .trim()
  .regex(/^\d+([.,]\d{1,2})?$/, "Monto inválido (máximo 2 decimales)")
  .transform((v) => Number(v.replace(",", ".")));
const percent = (min: number, max: number) =>
  z.coerce
    .number<string>()
    .min(min, `Mínimo ${min} %`)
    .max(max, `Máximo ${max} %`)
    .transform((v) => v / 100);

const schema = z.object({
  bankroll_initial: amount,
  currency: z.string().trim().length(3, "Código de 3 letras (PEN)").toUpperCase(),
  monthly_loss_limit: amount,
  max_stake_pct: percent(0.1, 100),
  kelly_fraction: percent(1, 100),
  min_edge: percent(0, 100),
});
type Input = z.input<typeof schema>;
type Output = z.output<typeof schema>;

function toInput(s: Settings): Input {
  const p = (v: number) => String(Math.round(v * 10000) / 100);
  return {
    bankroll_initial: s.bankroll_initial.toFixed(2),
    currency: s.currency ?? "PEN",
    monthly_loss_limit: s.monthly_loss_limit.toFixed(2),
    max_stake_pct: p(s.max_stake_pct),
    kelly_fraction: p(s.kelly_fraction),
    min_edge: p(s.min_edge),
  };
}

export function SettingsPage() {
  const settings = useSettings();
  if (settings.isPending) return <Loading what="los ajustes" />;
  if (settings.isError) return <ErrorBox error={settings.error} />;
  return <SettingsForm settings={settings.data} />;
}

function SettingsForm({ settings }: { settings: Settings }) {
  const save = useSaveSettings();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Input, unknown, Output>({
    resolver: zodResolver(schema),
    defaultValues: toInput(settings),
  });
  const current = save.data ?? settings;
  const pendingRaise = current.monthly_loss_limit > current.monthly_loss_limit_in_force;

  const field = (name: keyof Input, label: string, help?: string) => (
    <label className="flex flex-col text-sm">
      {label}
      <input className="rounded border border-slate-300 px-2 py-1" {...register(name)} />
      {help && <span className="text-xs text-slate-600">{help}</span>}
      {errors[name] && <span className="text-xs text-red-700">{errors[name]?.message}</span>}
    </label>
  );

  return (
    <>
      <PageTitle>Ajustes</PageTitle>
      <Card>
        <form
          className="grid gap-4 sm:grid-cols-2"
          noValidate
          onSubmit={handleSubmit((values) => save.mutate(values))}
          aria-label="Ajustes"
        >
          {field("bankroll_initial", "Bankroll inicial")}
          {field("currency", "Moneda")}
          {field(
            "monthly_loss_limit",
            "Límite de pérdida mensual",
            "Bajarlo aplica de inmediato; subirlo aplica desde el mes siguiente.",
          )}
          {field("max_stake_pct", "Stake máximo (% del bankroll)")}
          {field("kelly_fraction", "Fracción de Kelly (%)")}
          {field("min_edge", "Umbral de EV de la señal (%)")}
          <div className="sm:col-span-2 flex flex-wrap items-center gap-3">
            <button
              type="submit"
              className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
              disabled={save.isPending}
            >
              Guardar
            </button>
            {save.isSuccess && (
              <span role="status" className="text-sm text-emerald-800">
                Ajustes guardados.
              </span>
            )}
          </div>
        </form>
        <p className="mt-4 text-sm">
          Límite vigente este mes:{" "}
          <strong>{money(current.monthly_loss_limit_in_force, current.currency ?? "PEN")}</strong>
          {pendingRaise &&
            ` · el nuevo límite de ${money(current.monthly_loss_limit, current.currency ?? "PEN")} aplica desde el mes siguiente`}
        </p>
        {save.isError && (
          <div className="mt-3">
            <ErrorBox error={save.error} />
          </div>
        )}
      </Card>
    </>
  );
}
