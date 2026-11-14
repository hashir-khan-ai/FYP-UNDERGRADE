"use client";

import { useEffect } from "react";
import Link from "next/link";

import { Button, buttonVariants } from "@/components/ui/button";

export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Keep the console free of prompts, tokens or user text.
    console.error("Unhandled workspace error", error.digest ?? "no-digest");
  }, [error]);

  return (
    <div className="flex min-h-[60dvh] flex-col items-center justify-center px-4 text-center">
      <p className="font-mono text-xs uppercase tracking-[0.14em] text-faint">
        Workspace error
      </p>
      <h1 className="mt-2 text-xl font-semibold tracking-[-0.025em] text-ink">
        Something interrupted this view.
      </h1>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-muted">
        No prompt, token or document text is logged. Retry the view, or return to the conversation.
      </p>
      <div className="mt-5 flex gap-2">
        <Button variant="primary" onClick={reset}>
          Try again
        </Button>
        <Link href="/chat" className={buttonVariants({ variant: "secondary" })}>
          Back to chat
        </Link>
      </div>
    </div>
  );
}
