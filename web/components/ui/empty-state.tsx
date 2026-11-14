import * as React from "react";
import { EmptyDeskIllustration } from "@/components/visual/illustrations";
import { cn } from "@/lib/utils";

export interface EmptyStateProps extends React.HTMLAttributes<HTMLDivElement> {
  title: string;
  description?: string;
  action?: React.ReactNode;
  icon?: React.ReactNode;
}

export function EmptyState({
  title,
  description,
  action,
  icon,
  className,
  ...props
}: EmptyStateProps) {
  return (
    <div
      role="region"
      aria-label={title}
      className={cn(
        "flex flex-col items-center justify-center rounded-[var(--r-xl)] bg-surface p-8 text-center shadow-[var(--elev-1)]",
        className,
      )}
      {...props}
    >
      {icon ? (
        <div className="mb-4 flex size-14 items-center justify-center rounded-[var(--r-lg)] bg-surface-2 text-accent-link shadow-[var(--elev-1)]">
          {icon}
        </div>
      ) : (
        <EmptyDeskIllustration className="mb-4" />
      )}

      <h3 className="font-display text-lg font-semibold text-ink">
        {title}
      </h3>

      {description && (
        <p className="mt-1.5 max-w-md text-sm leading-relaxed text-muted">
          {description}
        </p>
      )}

      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

