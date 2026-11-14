"use client";

import { useEffect } from "react";
import { ErrorState } from "@/components/ui/error-state";

export default function ChatError({
  error,
  reset,
}: {
  error: Error & { digest?: string; status?: number };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Chat view error:", error.digest ?? "no-digest");
  }, [error]);

  return (
    <div className="flex min-h-[60dvh] items-center justify-center p-6">
      <ErrorState
        statusCode={error.status || 500}
        message="A disruption occurred while rendering the conversational workspace."
        onRetry={reset}
        className="max-w-md w-full"
      />
    </div>
  );
}

