import {
  CircleAlert,
  FlaskConical,
  Inbox,
  type LucideIcon,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import type { ReactNode } from "react";

import { ApiError } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Card as UiCard, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";

export const EXPERIMENTAL_LABEL = "EXPERIMENTAL — solo papel";

export function PageTitle({
  children,
  description,
  icon: Icon,
  aside,
}: {
  children: ReactNode;
  description?: ReactNode;
  icon?: LucideIcon;
  aside?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          {Icon && <Icon aria-hidden className="size-6 text-primary" />}
          {children}
        </h1>
        {description && (
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {aside}
    </div>
  );
}

/** Card with an optional title row (icon + title + action). */
export function Panel({
  title,
  icon: Icon,
  action,
  children,
  className,
  contentClassName,
}: {
  title?: ReactNode;
  icon?: LucideIcon;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}) {
  return (
    <UiCard className={cn("shadow-sm transition-colors duration-150", className)}>
      {title && (
        <CardHeader className="flex flex-row items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base font-semibold">
            {Icon && <Icon aria-hidden className="size-4 text-muted-foreground" />}
            <h2>{title}</h2>
          </CardTitle>
          {action}
        </CardHeader>
      )}
      <CardContent className={contentClassName}>{children}</CardContent>
    </UiCard>
  );
}

/** Skeleton placeholder; screen readers still hear "Cargando …". */
export function Loading({
  what = "datos",
  variant = "panel",
}: {
  what?: string;
  variant?: "panel" | "cards" | "table";
}) {
  return (
    <div role="status" aria-live="polite" className="w-full">
      <span className="sr-only">Cargando {what}…</span>
      {variant === "cards" ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-44 rounded-xl" />
          ))}
        </div>
      ) : variant === "table" ? (
        <div className="flex flex-col gap-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-6 w-1/3" />
          <Skeleton className="h-32 rounded-xl" />
        </div>
      )}
    </div>
  );
}

/** Shows an API error with its message (and a hint for the write key). */
export function ErrorBox({ error }: { error: unknown }) {
  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : "Error inesperado";
  const hint =
    error instanceof ApiError && error.code === "UNAUTHORIZED"
      ? " Configura la clave de escritura (botón arriba a la derecha)."
      : "";
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-lg border border-negative/40 bg-negative-soft p-3 text-sm text-foreground"
    >
      <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-negative" />
      <span>
        {message}
        {hint}
      </span>
    </div>
  );
}

export function Empty({
  children,
  icon: Icon = Inbox,
  title,
}: {
  children: ReactNode;
  icon?: LucideIcon;
  title?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed p-8 text-center">
      <span className="flex size-12 items-center justify-center rounded-full bg-muted">
        <Icon aria-hidden className="size-6 text-muted-foreground" />
      </span>
      {title && <p className="font-medium">{title}</p>}
      <p className="max-w-md text-sm text-muted-foreground">{children}</p>
    </div>
  );
}

/** The experimental value signal is always labelled as such (never "recomendado"). */
export function ExperimentalBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex w-fit items-center gap-1 rounded-md border border-experimental-border bg-experimental-soft px-2 py-0.5 text-xs font-semibold text-experimental",
        className,
      )}
    >
      <FlaskConical aria-hidden className="size-3.5" />
      {EXPERIMENTAL_LABEL}
    </span>
  );
}

export function evTone(ev: number | null | undefined): string {
  if (ev === null || ev === undefined) return "text-muted-foreground";
  return ev > 0 ? "text-positive" : ev < 0 ? "text-negative" : "text-foreground";
}

/** EV with its sign, color and an icon (never color alone). */
export function EvValue({ ev, className }: { ev: number | null | undefined; className?: string }) {
  const Icon = ev !== null && ev !== undefined && ev < 0 ? TrendingDown : TrendingUp;
  return (
    <span className={cn("inline-flex items-center gap-1 tabular-nums", evTone(ev), className)}>
      {ev !== null && ev !== undefined && <Icon aria-hidden className="size-3.5" />}
      EV {pct(ev, 1, true)}
    </span>
  );
}

export function ModelBadge({ agrees }: { agrees: boolean | null | undefined }) {
  if (agrees === null || agrees === undefined) return null;
  return (
    <Badge variant="outline" className="font-normal text-muted-foreground">
      {agrees ? "el modelo coincide" : "el modelo no coincide"}
    </Badge>
  );
}

/** Accessible meter (role=progressbar) whose color is a design token. */
export function Meter({
  label,
  value,
  max = 100,
  tone = "primary",
}: {
  label: string;
  value: number;
  max?: number;
  tone?: "primary" | "positive" | "experimental" | "negative";
}) {
  const share = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      className="h-2 w-full overflow-hidden rounded-full bg-muted"
    >
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-200",
          tone === "primary" && "bg-primary",
          tone === "positive" && "bg-positive",
          tone === "experimental" && "bg-experimental",
          tone === "negative" && "bg-negative",
        )}
        style={{ width: `${share * 100}%` }}
      />
    </div>
  );
}
