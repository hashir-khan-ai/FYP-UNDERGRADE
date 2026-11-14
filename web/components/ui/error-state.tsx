import * as React from "react";
import { AlertCircle, RefreshCw, Flag, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface ErrorStateProps extends React.HTMLAttributes<HTMLDivElement> {
  statusCode?: number;
  errorCode?: string;
  message?: string;
  onRetry?: () => void;
  showReportIssue?: boolean;
}

export function ErrorState({
  statusCode,
  errorCode,
  message,
  onRetry,
  showReportIssue = true,
  className,
  ...props
}: ErrorStateProps) {
  const [reported, setReported] = React.useState(false);

  // Human-friendly messaging mapping
  let title = "Something went wrong";
  let explanation = message || "An unexpected error occurred while processing your request.";

  if (statusCode === 429 || errorCode === "RATE_OR_SPEND_LIMIT" || errorCode === "RATE_LIMIT_EXCEEDED") {
    title = "Rate Limit or Spend Cap Reached";
    explanation =
      "The system has reached the allocated safety quota for this run or session. Your live usage budget will reset shortly. You can start a new session or retry in a few moments.";
  } else if (statusCode === 503 || errorCode === "SERVICE_UNAVAILABLE") {
    title = "Compliance Service Offline";
    explanation =
      "The local compliance API or embedded vector service is currently unavailable. Please check that the backend server is active on localhost:8000 and try again.";
  } else if (statusCode === 403 || errorCode === "FORBIDDEN") {
    title = "Access Restricted";
    explanation =
      "Your authenticated security role does not have permission to access or modify this resource. Only authorized clearance tiers may view these compliance materials.";
  } else if (statusCode === 404 || errorCode === "NOT_FOUND") {
    title = "Item Not Found";
    explanation = "The requested item or session could not be found or has been deleted.";
  }

  // SECURITY CONTRACT: "Report an issue" must NEVER include query text, answers, or citations
  const handleReportIssue = () => {
    const sanitizedDiagnostic = {
      timestamp: new Date().toISOString(),
      statusCode: statusCode || 500,
      errorCode: errorCode || "UNKNOWN_ERROR",
      userAgent: typeof navigator !== "undefined" ? navigator.userAgent : "SSR",
      // Sensitive fields explicitly omitted per security mandate
      queryText: undefined,
      answerText: undefined,
      citations: undefined,
    };

    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(
        `[Compliance RAG Error Report]\nTimestamp: ${sanitizedDiagnostic.timestamp}\nStatus: ${sanitizedDiagnostic.statusCode}\nCode: ${sanitizedDiagnostic.errorCode}\nBrowser: ${sanitizedDiagnostic.userAgent}`
      );
    }
    setReported(true);
    setTimeout(() => setReported(false), 3000);
  };

  return (
    <div
      role="alert"
      aria-live="assertive"
      className={cn(
        "flex flex-col items-center justify-center p-8 text-center rounded-xl",
        "border border-[var(--status-danger-border)] bg-[var(--status-danger-subtle)] text-[var(--text-primary)]",
        className
      )}
      {...props}
    >
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-[var(--surface-primary)] text-[var(--status-danger)] mb-4 shadow-xs">
        <AlertCircle className="h-7 w-7" aria-hidden="true" />
      </div>

      <h3 className="text-base font-semibold text-[var(--text-primary)]">
        {title}
      </h3>

      <p className="mt-2 max-w-md text-sm text-[var(--text-secondary)] leading-relaxed">
        {explanation}
      </p>

      {errorCode && (
        <p className="mt-1 text-xs font-mono text-[var(--text-muted)]">
          Error code: {errorCode}
        </p>
      )}

      <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
        {onRetry && (
          <Button
            variant="primary"
            size="md"
            onClick={onRetry}
            className="flex items-center gap-2"
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            <span>Try Again</span>
          </Button>
        )}

        {showReportIssue && (
          <Button
            variant="outline"
            size="md"
            onClick={handleReportIssue}
            className="flex items-center gap-2 text-xs"
            title="Copies sanitized diagnostic data (code & timestamp) without query text"
          >
            {reported ? (
              <>
                <Check className="h-3.5 w-3.5 text-[var(--status-success)]" aria-hidden="true" />
                <span>Diagnostic Copied!</span>
              </>
            ) : (
              <>
                <Flag className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Report an Issue</span>
              </>
            )}
          </Button>
        )}
      </div>
    </div>
  );
}

