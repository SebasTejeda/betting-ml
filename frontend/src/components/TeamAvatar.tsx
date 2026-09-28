import { initials, teamHue } from "@/lib/team";
import { cn } from "@/lib/utils";

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
