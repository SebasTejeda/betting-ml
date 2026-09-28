import { cn } from "@/lib/utils";

/** Initials of a team name: "Real Madrid" -> "RM", "Arsenal" -> "AR". */
export function initials(name: string): string {
  const words = name
    .replace(/[^\p{L}\p{N} ]/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0]!.slice(0, 2).toUpperCase();
  return (words[0]![0]! + words[1]![0]!).toUpperCase();
}

/** Stable hue from the name (no official crests are downloaded). */
export function teamHue(name: string): number {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.codePointAt(0)!) >>> 0;
  return hash % 360;
}

export function TeamAvatar({
  name,
  size = "md",
  className,
}: {
  name: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const hue = teamHue(name);
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full font-semibold tracking-tight text-white ring-2 ring-background select-none",
        size === "sm" && "size-7 text-[0.65rem]",
        size === "md" && "size-9 text-xs",
        size === "lg" && "size-14 text-base",
        className,
      )}
      // Mid lightness/chroma keeps white initials readable (AA) for every hue.
      style={{ backgroundColor: `oklch(0.5 0.13 ${hue})` }}
    >
      {initials(name)}
    </span>
  );
}
