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

/** Filter toolbar (date, league, accessible bookmakers) shared by Hoy and Top. No box around
 *  it: the filters sit on the page and the results carry the visual weight (spec 005). */
export function MatchFilters(props: Props) {
  const leagues = useLeagues();
  return (
    <div
      role="group"
      aria-label="Filtros"
      className="mb-6 flex flex-wrap items-end gap-x-3 gap-y-3 border-b pb-5"
    >
      <label className="flex w-40 flex-col gap-1.5 text-xs font-medium text-muted-foreground">
        Fecha
        <input
          type="date"
          className="field"
          value={props.date}
          onChange={(event) => props.onDate(event.target.value || todayLima())}
        />
      </label>
      <label className="flex w-44 flex-col gap-1.5 text-xs font-medium text-muted-foreground">
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
      <label className="flex h-10 cursor-pointer items-center gap-2 rounded-md px-2 text-sm transition-colors duration-150 hover:bg-secondary">
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
