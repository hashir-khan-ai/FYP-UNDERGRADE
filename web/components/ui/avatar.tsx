import { cn, initials } from "@/lib/utils";

const SIZES = {
  sm: "size-8 text-xs font-semibold",
  md: "size-10 text-xs",
  lg: "size-11 text-sm",
} as const;

export function Avatar({
  name,
  size = "md",
  className,
}: {
  name: string;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full bg-accent-soft font-semibold tracking-[0.02em] text-accent-link ring-1 ring-inset ring-line-accent",
        SIZES[size],
        className,
      )}
    >
      {initials(name)}
    </span>
  );
}
