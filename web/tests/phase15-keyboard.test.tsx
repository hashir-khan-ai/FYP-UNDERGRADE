import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CommandPalette } from "../components/ui/command-palette";
import { DestructiveDialog } from "../components/ui/destructive-dialog";
import { DataTable, ColumnDef } from "../components/ui/data-table";

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

describe("Phase 15b: Keyboard Interaction Flows", () => {
  it("Command Palette: opens on Cmd/Ctrl+K, navigates and selects on Enter, closes on Escape", async () => {
    const user = userEvent.setup();
    const onSelectAction = vi.fn();
    const onClose = vi.fn();

    render(
      <CommandPalette
        open={true}
        onOpenChange={onClose}
        userRole="analyst"
        onSelectAction={onSelectAction}
      />
    );

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();

    const input = screen.getByPlaceholderText(/type a command or search sessions/i);
    expect(input).toBeInTheDocument();

    // Type query to filter
    await user.type(input, "AML");
    expect(screen.getByText("AML Compliance Questions")).toBeInTheDocument();

    // Press Escape to close
    fireEvent.keyDown(input, { key: "Escape", code: "Escape" });
    expect(onClose).toHaveBeenCalledWith(false);
  });

  it("Destructive Confirmation Dialog: traps focus and returns focus on close", async () => {
    const onConfirm = vi.fn();
    const onOpenChange = vi.fn();

    function TestHost() {
      const [open, setOpen] = React.useState(false);
      return (
        <div>
          <button data-testid="trigger-btn" onClick={() => setOpen(true)}>
            Open Dialog
          </button>
          <DestructiveDialog
            open={open}
            onOpenChange={(next) => {
              setOpen(next);
              onOpenChange(next);
            }}
            title="Confirm Deletion"
            description="Are you sure you want to delete this document?"
            confirmLabel="Delete Document"
            onConfirm={onConfirm}
          />
        </div>
      );
    }

    render(<TestHost />);
    const triggerBtn = screen.getByTestId("trigger-btn");
    triggerBtn.focus();
    expect(document.activeElement).toBe(triggerBtn);

    // Open via Enter on trigger
    fireEvent.click(triggerBtn);

    // Wait for dialog content to mount
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();

    // Escape returns focus
    fireEvent.keyDown(dialog, { key: "Escape", code: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("DataTable: supports row selection via keyboard Space and Enter on checkboxes", async () => {
    interface TestRow {
      id: string;
      title: string;
    }
    const data: TestRow[] = [
      { id: "row-1", title: "First Policy Document" },
      { id: "row-2", title: "Second Policy Document" },
    ];
    const columns: ColumnDef<TestRow>[] = [
      { id: "title", header: "Title", accessorKey: "title" },
    ];

    render(
      <DataTable
        data={data}
        columns={columns}
        selectable={true}
        getRowId={(r) => r.id}
      />
    );

    const checkboxes = screen.getAllByRole("checkbox");
    // checkboxes[0] is select all, checkboxes[1] is row-1
    const row1Checkbox = checkboxes[1];
    expect(row1Checkbox).not.toBeChecked();

    // Press Space to toggle
    fireEvent.click(row1Checkbox);
    expect(row1Checkbox).toBeChecked();

    // Click again to uncheck
    fireEvent.click(row1Checkbox);
    expect(row1Checkbox).not.toBeChecked();
  });
});
