import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";

import { CommandPalette } from "@/components/ui/command-palette";
import { DestructiveDialog } from "@/components/ui/destructive-dialog";
import { DataTable, ColumnDef } from "@/components/ui/data-table";
import { ErrorState } from "@/components/ui/error-state";
import { LoginScreen } from "@/components/auth/login-screen";
import { UploadDialog } from "@/components/documents/upload-dialog";
import { useDebouncedValue } from "@/lib/hooks/use-debounce";
import { useThrottledCallback } from "@/lib/hooks/use-throttle";
import { isEventFromEditable, matchesShortcut } from "@/lib/shortcuts";
import { sanitizeToastMessage } from "@/lib/toast";

vi.mock("@/components/providers/sessions-provider", () => ({
  useSessions: () => ({
    sessions: [
      { id: "sess-1", title: "AML Compliance Questions", created_at: "2026-11-14T10:00:00Z" },
      { id: "sess-2", title: "FCA Outsourcing Review", created_at: "2026-11-13T10:00:00Z" },
    ],
    createSession: vi.fn(),
    renameSession: vi.fn(),
    deleteSession: vi.fn(),
    refreshSessions: vi.fn(),
    activeSessionId: "sess-1",
    creating: false,
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => "/chat",
  useSearchParams: () => new URLSearchParams(),
}));

// Helper components for testing hooks
function DebounceTestComponent({ value, delay }: { value: string; delay: number }) {
  const debounced = useDebouncedValue(value, delay);
  return <div data-testid="debounced">{debounced}</div>;
}

function ThrottleTestComponent({ onExecute }: { onExecute: () => void }) {
  const throttled = useThrottledCallback(onExecute, 200);
  return (
    <button type="button" onClick={() => throttled()}>
      Execute
    </button>
  );
}

describe("Phase 15: UX Patterns & Security Rules", () => {
  describe("Security Rule 1: Zero leakage in toasts & diagnostics", () => {
    it("sanitizes canary tokens in toasts", () => {
      const canaryMsg = "Failed with CANARY-AUDITOR-XYZ token leak";
      const sanitized = sanitizeToastMessage(canaryMsg);
      expect(sanitized).toBe("Action blocked by security policy.");
      expect(sanitized).not.toContain("CANARY");
    });

    it("leaves safe error messages untouched", () => {
      const safe = "Session renamed successfully";
      expect(sanitizeToastMessage(safe)).toBe(safe);
    });
  });

  describe("Security Rule 2: Keyboard shortcuts context awareness", () => {
    it("recognizes input and textarea as editable elements", () => {
      const input = document.createElement("input");
      input.type = "text";
      const eventOnInput = { target: input } as unknown as KeyboardEvent;
      expect(isEventFromEditable(eventOnInput)).toBe(true);

      const textarea = document.createElement("textarea");
      const eventOnTextarea = { target: textarea } as unknown as KeyboardEvent;
      expect(isEventFromEditable(eventOnTextarea)).toBe(true);

      const div = document.createElement("div");
      const eventOnDiv = { target: div } as unknown as KeyboardEvent;
      expect(isEventFromEditable(eventOnDiv)).toBe(false);
    });

    it("matches shortcut combinations accurately", () => {
      const eventK = {
        key: "k",
        metaKey: true,
        ctrlKey: false,
        shiftKey: false,
        altKey: false,
      } as unknown as KeyboardEvent;
      expect(matchesShortcut(eventK, "meta+k")).toBe(true);
      expect(matchesShortcut(eventK, "meta+b")).toBe(false);

      const eventQuestion = {
        key: "?",
        metaKey: false,
        ctrlKey: false,
        shiftKey: true,
        altKey: false,
      } as unknown as KeyboardEvent;
      expect(matchesShortcut(eventQuestion, "?")).toBe(true);
    });
  });

  describe("Pattern 6: Debounce & Throttle Hooks", () => {
    it("useDebouncedValue updates only after delay", async () => {
      const { rerender } = render(<DebounceTestComponent value="initial" delay={100} />);
      expect(screen.getByTestId("debounced").textContent).toBe("initial");

      rerender(<DebounceTestComponent value="updated" delay={100} />);
      // Immediately still initial
      expect(screen.getByTestId("debounced").textContent).toBe("initial");

      await act(async () => {
        await new Promise((r) => setTimeout(r, 120));
      });
      expect(screen.getByTestId("debounced").textContent).toBe("updated");
    });

    it("useThrottledCallback throttles rapid clicks", async () => {
      const callback = vi.fn();
      render(<ThrottleTestComponent onExecute={callback} />);
      const btn = screen.getByRole("button", { name: "Execute" });

      // Click 4 times rapidly
      fireEvent.click(btn);
      fireEvent.click(btn);
      fireEvent.click(btn);
      fireEvent.click(btn);

      // Should have executed once immediately
      expect(callback).toHaveBeenCalledTimes(1);

      await act(async () => {
        await new Promise((r) => setTimeout(r, 220));
      });

      // After interval, trailing execution occurs
      expect(callback).toHaveBeenCalledTimes(2);
    });
  });

  describe("Pattern 7: Destructive Confirmation Dialog", () => {
    it("Mode 1 (simple confirm) triggers callback on confirm click", () => {
      const onConfirm = vi.fn();
      const onOpenChange = vi.fn();
      render(
        <DestructiveDialog
          open={true}
          onOpenChange={onOpenChange}
          title="Delete session?"
          description="Permanent deletion."
          confirmLabel="Delete"
          onConfirm={onConfirm}
        />,
      );

      const deleteBtn = screen.getByRole("button", { name: /delete/i });
      expect(deleteBtn).not.toBeDisabled();
      fireEvent.click(deleteBtn);
      expect(onConfirm).toHaveBeenCalledTimes(1);
    });

    it("Mode 2 (type-the-name) disables button until exact filename is typed", () => {
      const onConfirm = vi.fn();
      const onOpenChange = vi.fn();
      render(
        <DestructiveDialog
          open={true}
          onOpenChange={onOpenChange}
          title="Delete document?"
          description="Permanent document deletion."
          matchString="mlr_2017_amendments.pdf"
          confirmLabel="Delete document"
          onConfirm={onConfirm}
        />,
      );

      const deleteBtn = screen.getByRole("button", { name: /delete document/i });
      expect(deleteBtn).toBeDisabled();

      const input = screen.getByLabelText(/type mlr_2017_amendments.pdf to confirm/i);
      // Type partial or wrong string
      fireEvent.change(input, { target: { value: "mlr_2017" } });
      expect(deleteBtn).toBeDisabled();

      // Type exact string
      fireEvent.change(input, { target: { value: "mlr_2017_amendments.pdf" } });
      expect(deleteBtn).not.toBeDisabled();

      fireEvent.click(deleteBtn);
      expect(onConfirm).toHaveBeenCalledTimes(1);
    });
  });

  describe("Pattern 8: Reusable DataTable", () => {
    interface TestItem {
      id: string;
      name: string;
      score: number;
    }

    const testData: TestItem[] = [
      { id: "1", name: "Alpha", score: 85 },
      { id: "2", name: "Beta", score: 92 },
      { id: "3", name: "Gamma", score: 78 },
    ];

    const columns: ColumnDef<TestItem>[] = [
      { id: "name", header: "Name", accessorKey: "name", sortable: true },
      { id: "score", header: "Score", accessorKey: "score", sortable: true },
    ];

    it("renders data rows and supports sorting", () => {
      render(
        <DataTable
          data={testData}
          columns={columns}
          getRowId={(item) => item.id}
          pageSize={10}
        />,
      );

      const alphas = screen.getAllByText("Alpha");
      expect(alphas.length).toBeGreaterThan(0);

      // Click Name sort header
      const nameSortBtn = screen.getByRole("button", { name: /name/i });
      fireEvent.click(nameSortBtn);
      // Sorted asc: Alpha, Beta, Gamma
      const table = screen.getByRole("table");
      const rows = table.querySelectorAll("tbody tr");
      expect(rows[0].textContent).toContain("Alpha");

      // Click again for desc
      fireEvent.click(nameSortBtn);
      const rowsDesc = table.querySelectorAll("tbody tr");
      expect(rowsDesc[0].textContent).toContain("Gamma");
    });

    it("handles row selection and displays sticky bulk action bar", () => {
      render(
        <DataTable
          data={testData}
          columns={columns}
          getRowId={(item) => item.id}
          pageSize={10}
          bulkActions={(selectedIds) => (
            <button type="button">Export {selectedIds.length}</button>
          )}
        />,
      );

      // Select first row (pick the first matching checkbox)
      const firstCheckboxes = screen.getAllByLabelText("Select row 1");
      fireEvent.click(firstCheckboxes[0]);

      expect(screen.getByText(/item selected/i)).toBeInTheDocument();
      expect(screen.getByText("Export 1")).toBeInTheDocument();
    });
  });

  describe("Security Rule 3 & Pattern 1: ErrorState & Sanitized Diagnostics", () => {
    it("renders friendly human messages for 429, 503, and 403", () => {
      const { rerender } = render(<ErrorState statusCode={429} />);
      expect(screen.getByText("Rate Limit or Spend Cap Reached")).toBeInTheDocument();
      expect(screen.getByText(/allocated safety quota/i)).toBeInTheDocument();

      rerender(<ErrorState statusCode={503} />);
      expect(screen.getByText("Compliance Service Offline")).toBeInTheDocument();
      expect(screen.getByText(/backend server is active on localhost:8000/i)).toBeInTheDocument();

      rerender(<ErrorState statusCode={403} />);
      expect(screen.getByText("Access Restricted")).toBeInTheDocument();
      expect(screen.getByText(/authenticated security role does not have permission/i)).toBeInTheDocument();
    });

    it("Report an issue clipboard payload never contains query text, answers, or citations", async () => {
      let clipboardText = "";
      Object.assign(navigator, {
        clipboard: {
          writeText: vi.fn(async (text: string) => {
            clipboardText = text;
          }),
        },
      });

      render(<ErrorState statusCode={500} errorCode="INTERNAL_ERROR" />);
      const reportBtn = screen.getByRole("button", { name: /report an issue/i });
      fireEvent.click(reportBtn);

      expect(navigator.clipboard.writeText).toHaveBeenCalledTimes(1);
      expect(clipboardText).toContain("[Compliance RAG Error Report]");
      expect(clipboardText).toContain("Status: 500");
      expect(clipboardText).toContain("Code: INTERNAL_ERROR");
      // STRICT ASSERTION: Sensitive items must never be present
      expect(clipboardText).not.toContain("queryText");
      expect(clipboardText).not.toContain("answerText");
      expect(clipboardText).not.toContain("citations");
      expect(clipboardText).not.toContain("CANARY");
    });
  });

  describe("Pattern 9: Smart Validation on Blur / Change", () => {
    it("LoginScreen shows inline error with aria-describedby after blur on invalid username", () => {
      render(<LoginScreen health={null} />);
      const userInput = screen.getByLabelText(/username/i);

      // Initially pristine: no error
      expect(userInput).toHaveAttribute("aria-invalid", "false");
      expect(screen.queryByText(/at least 3 characters/i)).not.toBeInTheDocument();

      // Type 1 char and blur
      fireEvent.change(userInput, { target: { value: "a" } });
      fireEvent.blur(userInput);

      expect(userInput).toHaveAttribute("aria-invalid", "true");
      expect(userInput).toHaveAttribute("aria-describedby", "username-error");
      expect(screen.getByText(/username must be at least 3 characters/i)).toBeInTheDocument();
    });

    it("UploadDialog shows inline error with aria-describedby on empty title after blur", () => {
      render(<UploadDialog open={true} onOpenChange={vi.fn()} onUploaded={vi.fn()} />);
      const titleInput = screen.getByLabelText(/^title$/i);

      expect(titleInput).toHaveAttribute("aria-invalid", "false");

      // Blur with empty title
      fireEvent.change(titleInput, { target: { value: "" } });
      fireEvent.blur(titleInput);

      expect(titleInput).toHaveAttribute("aria-invalid", "true");
      expect(titleInput).toHaveAttribute("aria-describedby", "upload-title-error");
      expect(screen.getByText(/document title cannot be empty/i)).toBeInTheDocument();
    });
  });

  describe("Security Rule 4: Zero document exposure in Command Palette", () => {
    it("Command palette never includes or leaks document items", () => {
      render(
        <CommandPalette
          open={true}
          onOpenChange={vi.fn()}
          userRole="analyst"
        />,
      );

      // Command palette search input
      const input = screen.getByPlaceholderText(/type a command or search sessions/i);
      expect(input).toBeInTheDocument();

      // Search for regulatory or confidential document keywords
      fireEvent.change(input, { target: { value: "confidential" } });
      expect(screen.getByText(/no matching commands or sessions found/i)).toBeInTheDocument();
      expect(screen.queryByText(/audit report/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/restricted/i)).not.toBeInTheDocument();

      // The security footnote must be explicitly displayed
      expect(screen.getByText(/document content never indexed in palette/i)).toBeInTheDocument();
    });
  });
});
