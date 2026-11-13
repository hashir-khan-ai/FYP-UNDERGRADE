import { cn } from "@/lib/utils";

export function Progress({
  value,
  label,
  indeterminate = false,
  className,
}: {
  value?: number;
  label?: string;
  indeterminate?: boolean;
  className?: string;
}) {
  const clamped = typeof value === "number" ? Math.min(100, Math.max(0, value)) : null;

  return (
    <div
      role="progressbar"
      aria-label={label ?? "Progress"}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate || clamped === null ? undefined : Math.round(clamped)}
      aria-valuetext={
        indeterminate
          ? "In progress"
          : clamped !== null
            ? `${Math.round(clamped)} percent`
            : undefined
      }
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]", className)}
    >
      <div
        className={cn(
          "h-full rounded-full bg-[linear-gradient(90deg,var(--accent-strong),var(--teal))] transition-[width] duration-[var(--duration-slow)] ease-[var(--ease-out)]",
          indeterminate && "animate-soft-pulse w-1/2",
        )}
        style={indeterminate || clamped === null ? undefined : { width: `${clamped}%` }}
      />
    </div>
  );
}
