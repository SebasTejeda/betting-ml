import { OUTCOME_TONE } from "@/lib/outcome";
import { cn } from "@/lib/utils";

type Split = { home?: number | null; draw?: number | null; away?: number | null };

/** One bar split home / draw / away; decorative, the figures are always written next to it. */
export function SplitBar({ values, className }: { values: Split; className?: string }) {
  return (
    <div aria-hidden className={cn("flex h-2 gap-0.5 overflow-hidden rounded-full", className)}>
      {(["home", "draw", "away"] as const).map((key) => (
        <div
          key={key}
          className={cn("transition-[width] duration-200", OUTCOME_TONE[key])}
          style={{ width: `${100 * (values[key] ?? 0)}%` }}
        />
      ))}
    </div>
  );
}
