"use client";

import * as React from "react";
import {
  AlertTriangle,
  ExternalLink,
  FileText,
  LockKeyhole,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  Upload,
} from "lucide-react";

import { UploadDialog } from "@/components/documents/upload-dialog";
import { PageHeader } from "@/components/workspace/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api-client";
import { canUploadDocuments, roleLabel } from "@/lib/auth";
import { safeHttpUrl } from "@/lib/citations";
import { formatDateTime, formatNumber } from "@/lib/format";
import type { DocumentItem, UserProfile } from "@/lib/types";
import { cn } from "@/lib/utils";

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-[var(--r-md)] border border-line bg-surface/55 p-3.5">
      <div className="text-[0.625rem] font-semibold uppercase tracking-[0.09em] text-faint">
        {label}
      </div>
      <div className="tabular mt-1 text-lg font-semibold tracking-[-0.02em] text-ink">{value}</div>
      {hint ? <div className="mt-0.5 text-[0.625rem] text-faint">{hint}</div> : null}
    </div>
  );
}

function TrustCell({ document }: { document: DocumentItem }) {
  const url = document.is_internal ? null : safeHttpUrl(document.source_url);
  if (document.is_internal) {
    return (
      <span className="inline-flex items-center gap-1 text-[0.6875rem] text-faint">
        <LockKeyhole className="size-3" aria-hidden="true" /> Internal only
      </span>
    );
  }
  if (url) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer nofollow"
        className="inline-flex items-center gap-1 text-[0.6875rem] font-medium text-accent underline-offset-2 hover:underline"
      >
        <ExternalLink className="size-3" aria-hidden="true" />
        {document.source_name ?? "Official source"}
      </a>
    );
  }
  return <span className="text-[0.6875rem] text-faint">No public link</span>;
}

function RoleBadges({ roles }: { roles: string[] }) {
  return (
    <span className="flex flex-wrap gap-1">
      {roles.map((role) => (
        <Badge key={role} tone={role === "auditor" ? "info" : role === "manager" ? "warning" : "neutral"}>
          {roleLabel(role)}
        </Badge>
      ))}
    </span>
  );
}

function hasDocumentAccess(document: DocumentItem, role: string): boolean {
  const allowed = document.allowed_roles.map((item) => item.trim().toLowerCase());
  if (allowed.length === 0) return true;
  return allowed.includes(role);
}

/** Red "unauthorized access" flag for a catalog row outside the caller's role. */
function AccessState({ document, role }: { document: DocumentItem; role: string }) {
  if (hasDocumentAccess(document, role)) return null;
  return (
    <span
      role="status"
      className="inline-flex items-center gap-1 rounded-full border border-[rgba(255,133,133,0.34)] bg-danger-soft px-2 py-0.5 text-[0.625rem] font-semibold text-danger"
    >
      <ShieldAlert className="size-3" aria-hidden="true" />
      Unauthorized access
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
  const canUpload = canUploadDocuments(role);
  const [documents, setDocuments] = React.useState(initialDocuments);
  const [query, setQuery] = React.useState("");
  const [typeFilter, setTypeFilter] = React.useState("all");
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [refreshing, setRefreshing] = React.useState(false);
  const [error, setError] = React.useState<string | null>(
    initialStatus >= 500 ? "The document catalog could not be loaded." : null,
  );

  const types = React.useMemo(
    () => Array.from(new Set(documents.map((document) => document.doc_type))).sort(),
    [documents],
  );

  const filtered = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    return documents
      .filter((document) => {
        if (typeFilter !== "all" && document.doc_type !== typeFilter) return false;
        if (!needle) return true;
        return [document.id, document.filename, document.source_jurisdiction, document.doc_type]
          .join(" ")
          .toLowerCase()
          .includes(needle);
      })
      .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
  }, [documents, query, typeFilter]);

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

  const totalChunks = documents.reduce((sum, document) => sum + (document.total_chunks || 0), 0);
  const internal = documents.filter((document) => document.is_internal).length;
  const visibleToRole = documents.filter((document) =>
    document.allowed_roles.map((item) => item.toLowerCase()).includes(role),
  ).length;

  return (
    <div>
      <PageHeader
        eyebrow="Corpus governance"
        title="Document catalog"
        description="Every indexed source, its jurisdiction and the roles authorised to retrieve it. Access is enforced inside the retrieval engine."
        actions={
          <>
            <Button variant="secondary" size="sm" onClick={() => void refresh()} disabled={refreshing}>
              <RefreshCw className={refreshing ? "animate-spin" : undefined} /> Refresh
            </Button>
            {canUpload ? (
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
              <p className="mt-0.5 text-[0.6875rem] text-muted">{error}</p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => void refresh()}>
              Try again
            </Button>
          </div>
        ) : null}

        <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
          <Stat label="Documents" value={formatNumber(documents.length)} hint="Visible after role filtering" />
          <Stat label="Indexed chunks" value={formatNumber(totalChunks)} hint="Across the catalog" />
          <Stat label="Internal sources" value={formatNumber(internal)} hint="No public verification link" />
          <Stat
            label="Readable by you"
            value={formatNumber(visibleToRole)}
            hint={`${roleLabel(role)} scope`}
          />
        </div>

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
          <span className="ml-auto text-[0.625rem] text-faint">
            {filtered.length} of {documents.length} shown
          </span>
        </div>

        {filtered.length === 0 ? (
          <div className="mt-6 rounded-[var(--r-lg)] border border-dashed border-line px-6 py-12 text-center">
            <FileText className="mx-auto mb-3 size-6 text-faint" aria-hidden="true" />
            <p className="text-sm font-medium text-ink-soft">
              {documents.length === 0 ? "No documents indexed yet" : "No documents match this filter"}
            </p>
            <p className="mx-auto mt-1 max-w-sm text-xs leading-relaxed text-muted">
              {documents.length === 0
                ? "Run the ingestion pipeline or upload a permitted document to populate the corpus."
                : "Adjust the search term or document type."}
            </p>
            {canUpload && documents.length === 0 ? (
              <Button variant="primary" size="sm" className="mt-4" onClick={() => setUploadOpen(true)}>
                <Upload /> Ingest the first document
              </Button>
            ) : null}
          </div>
        ) : (
          <>
            <div className="mt-4 hidden overflow-hidden rounded-[var(--r-lg)] border border-line md:block">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[820px] border-collapse text-left">
                  <thead>
                    <tr className="border-b border-line bg-surface-2/60">
                      {["Document", "Jurisdiction", "Type", "Version", "Read access", "Chunks", "Trust", "Added"].map(
                        (heading) => (
                          <th
                            key={heading}
                            scope="col"
                            className="px-3 py-2.5 text-[0.625rem] font-semibold uppercase tracking-[0.08em] text-faint"
                          >
                            {heading}
                          </th>
                        ),
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((document) => (
                      <tr
                        key={document.id}
                        className="border-b border-line/70 transition-colors last:border-0 hover:bg-surface-2/40"
                      >
                        <td className="max-w-64 px-3 py-2.5">
                          <div className="truncate text-xs font-medium text-ink">{document.filename}</div>
                          <div className="truncate font-mono text-[0.625rem] text-faint">{document.id}</div>
                        </td>
                        <td className="px-3 py-2.5 text-[0.6875rem] text-muted">
                          {document.source_jurisdiction}
                        </td>
                        <td className="px-3 py-2.5">
                          <Badge tone="outline">{document.doc_type}</Badge>
                        </td>
                        <td className="px-3 py-2.5 font-mono text-[0.6875rem] text-muted">
                          {document.version}
                        </td>
                        <td className="px-3 py-2.5">
                          <div className="flex flex-col items-start gap-1">
                            <RoleBadges roles={document.allowed_roles} />
                            <AccessState document={document} role={role} />
                          </div>
                        </td>
                        <td className="tabular px-3 py-2.5 text-[0.6875rem] text-muted">
                          {formatNumber(document.total_chunks)}
                        </td>
                        <td className="px-3 py-2.5">
                          <TrustCell document={document} />
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-[0.6875rem] text-faint">
                          {formatDateTime(document.created_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="mt-4 space-y-2 md:hidden">
              {filtered.map((document) => (
                <article key={document.id} className="rounded-[var(--r-md)] border border-line bg-surface/60 p-3.5">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h3 className="truncate text-xs font-semibold text-ink">{document.filename}</h3>
                      <p className="mt-0.5 font-mono text-[0.625rem] text-faint">{document.id}</p>
                    </div>
                    <Badge tone="outline">{document.doc_type}</Badge>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <RoleBadges roles={document.allowed_roles} />
                    <AccessState document={document} role={role} />
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-[0.6875rem]">
                    <div>
                      <span className="block text-[0.625rem] text-faint">Jurisdiction</span>
                      {document.source_jurisdiction}
                    </div>
                    <div>
                      <span className="block text-[0.625rem] text-faint">Chunks</span>
                      <span className="tabular">{formatNumber(document.total_chunks)}</span>
                    </div>
                    <div>
                      <span className="block text-[0.625rem] text-faint">Version</span>
                      {document.version}
                    </div>
                    <div>
                      <span className="block text-[0.625rem] text-faint">Added</span>
                      {formatDateTime(document.created_at)}
                    </div>
                  </div>
                  <div className={cn("mt-2 border-t border-line pt-2")}>
                    <TrustCell document={document} />
                  </div>
                </article>
              ))}
            </div>
          </>
        )}

        <div className="mt-5 flex items-start gap-2 rounded-[var(--r-md)] border border-line bg-surface/40 px-3.5 py-3">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden="true" />
          <p className="text-[0.6875rem] leading-relaxed text-muted">
            This catalog is already filtered by the API for your role. The role chips describe who may
            retrieve each source; they are not a UI switch. Official links come only from trusted
            document metadata, never from a model-generated URL.
          </p>
        </div>
      </div>

      {canUpload ? (
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
