import {
  CircleCheck,
  FlaskConical,
  Lock,
  Save,
  Settings as SettingsIcon,
  ShieldCheck,
} from "lucide-react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { useSaveSettings, useSettings } from "../api/hooks";
import type { Settings } from "../api/types";
import { ErrorBox, ExperimentalBadge, Loading, PageTitle, Panel } from "../components/common";
import { Button } from "../components/ui/button";
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

  const field = (name: keyof Input, label: string, help?: string, suffix?: string) => (
    <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
      {label}
      <span className="relative">
        <input className="field pr-9 tabular-nums" {...register(name)} />
        {suffix && (
          <span
            aria-hidden
            className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-muted-foreground"
          >
            {suffix}
          </span>
        )}
      </span>
      {help && <span className="font-normal">{help}</span>}
      {errors[name] && <span className="font-normal text-negative">{errors[name]?.message}</span>}
    </label>
  );
  const currency = current.currency ?? "PEN";

  return (
    <>
      <PageTitle
        icon={SettingsIcon}
        description="Tu bankroll, los límites de juego responsable y los parámetros de la señal experimental."
      >
        Ajustes
      </PageTitle>
      <form
        className="flex flex-col gap-4"
        noValidate
        onSubmit={handleSubmit((values) => save.mutate(values))}
        aria-label="Ajustes"
      >
        <Panel title="Bankroll y límites" icon={ShieldCheck}>
          <div className="grid gap-4 sm:grid-cols-2">
            {field("bankroll_initial", "Bankroll inicial")}
            {field("currency", "Moneda")}
            {field(
              "monthly_loss_limit",
              "Límite de pérdida mensual",
              "Bajarlo aplica de inmediato; subirlo aplica desde el mes siguiente.",
            )}
            {field("max_stake_pct", "Stake máximo (% del bankroll)", undefined, "%")}
          </div>
          <p className="mt-4 flex flex-wrap items-center gap-2 rounded-lg bg-secondary/60 p-3 text-sm">
            <Lock aria-hidden className="size-4 text-primary" />
            Límite vigente este mes:{" "}
            <strong>{money(current.monthly_loss_limit_in_force, currency)}</strong>
            {pendingRaise &&
              ` · el nuevo límite de ${money(current.monthly_loss_limit, currency)} aplica desde el mes siguiente`}
          </p>
        </Panel>
        <Panel title="Señal experimental" icon={FlaskConical} action={<ExperimentalBadge />}>
          <div className="grid gap-4 sm:grid-cols-2">
            {field("kelly_fraction", "Fracción de Kelly (%)", undefined, "%")}
            {field("min_edge", "Umbral de EV de la señal (%)", undefined, "%")}
          </div>
        </Panel>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" size="lg" disabled={save.isPending}>
            <Save aria-hidden />
            Guardar
          </Button>
          {save.isSuccess && (
            <span role="status" className="flex items-center gap-1 text-sm text-positive">
              <CircleCheck aria-hidden className="size-4" />
              Ajustes guardados.
            </span>
          )}
        </div>
        {save.isError && <ErrorBox error={save.error} />}
      </form>
    </>
  );
}
