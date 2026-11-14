"use client";

import * as React from "react";
import {
  AlertTriangle,
  Check,
  Download,
  ExternalLink,
  FileText,
  LockKeyhole,
  Pencil,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  Upload,
} from "lucide-react";
import { toast } from "sonner";

import { UploadDialog } from "@/components/documents/upload-dialog";
import { PageHeader } from "@/components/workspace/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DestructiveDialog } from "@/components/ui/destructive-dialog";
import { ColumnDef, DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api-client";
import { canUploadDocuments, roleLabel } from "@/lib/auth";
import { safeHttpUrl } from "@/lib/citations";
import { formatDateTime, formatNumber } from "@/lib/format";
import { useDebouncedCallback, useDebouncedValue } from "@/lib/hooks/use-debounce";
import type { DocumentItem, UserProfile } from "@/lib/types";
import { cn } from "@/lib/utils";

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-[var(--r-md)] border border-line bg-surface/55 p-3.5">
      <div className="text-xs font-semibold uppercase tracking-[0.09em] text-faint">
        {label}
      </div>
      <div className="tabular mt-1 text-lg font-semibold tracking-[-0.02em] text-ink">{value}</div>
      {hint ? <div className="mt-0.5 text-xs text-faint">{hint}</div> : null}
    </div>
  );
}

function TrustCell({ document }: { document: DocumentItem }) {
  const url = document.is_internal ? null : safeHttpUrl(document.source_url);
  if (document.is_internal) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-warning/30 bg-warning-soft px-2 py-0.5 text-[11px] font-medium text-warning">
        <LockKeyhole className="size-3" aria-hidden="true" />
        Restricted to Manager, Auditor
      </span>
    );
  }
  if (url) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer nofollow"
        className="inline-flex items-center gap-1 text-xs font-medium text-accent underline-offset-2 hover:underline"
      >
        <ExternalLink className="size-3" aria-hidden="true" />
        {document.source_name ?? "Official source"}
      </a>
    );
  }
  return <span className="text-xs text-faint">No public link</span>;
}

function RoleBadges({ roles }: { roles: string[] }) {
  return (
    <span className="flex flex-wrap gap-1">
      {roles.map((role) => (
        <Badge
          key={role}
          tone={role === "auditor" ? "info" : role === "manager" ? "warning" : "neutral"}
        >
          {roleLabel(role)}
        </Badge>
      ))}
    </span>
  );
}

export function DocumentsView({
  user,
  initialDocuments,
  initialStatus,
}: {
  user: UserProfile;
  initialDocuments: DocumentItem[];
  initialStatus: number;
}) {
  const role = String(user.role ?? "").toLowerCase();
  const canManage = canUploadDocuments(role);
  const [documents, setDocuments] = React.useState(initialDocuments);
  const [query, setQuery] = React.useState("");
  const debouncedQuery = useDebouncedValue(query, 250);
  const [typeFilter, setTypeFilter] = React.useState("all");
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [refreshing, setRefreshing] = React.useState(false);
  const [error, setError] = React.useState<string | null>(
    initialStatus >= 500 ? "The document catalog could not be loaded." : null,
  );

  // Inline editing / autosave state: docId -> { title, savingState: "idle" | "saving" | "saved" | "error" }
  const [editStates, setEditStates] = React.useState<
    Record<string, { title: string; isEditing: boolean; status: "idle" | "saving" | "saved" | "error" }>
  >({});

  // Destructive delete dialog state
  const [docToDelete, setDocToDelete] = React.useState<DocumentItem | null>(null);
  const [isDeleting, setIsDeleting] = React.useState(false);

  const types = React.useMemo(
    () => Array.from(new Set(documents.map((document) => document.doc_type))).sort(),
    [documents],
  );

  const filtered = React.useMemo(() => {
    const needle = debouncedQuery.trim().toLowerCase();
    return documents
      .filter((document) => {
        if (typeFilter !== "all" && document.doc_type !== typeFilter) return false;
        if (!needle) return true;
        const currentTitle = editStates[document.id]?.title ?? document.filename;
        return [document.id, currentTitle, document.source_jurisdiction, document.doc_type]
          .join(" ")
          .toLowerCase()
          .includes(needle);
      })
      .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
  }, [documents, debouncedQuery, typeFilter, editStates]);

  async function refresh() {
    setRefreshing(true);
    setError(null);
    try {
      setDocuments(await api.listDocuments());
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The catalog could not be refreshed.");
    } finally {
      setRefreshing(false);
    }
  }

  // Autosave routine for document title
  const performAutosave = useDebouncedCallback(async (docId: string, newTitle: string) => {
    const trimmed = newTitle.trim();
    if (!trimmed) return;

    setEditStates((prev) => ({
      ...prev,
      [docId]: { ...(prev[docId] ?? { title: trimmed, isEditing: false }), status: "saving" },
    }));

    try {
      await api.updateDocument(docId, { title: trimmed });
      setDocuments((prev) =>
        prev.map((doc) => (doc.id === docId ? { ...doc, filename: trimmed } : doc)),
      );
      setEditStates((prev) => ({
        ...prev,
        [docId]: { ...(prev[docId] ?? { title: trimmed, isEditing: false }), status: "saved" },
      }));
      setTimeout(() => {
        setEditStates((prev) => ({
          ...prev,
          [docId]: { ...(prev[docId] ?? { title: trimmed, isEditing: false }), status: "idle" },
        }));
      }, 2500);
    } catch {
      setEditStates((prev) => ({
        ...prev,
        [docId]: { ...(prev[docId] ?? { title: trimmed, isEditing: false }), status: "error" },
      }));
      toast.error("Failed to autosave document title");
    }
  }, 600);

  function handleTitleChange(doc: DocumentItem, value: string) {
    setEditStates((prev) => ({
      ...prev,
      [doc.id]: {
        title: value,
        isEditing: true,
        status: "saving",
      },
    }));
    performAutosave(doc.id, value);
  }

  async function handleDeleteDocument() {
    if (!docToDelete) return;
    setIsDeleting(true);
    try {
      await api.deleteDocument(docToDelete.id);
      setDocuments((prev) => prev.filter((d) => d.id !== docToDelete.id));
      toast.success(`Document "${docToDelete.filename}" deleted successfully.`);
      setDocToDelete(null);
    } catch (err) {
      toast.error("Failed to delete document", {
        description: err instanceof ApiError ? err.message : "Internal API error",
      });
    } finally {
      setIsDeleting(false);
    }
  }

  // Stats scoped strictly to user's permitted documents
  const totalChunks = documents.reduce((sum, document) => sum + (document.total_chunks || 0), 0);
  const internal = documents.filter((document) => document.is_internal).length;

  // DataTable column definitions
  const columns: ColumnDef<DocumentItem>[] = React.useMemo(() => {
    const cols: ColumnDef<DocumentItem>[] = [
      {
        id: "filename",
        header: "Document",
        sortable: true,
        accessorKey: "filename",
        className: "max-w-72",
        cell: (doc) => {
          const editState = editStates[doc.id];
          const title = editState?.title ?? doc.filename;
          const status = editState?.status ?? "idle";

          if (canManage) {
            return (
              <div className="space-y-1">
                <div className="flex items-center gap-1.5">
                  <Input
                    value={title}
                    onChange={(e) => handleTitleChange(doc, e.target.value)}
                    className="h-7 text-xs font-medium py-1 px-2 text-ink bg-surface-2/40 border-line hover:border-line-strong focus:border-line-accent"
                    aria-label={`Edit title for ${doc.id}`}
                  />
                  {status === "saving" && (
                    <span className="text-[10px] text-faint animate-pulse">Saving…</span>
                  )}
                  {status === "saved" && (
                    <span className="inline-flex items-center gap-0.5 text-[10px] text-success">
                      <Check className="size-3" /> Saved
                    </span>
                  )}
                  {status === "error" && (
                    <span className="text-[10px] text-danger">Error</span>
                  )}
                </div>
                <div className="truncate font-mono text-[11px] text-faint px-0.5">{doc.id}</div>
              </div>
            );
          }

          return (
            <div>
              <div className="truncate text-xs font-medium text-ink">{doc.filename}</div>
              <div className="truncate font-mono text-[11px] text-faint">{doc.id}</div>
            </div>
          );
        },
      },
      {
        id: "source_jurisdiction",
        header: "Jurisdiction",
        sortable: true,
        accessorKey: "source_jurisdiction",
        cell: (doc) => <span className="text-muted">{doc.source_jurisdiction}</span>,
      },
      {
        id: "doc_type",
        header: "Type",
        sortable: true,
        accessorKey: "doc_type",
        cell: (doc) => <Badge tone="outline">{doc.doc_type}</Badge>,
      },
      {
        id: "version",
        header: "Version",
        sortable: true,
        accessorKey: "version",
        cell: (doc) => <span className="font-mono text-muted">{doc.version}</span>,
      },
      {
        id: "allowed_roles",
        header: "Read Access",
        cell: (doc) => <RoleBadges roles={doc.allowed_roles} />,
      },
      {
        id: "total_chunks",
        header: "Chunks",
        sortable: true,
        accessorKey: "total_chunks",
        cell: (doc) => <span className="tabular text-muted">{formatNumber(doc.total_chunks)}</span>,
      },
      {
        id: "trust",
        header: "Trust",
        cell: (doc) => <TrustCell document={doc} />,
      },
      {
        id: "created_at",
        header: "Added",
        sortable: true,
        accessorKey: "created_at",
        cell: (doc) => (
          <span className="whitespace-nowrap text-faint">
            {formatDateTime(doc.created_at)}
          </span>
        ),
      },
    ];

    if (canManage) {
      cols.push({
        id: "actions",
        header: "Actions",
        cell: (doc) => (
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setDocToDelete(doc)}
            aria-label={`Delete ${doc.filename}`}
            className="text-faint hover:text-danger hover:bg-danger-soft/30"
          >
            <Trash2 className="size-3.5" />
          </Button>
        ),
      });
    }

    return cols;
  }, [editStates, canManage]);

  return (
    <div>
      <PageHeader
        eyebrow="Corpus governance"
        title="Document catalog"
        description="Every indexed source permitted for your role. Role access is strictly verified server-side at the vector and lexical index layers."
        role={role}
        actions={
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void refresh()}
              disabled={refreshing}
            >
              <RefreshCw className={refreshing ? "animate-spin" : undefined} /> Refresh
            </Button>
            {canManage ? (
              <Button variant="primary" size="sm" onClick={() => setUploadOpen(true)}>
                <Upload /> Ingest document
              </Button>
            ) : (
              <Badge tone="outline">
                <LockKeyhole /> Upload requires Manager or Auditor
              </Badge>
            )}
          </>
        }
      />

      <div className="px-4 py-5 sm:px-6 lg:px-10">
        {error ? (
          <div
            role="alert"
            className="mb-4 flex items-start gap-2 rounded-[var(--r-md)] border border-[rgba(255,133,133,0.28)] bg-danger-soft px-3.5 py-3 text-xs text-danger"
          >
            <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <div className="flex-1">
              <p className="font-medium text-ink">Catalog unavailable</p>
              <p className="mt-0.5 text-xs text-muted">{error}</p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => void refresh()}>
              Try again
            </Button>
          </div>
        ) : null}

        {/* Stats Grid: zero leak of documents outside caller's role */}
        <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
          <Stat
            label="Permitted Documents"
            value={formatNumber(documents.length)}
            hint="Authorized for your role"
          />
          <Stat
            label="Indexed Chunks"
            value={formatNumber(totalChunks)}
            hint="In your retrieval scope"
          />
          <Stat
            label="Internal Sources"
            value={formatNumber(internal)}
            hint="Internal regulatory SOPs"
          />
          <Stat
            label="Current Scope"
            value={roleLabel(role)}
            hint="Enforced server-side"
          />
        </div>

        {/* Filters bar */}
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <div className="relative min-w-52 flex-1 sm:max-w-xs">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-faint"
              aria-hidden="true"
            />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search by title, ID or jurisdiction"
              aria-label="Search documents"
              className="h-9 pl-8 text-xs"
            />
          </div>
          <label className="sr-only" htmlFor="doc-type-filter">
            Filter by document type
          </label>
          <select
            id="doc-type-filter"
            value={typeFilter}
            onChange={(event) => setTypeFilter(event.target.value)}
            className="h-9 rounded-[var(--r-sm)] border border-line bg-[rgba(3,6,10,0.44)] px-2.5 text-xs text-ink outline-none focus:border-line-accent"
          >
            <option value="all">All types</option>
            {types.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </div>

        {/* Reusable DataTable with sorting, column toggle, bulk export, pagination */}
        <div className="mt-4">
          <DataTable<DocumentItem>
            data={filtered}
            columns={columns}
            getRowId={(doc) => doc.id}
            pageSize={10}
            emptyState={
              <div className="py-8 text-center">
                <FileText className="mx-auto mb-2 size-6 text-faint" aria-hidden="true" />
                <p className="text-xs font-medium text-ink">No matching documents found</p>
                <p className="mt-1 text-xs text-muted">Try adjusting your search query or filters.</p>
              </div>
            }
            bulkActions={(selectedIds, clearSelection) => (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  const selectedDocs = documents.filter((d) => selectedIds.includes(d.id));
                  const blob = new Blob([JSON.stringify(selectedDocs, null, 2)], {
                    type: "application/json",
                  });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `documents-export-${Date.now()}.json`;
                  a.click();
                  URL.revokeObjectURL(url);
                  toast.success(`Exported ${selectedIds.length} document metadata records.`);
                  clearSelection();
                }}
              >
                <Download className="size-3.5" aria-hidden="true" /> Export JSON
              </Button>
            )}
          />
        </div>

        <div className="mt-5 flex items-start gap-2 rounded-[var(--r-md)] border border-line bg-surface/40 px-3.5 py-3">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden="true" />
          <p className="text-xs leading-relaxed text-muted">
            Corpus RBAC is enforced strictly at the database and index level. Any document outside
            your role is filtered before similarity ranking and never reaches client context.
          </p>
        </div>
      </div>

      {/* Mode 2 "Type-the-name" Destructive Confirmation Dialog */}
      {docToDelete ? (
        <DestructiveDialog
          open={Boolean(docToDelete)}
          onOpenChange={(open) => !open && setDocToDelete(null)}
          title="Delete document permanently?"
          description={`Deleting "${docToDelete.filename}" will remove its metadata, chunk records, and embeddings from Qdrant and BM25 indices. This cannot be undone.`}
          confirmLabel="Delete document"
          matchString={docToDelete.filename}
          onConfirm={handleDeleteDocument}
          isLoading={isDeleting}
        />
      ) : null}

      {canManage ? (
        <UploadDialog
          open={uploadOpen}
          onOpenChange={setUploadOpen}
          onUploaded={() => {
            void refresh();
          }}
        />
      ) : null}
    </div>
  );
}
