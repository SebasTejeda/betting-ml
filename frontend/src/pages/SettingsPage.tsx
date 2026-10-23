import { CircleCheck, Lock, Save } from "lucide-react";
import { zodResolver } from "@hookform/resolvers/zod";
import { type ReactNode, useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { isVersionConflict } from "../api/client";
import { useSaveSettings, useSettings } from "../api/hooks";
import type { Settings } from "../api/types";
import { ErrorBox, ExperimentalBadge, Loading, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
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
  currency: z
    .string()
    .trim()
    .regex(/^[A-Za-z]{3}$/, "Código de 3 letras (PEN)")
    .toUpperCase(),
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

/** Settings section: what it is and why on the left, the fields on the right. */
function Section({
  title,
  description,
  badge,
  children,
}: {
  title: string;
  description: ReactNode;
  badge?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card className="gap-6 p-5 sm:p-6 md:grid md:grid-cols-[minmax(0,16rem)_minmax(0,1fr)] md:gap-10">
      <div className="flex flex-col gap-2">
        <h2 className="font-semibold tracking-tight">{title}</h2>
        {badge}
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="min-w-0">{children}</div>
    </Card>
  );
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
    reset,
    formState: { errors },
  } = useForm<Input, unknown, Output>({
    resolver: zodResolver(schema),
    defaultValues: toInput(settings),
  });
  const current = save.data ?? settings;
  // Saved elsewhere meanwhile (409): show the reloaded values, never overwrite them blindly.
  const conflict = isVersionConflict(save.error);
  useEffect(() => {
    if (conflict) reset(toInput(settings));
  }, [conflict, settings, reset]);
  const pendingRaise = current.monthly_loss_limit > current.monthly_loss_limit_in_force;

  const field = (name: keyof Input, label: string, help?: string, suffix?: string) => (
    <label className="flex flex-col gap-1.5 text-xs font-medium text-muted-foreground">
      {label}
      <span className="relative">
        <input className="field num pr-9" {...register(name)} />
        {suffix && (
          <span
            aria-hidden
            className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-muted-foreground"
          >
            {suffix}
          </span>
        )}
      </span>
      {help && <span className="font-normal text-muted-foreground">{help}</span>}
      {errors[name] && <span className="font-normal text-negative">{errors[name]?.message}</span>}
    </label>
  );
  const currency = current.currency ?? "PEN";

  return (
    <>
      <PageTitle description="Tu bankroll, los límites de juego responsable y los parámetros de la señal experimental.">
        Ajustes
      </PageTitle>
      <form
        className="mt-6 flex flex-col gap-5"
        noValidate
        onSubmit={handleSubmit((values) => save.mutate({ ...values, version: current.version }))}
        aria-label="Ajustes"
      >
        <Section
          title="Bankroll y límites"
          description="Juego responsable: el límite de pérdida mensual no se puede saltar desde la app, y el stake máximo te avisa antes de una apuesta demasiado grande."
        >
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
          <p className="mt-5 flex flex-wrap items-center gap-2 rounded-lg bg-muted px-3 py-2.5 text-sm">
            <Lock aria-hidden className="size-4 text-muted-foreground" />
            Límite vigente este mes:{" "}
            <strong className="num">{money(current.monthly_loss_limit_in_force, currency)}</strong>
            {pendingRaise &&
              ` · el nuevo límite de ${money(current.monthly_loss_limit, currency)} aplica desde el mes siguiente`}
          </p>
        </Section>
        <Section
          title="Señal experimental"
          badge={<ExperimentalBadge />}
          description="La señal no tiene evidencia todavía. El umbral de EV decide qué cuotas se marcan; la fracción de Kelly, el stake sugerido."
        >
          <div className="grid gap-4 sm:grid-cols-2">
            {field("kelly_fraction", "Fracción de Kelly (%)", undefined, "%")}
            {field("min_edge", "Umbral de EV de la señal (%)", undefined, "%")}
          </div>
        </Section>
        <div className="flex flex-wrap items-center justify-end gap-3">
          {save.isSuccess && (
            <span role="status" className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <CircleCheck aria-hidden className="size-4 text-positive" />
              Ajustes guardados.
            </span>
          )}
          <Button type="submit" size="lg" disabled={save.isPending}>
            <Save aria-hidden />
            Guardar
          </Button>
        </div>
        {save.isError && <ErrorBox error={save.error} />}
      </form>
    </>
  );
}
