import { cn, initials } from "@/lib/utils";

const SIZES = {
  sm: "size-8 text-xs font-semibold",
  md: "size-9.5 text-xs",
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
        "inline-flex shrink-0 items-center justify-center rounded-full border border-line-accent bg-[linear-gradient(135deg,rgba(120,169,255,0.24),rgba(84,214,196,0.12))] font-semibold tracking-[0.02em] text-ink",
        SIZES[size],
        className,
      )}
    >
      {initials(name)}
    </span>
  );
}
