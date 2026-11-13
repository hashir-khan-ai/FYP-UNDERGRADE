import Link from "next/link";

import { Logo } from "@/components/brand/logo";
import { buttonVariants } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="relative flex min-h-dvh flex-col items-center justify-center px-4 text-center">
      <div className="app-atmosphere" aria-hidden="true" />
      <Logo showWordmark />
      <p className="mt-6 font-mono text-[0.6875rem] uppercase tracking-[0.16em] text-faint">
        404 · Not found
      </p>
      <h1 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-ink">
        That page is outside the workspace.
      </h1>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-muted">
        The session may have been deleted, or the link is not part of the compliance workspace.
      </p>
      <div className="mt-6 flex gap-2">
        <Link href="/chat" className={buttonVariants({ variant: "primary", size: "md" })}>
          Return to chat
        </Link>
        <Link href="/documents" className={buttonVariants({ variant: "secondary", size: "md" })}>
          Document catalog
        </Link>
      </div>
    </div>
  );
}
