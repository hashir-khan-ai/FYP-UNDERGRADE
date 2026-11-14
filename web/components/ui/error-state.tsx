import * as React from "react";
import { AlertCircle, Check, Flag, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { QuotaErrorIllustration } from "@/components/visual/illustrations";
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
  } else if (errorCode === "LLM_AUTH_ERROR") {
    title = "LLM Provider Authentication Failed";
    explanation =
      message ||
      "The configured LLM provider rejected the server credentials. Verify LLM_PROFILE and your API key in .env (or switch to mock/local) and restart the backend server.";
  } else if (errorCode === "LLM_UNAVAILABLE") {
    title = "LLM Provider Unavailable";
    explanation =
      message ||
      "The configured LLM provider could not be reached. Verify your provider endpoint in .env or switch to mock/local.";
  } else if (errorCode === "MODEL_WEIGHTS_MISSING") {
    title = "Local Model Weights Missing";
    explanation =
      message ||
      "Local embedding or re-ranking model weights could not be loaded on the backend server.";
  } else if (statusCode === 503 || errorCode === "SERVICE_UNAVAILABLE" || errorCode === "BACKEND_UNREACHABLE") {
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

  const isQuotaOrRate =
    statusCode === 429 ||
    errorCode === "RATE_OR_SPEND_LIMIT" ||
    errorCode === "RATE_LIMIT_EXCEEDED";

  return (
    <div
      role="alert"
      aria-live="assertive"
      className={cn(
        "flex flex-col items-center justify-center rounded-[var(--r-xl)] p-6 text-center shadow-[var(--elev-2)] sm:p-8",
        isQuotaOrRate
          ? "bg-surface text-ink ring-1 ring-inset ring-line-accent"
          : "bg-surface text-ink ring-1 ring-inset ring-danger/25",
        className,
      )}
      {...props}
    >
      {isQuotaOrRate ? (
        <QuotaErrorIllustration className="mb-3" />
      ) : (
        <div className="mb-4 flex size-14 items-center justify-center rounded-[var(--r-lg)] bg-danger-soft text-danger shadow-[var(--elev-1)]">
          <AlertCircle className="h-7 w-7" aria-hidden="true" />
        </div>
      )}

      <h3 className="font-display text-lg font-semibold text-ink">
        {title}
      </h3>

      <p className="mt-2 max-w-md text-sm leading-relaxed text-muted">
        {explanation}
      </p>

      {errorCode && (
        <p className="mt-2 font-mono text-xs text-faint">
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
                <Check className="h-4 w-4 text-success" aria-hidden="true" />
                <span>Diagnostic Copied!</span>
              </>
            ) : (
              <>
                <Flag className="h-4 w-4" aria-hidden="true" />
                <span>Report an Issue</span>
              </>
            )}
          </Button>
        )}
      </div>
    </div>
  );
}

