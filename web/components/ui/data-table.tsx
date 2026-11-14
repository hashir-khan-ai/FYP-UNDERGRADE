"use client";

import * as React from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Columns3,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

export interface ColumnDef<T> {
  id: string;
  header: string;
  cell?: (row: T) => React.ReactNode;
  accessorKey?: keyof T;
  sortable?: boolean;
  defaultHidden?: boolean;
  className?: string;
  cardRender?: (row: T) => React.ReactNode;
}

export interface DataTableProps<T> {
  data: T[];
  columns: ColumnDef<T>[];
  getRowId: (row: T) => string;
  emptyState?: React.ReactNode;
  bulkActions?: (selectedIds: string[], clearSelection: () => void) => React.ReactNode;
  pageSize?: number;
  className?: string;
}

export function DataTable<T>({
  data,
  columns,
  getRowId,
  emptyState,
  bulkActions,
  pageSize: initialPageSize = 10,
  className,
}: DataTableProps<T>) {
  const [sortColumn, setSortColumn] = React.useState<string | null>(null);
  const [sortDirection, setSortDirection] = React.useState<"asc" | "desc">("asc");
  const [pageSize, setPageSize] = React.useState(initialPageSize);
  const [currentPage, setCurrentPage] = React.useState(1);
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set());
  const [visibleColumns, setVisibleColumns] = React.useState<Set<string>>(() => {
    return new Set(columns.filter((c) => !c.defaultHidden).map((c) => c.id));
  });

  // Sorting
  const sortedData = React.useMemo(() => {
    if (!sortColumn) return data;
    const col = columns.find((c) => c.id === sortColumn);
    if (!col) return data;

    return [...data].sort((a: any, b: any) => {
      const aVal = col.accessorKey ? a[col.accessorKey] : a[col.id];
      const bVal = col.accessorKey ? b[col.accessorKey] : b[col.id];

      if (aVal === bVal) return 0;
      if (aVal === undefined || aVal === null) return 1;
      if (bVal === undefined || bVal === null) return -1;

      const compare = String(aVal).localeCompare(String(bVal), undefined, { numeric: true });
      return sortDirection === "asc" ? compare : -compare;
    });
  }, [data, sortColumn, sortDirection, columns]);

  // Pagination
  const totalPages = Math.max(1, Math.ceil(sortedData.length / pageSize));
  const paginatedData = React.useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return sortedData.slice(start, start + pageSize);
  }, [sortedData, currentPage, pageSize]);

  // Adjust current page if data shrinks
  React.useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [totalPages, currentPage]);

  const activeColumns = columns.filter((c) => visibleColumns.has(c.id));

  // Selection
  const allCurrentPageSelected =
    paginatedData.length > 0 &&
    paginatedData.every((row) => selectedIds.has(getRowId(row)));

  function toggleSelectAll() {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allCurrentPageSelected) {
        paginatedData.forEach((row) => next.delete(getRowId(row)));
      } else {
        paginatedData.forEach((row) => next.add(getRowId(row)));
      }
      return next;
    });
  }

  function toggleRow(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function clearSelection() {
    setSelectedIds(new Set());
  }

  function handleSort(columnId: string) {
    if (sortColumn === columnId) {
      if (sortDirection === "asc") {
        setSortDirection("desc");
      } else {
        setSortColumn(null);
        setSortDirection("asc");
      }
    } else {
      setSortColumn(columnId);
      setSortDirection("asc");
    }
  }

  return (
    <div className={cn("space-y-3", className)}>
      {/* Table Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs text-faint">
          Showing <span className="tabular font-medium text-ink">{paginatedData.length}</span> of{" "}
          <span className="tabular font-medium text-ink">{data.length}</span> entries
        </div>

        <div className="flex items-center gap-2">
          {/* Column Visibility */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="secondary" size="sm" aria-label="Toggle visible columns">
                <Columns3 className="size-3.5" aria-hidden="true" /> Columns
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
              <DropdownMenuLabel>Toggle columns</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {columns.map((col) => (
                <DropdownMenuCheckboxItem
                  key={col.id}
                  checked={visibleColumns.has(col.id)}
                  onCheckedChange={(checked: boolean) => {
                    setVisibleColumns((prev) => {
                      const next = new Set(prev);
                      if (checked) {
                        next.add(col.id);
                      } else {
                        if (next.size > 1) next.delete(col.id);
                      }
                      return next;
                    });
                  }}
                >
                  {col.header}
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Rows Per Page */}
          <label className="sr-only" htmlFor="page-size-select">
            Rows per page
          </label>
          <select
            id="page-size-select"
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setCurrentPage(1);
            }}
            className="h-8 rounded-[var(--r-sm)] border border-line bg-surface px-2 text-xs text-ink outline-none focus:border-line-accent"
          >
            <option value={10}>10 / page</option>
            <option value={25}>25 / page</option>
            <option value={50}>50 / page</option>
          </select>
        </div>
      </div>

      {/* Desktop / Tablet Table View */}
      <div className="hidden md:block overflow-hidden rounded-[var(--r-md)] border border-line bg-surface/50">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-xs">
            <thead>
              <tr className="border-b border-line bg-surface-2/60">
                <th scope="col" className="w-10 px-3 py-2.5">
                  <input
                    type="checkbox"
                    checked={allCurrentPageSelected}
                    onChange={toggleSelectAll}
                    aria-label="Select all rows on this page"
                    className="size-4 rounded border-line text-accent focus:ring-accent"
                  />
                </th>
                {activeColumns.map((col) => {
                  const isSorted = sortColumn === col.id;
                  const ariaSort = isSorted
                    ? sortDirection === "asc"
                      ? "ascending"
                      : "descending"
                    : "none";

                  return (
                    <th
                      key={col.id}
                      scope="col"
                      aria-sort={col.sortable ? ariaSort : undefined}
                      className={cn(
                        "px-3 py-2.5 font-semibold uppercase tracking-[0.08em] text-faint",
                        col.className,
                      )}
                    >
                      {col.sortable ? (
                        <button
                          type="button"
                          onClick={() => handleSort(col.id)}
                          className="group inline-flex items-center gap-1.5 hover:text-ink focus:outline-none"
                        >
                          <span>{col.header}</span>
                          {isSorted ? (
                            sortDirection === "asc" ? (
                              <ArrowUp className="size-3 text-accent" aria-hidden="true" />
                            ) : (
                              <ArrowDown className="size-3 text-accent" aria-hidden="true" />
                            )
                          ) : (
                            <ArrowUpDown
                              className="size-3 text-faint opacity-0 group-hover:opacity-100"
                              aria-hidden="true"
                            />
                          )}
                        </button>
                      ) : (
                        col.header
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {paginatedData.length === 0 ? (
                <tr>
                  <td colSpan={activeColumns.length + 1} className="py-8 text-center text-muted">
                    {emptyState ?? "No items found."}
                  </td>
                </tr>
              ) : (
                paginatedData.map((row) => {
                  const id = getRowId(row);
                  const isSelected = selectedIds.has(id);

                  return (
                    <tr
                      key={id}
                      className={cn(
                        "border-b border-line/60 transition-colors last:border-0 hover:bg-surface-2/40",
                        isSelected && "bg-accent/5",
                      )}
                    >
                      <td className="w-10 px-3 py-2.5">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleRow(id)}
                          aria-label={`Select row ${id}`}
                          className="size-4 rounded border-line text-accent focus:ring-accent"
                        />
                      </td>
                      {activeColumns.map((col) => {
                        const cellContent = col.cell
                          ? col.cell(row)
                          : col.accessorKey
                            ? String((row as any)[col.accessorKey] ?? "")
                            : null;
                        return (
                          <td key={col.id} className={cn("px-3 py-2.5", col.className)}>
                            {cellContent}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Mobile Card View (< 768px) */}
      <div className="space-y-2 md:hidden">
        {paginatedData.length === 0 ? (
          <div className="rounded-[var(--r-md)] border border-dashed border-line p-6 text-center text-xs text-muted">
            {emptyState ?? "No items found."}
          </div>
        ) : (
          paginatedData.map((row) => {
            const id = getRowId(row);
            const isSelected = selectedIds.has(id);

            return (
              <div
                key={id}
                className={cn(
                  "rounded-[var(--r-md)] border border-line bg-surface/60 p-3 space-y-2 text-xs",
                  isSelected && "border-accent/40 bg-accent/5",
                )}
              >
                <div className="flex items-center justify-between border-b border-line/50 pb-2">
                  <label className="flex items-center gap-2 font-mono text-[11px] text-faint">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleRow(id)}
                      aria-label={`Select row ${id}`}
                      className="size-4 rounded border-line text-accent focus:ring-accent"
                    />
                    <span>{id.slice(0, 10)}</span>
                  </label>
                </div>
                {activeColumns.map((col) => {
                  const content = col.cardRender
                    ? col.cardRender(row)
                    : col.cell
                      ? col.cell(row)
                      : col.accessorKey
                        ? String((row as any)[col.accessorKey] ?? "")
                        : null;
                  return (
                    <div key={col.id} className="flex items-start justify-between gap-2">
                      <span className="font-semibold uppercase tracking-wider text-[10px] text-faint">
                        {col.header}
                      </span>
                      <div className="text-right text-ink">{content}</div>
                    </div>
                  );
                })}
              </div>
            );
          })
        )}
      </div>

      {/* Pagination Controls */}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-xs">
        <span className="text-faint">
          Page <span className="tabular font-medium text-ink">{currentPage}</span> of{" "}
          <span className="tabular font-medium text-ink">{totalPages}</span>
        </span>

        <div className="flex items-center gap-1.5">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
            disabled={currentPage <= 1}
            aria-label="Previous page"
          >
            <ChevronLeft className="size-3.5" aria-hidden="true" /> Previous
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
            disabled={currentPage >= totalPages}
            aria-label="Next page"
          >
            Next <ChevronRight className="size-3.5" aria-hidden="true" />
          </Button>
        </div>
      </div>

      {/* Sticky Bulk Action Bar */}
      {selectedIds.size > 0 && bulkActions ? (
        <div
          role="region"
          aria-label="Bulk actions"
          className="sticky bottom-4 z-20 flex items-center justify-between gap-3 rounded-[var(--r-md)] border border-line-accent bg-canvas-raised p-3 shadow-xl backdrop-blur-md"
        >
          <div aria-live="polite" className="flex items-center gap-2 text-xs font-medium text-ink">
            <span className="tabular flex size-5 items-center justify-center rounded-full bg-accent text-[11px] font-bold text-accent-ink">
              {selectedIds.size}
            </span>
            <span>{selectedIds.size === 1 ? "item" : "items"} selected</span>
          </div>

          <div className="flex items-center gap-2">
            {bulkActions(Array.from(selectedIds), clearSelection)}
            <Button
              variant="ghost"
              size="sm"
              onClick={clearSelection}
              aria-label="Clear selection"
            >
              <X className="size-3.5" aria-hidden="true" /> Deselect
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
