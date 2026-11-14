import { LockKeyhole } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";

export function RestrictedPanel({
  title,
  description,
  requiredRole,
  children,
}: {
  title: string;
  description: string;
  requiredRole?: string;
  children?: ReactNode;
}) {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center px-4 py-16 text-center sm:py-24">
      <span className="mb-5 inline-flex size-12 items-center justify-center rounded-full border border-line bg-surface-2 text-faint">
        <LockKeyhole className="size-5" aria-hidden="true" />
      </span>
      <h2 className="text-base font-semibold tracking-[-0.015em] text-ink">{title}</h2>
      <p className="mt-2 text-sm leading-relaxed text-muted">{description}</p>
      {requiredRole ? (
        <Badge tone="outline" className="mt-4">
          Requires {requiredRole}
        </Badge>
      ) : null}
      {children ? <div className="mt-6">{children}</div> : null}
      <p className="mt-6 max-w-md text-xs leading-relaxed text-faint">
        This is a user-experience restriction. Authorisation itself is always enforced inside the
        retrieval engine and the API, never by this screen.
      </p>
    </div>
  );
}
