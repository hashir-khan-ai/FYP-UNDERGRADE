import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { roleLabel } from "@/lib/auth";
import { cn } from "@/lib/utils";

export function PageHeader({
  eyebrow,
  title,
  description,
  role,
  actions,
  className,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  role?: string;
  actions?: ReactNode;
  className?: string;
}) {
  const normalizedRole = role?.toLowerCase();
  const roleTone =
    normalizedRole === "auditor"
      ? "info"
      : normalizedRole === "manager"
        ? "warning"
        : "neutral";

  return (
    <header
      className={cn(
        "flex flex-wrap items-start justify-between gap-4 border-b border-line px-4 py-5 sm:px-6 lg:px-10 lg:py-6",
        className,
      )}
    >
      <div className="min-w-0 max-w-2xl">
        <div className="mb-1.5 flex flex-wrap items-center gap-2.5">
          {eyebrow ? (
            <p className="font-mono text-xs font-semibold uppercase tracking-[0.12em] text-faint">
              {eyebrow}
            </p>
          ) : null}
          {normalizedRole ? (
            <Badge tone={roleTone} className="capitalize">
              {roleLabel(normalizedRole)}
            </Badge>
          ) : null}
        </div>
        <h1 className="font-display text-[clamp(1.375rem,2.4vw,1.875rem)] font-semibold tracking-[-0.02em] text-ink">
          {title}
        </h1>
        {description ? (
          <p className="mt-1.5 text-sm leading-relaxed text-muted">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
