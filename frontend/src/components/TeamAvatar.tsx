import { initials } from "@/lib/team";
import { cn } from "@/lib/utils";

/** Team monogram, neutral (spec 005: no loud colors competing with the data; random hues
 *  made two teams look alike). No official crests are downloaded. */
export function TeamAvatar({
  name,
  size = "md",
  className,
}: {
  name: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full bg-secondary font-semibold tracking-tight text-foreground ring-1 ring-foreground/15 select-none",
        size === "sm" && "size-7 text-[0.65rem]",
        size === "md" && "size-9 text-xs",
        size === "lg" && "size-12 text-sm",
        className,
      )}
    >
      {initials(name)}
    </span>
  );
}
