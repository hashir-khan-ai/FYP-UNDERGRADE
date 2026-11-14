import * as React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FileCheck2 } from "lucide-react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MessageList } from "@/components/chat/message-list";
import { PipelineStepper, buildPipelineStages } from "@/components/chat/pipeline-stepper";
import { ThemeProvider, useTheme } from "@/components/providers/theme-provider";
import { StatCard } from "@/components/ui/stat-card";
import type { Message } from "@/lib/types";

function ThemeProbe() {
  const { theme, preference, toggleTheme, setPreference } = useTheme();
  return (
    <div>
      <span data-testid="theme-val">{theme}</span>
      <span data-testid="pref-val">{preference}</span>
      <button type="button" onClick={toggleTheme}>
        Toggle
      </button>
      <button type="button" onClick={() => setPreference("system")}>
        Follow system
      </button>
    </div>
  );
}

describe("Phase 16 Addendum polish", () => {
  const originalMatchMedia = window.matchMedia;

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
    window.localStorage.removeItem("crcs_theme");
    delete document.documentElement.dataset.theme;
  });

  it("ThemeProvider follows system prefers-color-scheme until overridden and remembers explicit choice", async () => {
    const user = userEvent.setup();
    let prefersLight = true;
    const listeners = new Set<(event: MediaQueryListEvent) => void>();

    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("light") ? prefersLight : false,
      media: query,
      onchange: null,
      addEventListener: (_type: string, cb: (event: MediaQueryListEvent) => void) => listeners.add(cb),
      removeEventListener: (_type: string, cb: (event: MediaQueryListEvent) => void) =>
        listeners.delete(cb),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    );

    expect(screen.getByTestId("pref-val")).toHaveTextContent("system");
    expect(screen.getByTestId("theme-val")).toHaveTextContent("light");
    expect(document.documentElement.dataset.theme).toBe("light");

    // Live OS switch to dark applies immediately in system mode
    act(() => {
      prefersLight = false;
      listeners.forEach((cb) => cb({ matches: false } as MediaQueryListEvent));
    });
    expect(screen.getByTestId("theme-val")).toHaveTextContent("dark");

    // Explicit toggle persists choice to localStorage
    await user.click(screen.getByRole("button", { name: "Toggle" }));
    expect(screen.getByTestId("theme-val")).toHaveTextContent("light");
    expect(screen.getByTestId("pref-val")).toHaveTextContent("light");
    expect(window.localStorage.getItem("crcs_theme")).toBe("light");

    // Follow system clears saved key and picks up current OS state
    await user.click(screen.getByRole("button", { name: "Follow system" }));
    expect(window.localStorage.getItem("crcs_theme")).toBeNull();
    expect(screen.getByTestId("theme-val")).toHaveTextContent("dark");
  });

  it("StatCard renders honest 'No data yet' without fake series and renders SVG visuals with real data", () => {
    const { rerender } = render(
      <StatCard
        label="Audited turns"
        value={0}
        caption="Waiting for ledger rows"
        icon={<FileCheck2 className="size-4" />}
        sparkline={[]}
        sparkVariant="bars"
        emptyVisualText="No data yet"
      />,
    );

    expect(screen.getByText("No data yet")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();

    rerender(
      <StatCard
        label="Audited turns"
        value={4}
        delta="4 visible"
        caption="Total verified query records"
        icon={<FileCheck2 className="size-4" />}
        sparkline={[120, 240, 180, 210]}
        sparkVariant="bars"
        sparkLabel="Token volume trend"
      />,
    );

    expect(screen.queryByText("No data yet")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Token volume trend" })).toBeInTheDocument();
    expect(screen.getByText("4 visible")).toBeInTheDocument();
  });

  it("PipelineStepper dims skipped stages on DIRECT_REPLY and shows real timings otherwise", () => {
    const skippedStages = buildPipelineStages({
      mode: "completed",
      routeUsed: "DIRECT_REPLY",
      timings: { route_ms: 42, answer_ms: 190 },
    });

    const { rerender } = render(<PipelineStepper stages={skippedStages} />);

    const retrieveNode = screen.getByText("Retrieve").closest("li");
    const rerankNode = screen.getByText("Re-rank").closest("li");
    const gradeNode = screen.getByText("Grade").closest("li");
    expect(retrieveNode).toHaveAttribute("data-stage-status", "skipped");
    expect(rerankNode).toHaveAttribute("data-stage-status", "skipped");
    expect(gradeNode).toHaveAttribute("data-stage-status", "skipped");
    expect(screen.getAllByText("skipped")).toHaveLength(3);
    expect(screen.getByText("42 ms")).toBeInTheDocument();

    const ragStages = buildPipelineStages({
      mode: "completed",
      routeUsed: "SINGLE_SEARCH",
      timings: { route_ms: 35, retrieve_ms: 88, rerank_ms: 54, grade_ms: 61, answer_ms: 210 },
    });
    rerender(<PipelineStepper stages={ragStages} />);
    expect(screen.getByText("88 ms")).toBeInTheDocument();
    expect(screen.getByText("54 ms")).toBeInTheDocument();
    expect(screen.queryByText("skipped")).not.toBeInTheDocument();

    // Backend timings dict keys (retrieval_ms, rerank_ms, generation_ms) & nowrap equal-height stepper layout
    const backendStages = buildPipelineStages({
      mode: "completed",
      routeUsed: "SINGLE_SEARCH",
      timings: { retrieval_ms: 42, rerank_ms: 664, generation_ms: 24 },
    });
    rerender(<PipelineStepper stages={backendStages} />);
    expect(screen.getByText("664 ms")).toHaveClass("whitespace-nowrap");
    expect(screen.getByText("42 ms")).toHaveClass("whitespace-nowrap");
    expect(screen.getByText("24 ms")).toHaveClass("whitespace-nowrap");
    expect(screen.getByRole("list")).toHaveClass("sm:items-stretch");
  });

  it("highlights active inline citation pin on hover/focus while preserving unique collapsed citation lookup", async () => {
    const user = userEvent.setup();
    const message: Message = {
      id: 99,
      sender: "assistant",
      content: "Firms must verify governance controls [1].",
      route_used: "SINGLE_SEARCH",
      user_role: "analyst",
      metadata: {
        grounded: true,
        response_type: "rag",
        citations: [
          {
            doc_id: "FCA-1",
            doc_name: "FCA Handbook",
            doc_title: "FCA Handbook — SYSC",
            section_title: "Outsourcing",
            clause_id: "SYSC 8.1.1",
            page_number: 12,
            snippet: "A firm must take reasonable steps.",
            source_url: "https://www.handbook.fca.org.uk/handbook/SYSC/8/1.html",
            source_name: "FCA",
            is_internal: false,
          },
        ],
      },
      created_at: "2026-01-01T10:00:00Z",
    };

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

    expect(screen.queryByText(/clause index/i)).not.toBeInTheDocument();
    expect(document.querySelector('[data-cite-marginalia="1"]')).toBeNull();

    const pin = screen.getByRole("button", { name: "Jump to source 1" });
    expect(pin.className).not.toContain("bg-accent text-accent-ink");

    await user.hover(pin);
    expect(pin.className).toContain("bg-accent text-accent-ink");
    await user.unhover(pin);
    expect(pin.className).not.toContain("bg-accent text-accent-ink");

    fireEvent.focus(pin);
    expect(pin.className).toContain("bg-accent text-accent-ink");
    fireEvent.blur(pin);
    expect(pin.className).not.toContain("bg-accent text-accent-ink");

    await user.click(screen.getByRole("button", { name: /sources \(1\)/i }));
    expect(screen.getByText("FCA Handbook — SYSC")).toBeInTheDocument();
    const clauseMatches = screen.getAllByText("SYSC 8.1.1");
    expect(clauseMatches.some((el) => el.tagName === "P")).toBe(true);

    const citeCard = document.querySelector('[data-cite-card="1"]');
    expect(citeCard).not.toBeNull();
    await user.hover(pin);
    expect(citeCard?.className).toContain("ring-line-accent");
    await user.unhover(pin);
    expect(citeCard?.className).not.toContain("ring-line-accent");
  });

  it("ErrorState treats LLM_AUTH_ERROR distinctly rather than claiming localhost:8000 is offline", async () => {
    const { ErrorState } = await import("@/components/ui/error-state");
    render(<ErrorState statusCode={503} errorCode="LLM_AUTH_ERROR" />);
    expect(screen.getByText("LLM Provider Authentication Failed")).toBeInTheDocument();
    expect(screen.queryByText("Compliance Service Offline")).not.toBeInTheDocument();
  });
});
