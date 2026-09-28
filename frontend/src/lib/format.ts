export function money(value: number | null | undefined, currency = "PEN"): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("es-PE", { style: "currency", currency }).format(value);
}

export function pct(value: number | null | undefined, digits = 1, signed = false): string {
  if (value === null || value === undefined) return "—";
  const text = `${(100 * value).toFixed(digits)} %`;
  return signed && value > 0 ? `+${text}` : text;
}

export function odds(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toFixed(2);
}

export function kickoff(iso: string | null | undefined): string {
  if (!iso) return "hora por confirmar";
  return new Intl.DateTimeFormat("es-PE", {
    timeZone: "America/Lima",
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

/** Today in Lima as YYYY-MM-DD. */
export function todayLima(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Lima" }).format(now);
}
