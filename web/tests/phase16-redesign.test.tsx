import * as React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MessageList } from "@/components/chat/message-list";
import { ThemeProvider, useTheme } from "@/components/providers/theme-provider";
import { AnimatedCounter } from "@/components/ui/animated-counter";
import { ErrorState } from "@/components/ui/error-state";
import type { Message } from "@/lib/types";

function makeCitedAssistantMessage(): Message {
  return {
    id: 42,
    sender: "assistant",
    content: "Under SYSC governance rules, firms must allocate responsibilities clearly [1].",
    route_used: "SINGLE_SEARCH",
    user_role: "analyst",
    created_at: "2026-11-14T12:00:00Z",
    metadata: {
      response_type: "rag",
      grounded: true,
      citations: [
        {
          doc_id: "DOC-SYSC-01",
          doc_name: "FCA Handbook — SYSC",
          doc_title: "FCA Handbook — SYSC",
          section_title: "SYSC 4.1",
          clause_id: "SYSC-4.1.1R",
          page_number: 14,
          snippet: "A firm must have robust governance arrangements including clear lines of responsibility.",
          source_url: "https://www.handbook.fca.org.uk/handbook/SYSC/4/1.html",
          is_internal: false,
          allowed_roles: ["analyst", "manager", "auditor"],
        },
      ],
    },
  };
}

function ThemeHarness() {
  const { theme, toggleTheme } = useTheme();
  return (
    <button type="button" onClick={toggleTheme} data-testid="theme-btn">
      Current: {theme}
    </button>
  );
}

describe("Phase 16 Compliance Ledger redesign", () => {
  it("links inline citation pins [1] to the collapsible source drawer without duplicating titles", () => {
    const message = makeCitedAssistantMessage();
    render(
      <MessageList
        messages={[message]}
        streamingId={null}
        onRegenerate={vi.fn()}
        onEdit={vi.fn()}
        onFollowUp={vi.fn()}
        onStreamDone={vi.fn()}
        sending={false}
      />,
    );

    const sourcesToggle = screen.getByRole("button", { name: /sources \(1\)/i });
    expect(sourcesToggle.getAttribute("aria-expanded")).toBe("false");

    const inlinePin = screen.getByRole("button", { name: /jump to source 1/i });
    expect(inlinePin.textContent).toBe("[1]");

    fireEvent.click(inlinePin);
    expect(sourcesToggle.getAttribute("aria-expanded")).toBe("true");
    // Uniqueness preserved: marginalia shows clause/page, never duplicates doc_title
    expect(screen.getByText("FCA Handbook — SYSC")).toBeTruthy();
  });

  it("toggles dark/light theme via ThemeProvider cleanly", () => {
    window.localStorage.removeItem("crcs_theme");
    render(
      <ThemeProvider>
        <ThemeHarness />
      </ThemeProvider>,
    );

    expect(document.documentElement.dataset.theme).toBe("dark");
    const btn = screen.getByTestId("theme-btn");
    expect(btn.textContent).toContain("dark");

    fireEvent.click(btn);
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(btn.textContent).toContain("light");
    expect(window.localStorage.getItem("crcs_theme")).toBe("light");
  });

  it("renders AnimatedCounter with tabular numbers cleanly under reduced motion", () => {
    render(<AnimatedCounter value={1240} />);
    expect(screen.getByText("1,240")).toBeTruthy();
  });

  it("renders ErrorState 429 spend-cap state cleanly with sanitized diagnostics", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    render(
      <ErrorState
        statusCode={429}
        errorCode="RATE_OR_SPEND_LIMIT"
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText(/Rate Limit or Spend Cap Reached/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Report an Issue/i }));
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText.mock.calls[0][0]).toContain("Status: 429");
  });
});

