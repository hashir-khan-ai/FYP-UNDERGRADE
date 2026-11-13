import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  className,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex flex-wrap items-start justify-between gap-4 border-b border-line px-4 py-5 sm:px-6 lg:px-10 lg:py-6",
        className,
      )}
    >
      <div className="min-w-0 max-w-2xl">
        {eyebrow ? (
          <p className="mb-1 text-[0.625rem] font-semibold uppercase tracking-[0.12em] text-faint">
            {eyebrow}
          </p>
        ) : null}
        <h1 className="text-lg font-semibold tracking-[-0.02em] text-ink sm:text-xl">{title}</h1>
        {description ? (
          <p className="mt-1.5 text-xs leading-relaxed text-muted sm:text-[0.8125rem]">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
