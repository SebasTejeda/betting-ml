import { CalendarDays, Filter } from "lucide-react";

import { useLeagues } from "@/api/hooks";
import { todayLima } from "@/lib/format";

type Props = {
  date: string;
  onDate: (date: string) => void;
  league: string;
  onLeague: (league: string) => void;
  accessibleOnly: boolean;
  onAccessibleOnly: (value: boolean) => void;
};

/** Compact filter bar (date, league, accessible bookmakers) shared by Hoy and Top. */
export function MatchFilters(props: Props) {
  const leagues = useLeagues();
  return (
    <div
      role="group"
      aria-label="Filtros"
      className="mb-5 flex flex-wrap items-end gap-3 rounded-xl border bg-card p-3 shadow-sm"
    >
      <Filter aria-hidden className="mb-2 hidden size-4 text-muted-foreground sm:block" />
      <label className="flex min-w-36 flex-col gap-1 text-xs font-medium text-muted-foreground">
        <span className="flex items-center gap-1">
          <CalendarDays aria-hidden className="size-3.5" />
          Fecha
        </span>
        <input
          type="date"
          className="field"
          value={props.date}
          onChange={(event) => props.onDate(event.target.value || todayLima())}
        />
      </label>
      <label className="flex min-w-40 flex-col gap-1 text-xs font-medium text-muted-foreground">
        Liga
        <select
          className="field"
          value={props.league}
          onChange={(event) => props.onLeague(event.target.value)}
        >
          <option value="">Todas</option>
          {leagues.data?.map((item) => (
            <option key={item.code} value={item.code}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      <label className="flex h-9 cursor-pointer items-center gap-2 rounded-md px-2 text-sm transition-colors duration-150 hover:bg-secondary">
        <input
          type="checkbox"
          className="size-4 accent-(--primary)"
          checked={props.accessibleOnly}
          onChange={(event) => props.onAccessibleOnly(event.target.checked)}
        />
        Solo casas accesibles desde Perú
      </label>
    </div>
  );
}
