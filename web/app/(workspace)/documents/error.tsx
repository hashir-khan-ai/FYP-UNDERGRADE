"use client";

import { useEffect } from "react";
import { ErrorState } from "@/components/ui/error-state";

export default function DocumentsError({
  error,
  reset,
}: {
  error: Error & { digest?: string; status?: number };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Documents view error:", error.digest ?? "no-digest");
  }, [error]);

  return (
    <div className="flex min-h-[60dvh] items-center justify-center p-6">
      <ErrorState
        statusCode={error.status || 500}
        message="Could not load the compliance document catalog."
        onRetry={reset}
        className="max-w-md w-full"
      />
    </div>
  );
}

