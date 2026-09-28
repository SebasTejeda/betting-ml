import type { ReactNode } from "react";

import { ApiError } from "../api/client";

export const EXPERIMENTAL_LABEL = "EXPERIMENTAL — solo papel";

export function PageTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <h1 className="text-2xl font-semibold text-slate-900">{children}</h1>
      {aside}
    </div>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-slate-200 bg-white p-4 shadow-sm ${className}`}>
      {children}
    </section>
  );
}

export function Loading({ what = "datos" }: { what?: string }) {
  return (
    <p role="status" className="text-slate-600">
      Cargando {what}…
    </p>
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
    <div role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
      {message}
      {hint}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="rounded border border-dashed border-slate-300 p-6 text-slate-600">{children}</p>
  );
}

/** The experimental value signal is always labelled as such (never "recomendado"). */
export function ExperimentalBadge() {
  return (
    <span className="inline-block rounded bg-amber-100 px-1.5 py-0.5 text-xs font-semibold text-amber-900">
      {EXPERIMENTAL_LABEL}
    </span>
  );
}
