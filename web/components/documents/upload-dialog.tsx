"use client";

import * as React from "react";
import { AlertTriangle, CheckCircle2, FileUp, LoaderCircle } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { ApiError, api } from "@/lib/api-client";
import { roleLabel } from "@/lib/auth";
import { ACCEPTED_UPLOAD_EXTENSIONS, DOCUMENT_TYPES, UPLOAD_ROLES } from "@/lib/constants";
import type { DocumentUploadResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

type Stage = "idle" | "uploading" | "indexing" | "done";

export function UploadDialog({
  open,
  onOpenChange,
  onUploaded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUploaded: () => void;
}) {
  const [file, setFile] = React.useState<File | null>(null);
  const [title, setTitle] = React.useState("");
  const [docId, setDocId] = React.useState("");
  const [docType, setDocType] = React.useState<string>("policy");
  const [roles, setRoles] = React.useState<string[]>(["manager", "auditor"]);
  const [titleTouched, setTitleTouched] = React.useState(false);
  const [rolesTouched, setRolesTouched] = React.useState(false);
  const [stage, setStage] = React.useState<Stage>("idle");
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<DocumentUploadResponse | null>(null);
  const [dragging, setDragging] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const timerRef = React.useRef<number | null>(null);

  const titleError = titleTouched && !title.trim() ? "Document title cannot be empty." : null;
  const rolesError =
    rolesTouched && roles.length === 0 ? "Select at least one permitted role." : null;

  React.useEffect(() => {
    if (!open) {
      if (timerRef.current) window.clearInterval(timerRef.current);
      timerRef.current = null;
      setFile(null);
      setTitle("");
      setDocId("");
      setDocType("policy");
      setRoles(["manager", "auditor"]);
      setStage("idle");
      setError(null);
      setResult(null);
      setDragging(false);
    }
  }, [open]);

  React.useEffect(
    () => () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    },
    [],
  );

  function acceptFile(candidate: File | null | undefined) {
    if (!candidate) return;
    const extension = candidate.name.split(".").pop()?.toLowerCase() ?? "";
    if (!["pdf", "txt", "md", "docx"].includes(extension)) {
      setError("Use a PDF, TXT, Markdown or DOCX file.");
      return;
    }
    if (candidate.size > 20 * 1024 * 1024) {
      setError("The file must be 20 MB or smaller.");
      return;
    }
    setError(null);
    setFile(candidate);
    if (!title) setTitle(candidate.name.replace(/\.[^.]+$/, "").replaceAll("_", " "));
  }

  async function submit() {
    if (!file) {
      setError("Choose a document to index.");
      return;
    }
    if (roles.length === 0) {
      setError("Select at least one role that may read this document.");
      return;
    }

    setError(null);
    setStage("uploading");
    timerRef.current = window.setInterval(() => {
      setStage((current) => (current === "uploading" ? "indexing" : current));
    }, 850);

    try {
      const response = await api.uploadDocument({
        file,
        allowedRoles: roles,
        title: title.trim() || undefined,
        docId: docId.trim() || undefined,
        docType,
      });
      if (timerRef.current) window.clearInterval(timerRef.current);
      timerRef.current = null;
      setStage("done");
      setResult(response);
      onUploaded();
      toast.success("Document indexed", {
        description: `${response.chunks_indexed} chunks added · ${response.doc_id}`,
      });
    } catch (caught) {
      if (timerRef.current) window.clearInterval(timerRef.current);
      timerRef.current = null;
      setStage("idle");
      setError(
        caught instanceof ApiError ? caught.message : "The document could not be indexed.",
      );
    }
  }

  const busy = stage === "uploading" || stage === "indexing";

  return (
    <Dialog open={open} onOpenChange={(next) => (busy ? undefined : onOpenChange(next))}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Ingest a regulatory document</DialogTitle>
          <DialogDescription>
            The document is chunked, embedded and indexed locally. Only the roles you select can
            retrieve it — enforced inside Qdrant and BM25, not in this dialog.
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-4 pb-3">
          {stage === "done" && result ? (
            <div className="rounded-[var(--r-md)] border border-[rgba(86,217,155,0.28)] bg-success-soft p-4">
              <div className="flex items-start gap-2.5">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-hidden="true" />
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-ink">Indexed successfully</p>
                  <p className="mt-1 text-xs leading-relaxed text-muted">
                    {result.title} · {result.chunks_indexed} chunks · {result.doc_id}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {result.allowed_roles.map((role) => (
                      <Badge key={role} tone="outline">
                        {roleLabel(role)}
                      </Badge>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <>
              <div>
                <Label htmlFor="upload-file">Document file</Label>
                <div
                  onDragOver={(event) => {
                    event.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(event) => {
                    event.preventDefault();
                    setDragging(false);
                    acceptFile(event.dataTransfer.files?.[0]);
                  }}
                  className={cn(
                    "mt-1.5 flex flex-col items-center justify-center rounded-[var(--r-md)] border border-dashed px-4 py-6 text-center transition-colors",
                    dragging
                      ? "border-line-accent bg-accent-soft"
                      : "border-line-strong bg-[rgba(3,6,10,0.3)] hover:border-line-accent",
                  )}
                >
                  <input
                    ref={inputRef}
                    id="upload-file"
                    type="file"
                    accept={ACCEPTED_UPLOAD_EXTENSIONS}
                    className="sr-only"
                    onChange={(event) => acceptFile(event.target.files?.[0])}
                    disabled={busy}
                  />
                  <FileUp className="mb-2 size-5 text-faint" aria-hidden="true" />
                  <p className="text-xs font-medium text-ink-soft">
                    {file ? file.name : "Drop a file here or choose one"}
                  </p>
                  <p className="mt-1 text-xs text-faint">
                    PDF, TXT, MD or DOCX · up to 20 MB
                  </p>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="mt-2.5"
                    onClick={() => inputRef.current?.click()}
                    disabled={busy}
                  >
                    {file ? "Choose a different file" : "Choose file"}
                  </Button>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <Label htmlFor="upload-title">Title</Label>
                  <Input
                    id="upload-title"
                    value={title}
                    onChange={(event) => {
                      setTitle(event.target.value);
                      setTitleTouched(true);
                    }}
                    onBlur={() => setTitleTouched(true)}
                    maxLength={160}
                    placeholder="e.g. AML Escalation Policy"
                    className={cn("mt-1.5", titleError && "border-danger focus:border-danger")}
                    aria-invalid={Boolean(titleError)}
                    aria-describedby={titleError ? "upload-title-error" : undefined}
                    disabled={busy}
                  />
                  {titleError ? (
                    <p id="upload-title-error" className="mt-1 text-xs text-danger font-medium">
                      {titleError}
                    </p>
                  ) : null}
                </div>
                <div>
                  <Label htmlFor="upload-doc-id">Document ID (optional)</Label>
                  <Input
                    id="upload-doc-id"
                    value={docId}
                    onChange={(event) => setDocId(event.target.value.toUpperCase())}
                    maxLength={64}
                    placeholder="e.g. POL-051"
                    className="mt-1.5 font-mono text-xs"
                    disabled={busy}
                  />
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <Label htmlFor="upload-type">Document type</Label>
                  <select
                    id="upload-type"
                    value={docType}
                    onChange={(event) => setDocType(event.target.value)}
                    disabled={busy}
                    className="mt-1.5 h-10 w-full rounded-[var(--r-sm)] border border-line bg-[rgba(3,6,10,0.44)] px-3 text-sm text-ink outline-none focus:border-line-accent focus:shadow-[0_0_0_3px_rgba(120,169,255,0.12)] disabled:opacity-50"
                  >
                    {DOCUMENT_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {type}
                      </option>
                    ))}
                  </select>
                </div>
                <fieldset aria-describedby={rolesError ? "upload-roles-error" : undefined}>
                  <legend className="text-xs font-medium text-ink-soft">Read access</legend>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {UPLOAD_ROLES.map((role) => {
                      const checked = roles.includes(role);
                      return (
                        <button
                          key={role}
                          type="button"
                          aria-pressed={checked}
                          disabled={busy}
                          onClick={() => {
                            setRolesTouched(true);
                            setRoles((current) =>
                              current.includes(role)
                                ? current.filter((item) => item !== role)
                                : [...current, role],
                            );
                          }}
                          className={cn(
                            "rounded-full border px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-50",
                            checked
                              ? "border-line-accent bg-accent-soft text-accent"
                              : "border-line bg-surface-2 text-faint hover:text-ink",
                          )}
                        >
                          {roleLabel(role)}
                        </button>
                      );
                    })}
                  </div>
                  {rolesError ? (
                    <p id="upload-roles-error" className="mt-1 text-xs text-danger font-medium">
                      {rolesError}
                    </p>
                  ) : null}
                  <p className="mt-1.5 text-xs leading-relaxed text-faint">
                    At least one role is required. Analysts can never read internal audit files
                    unless you explicitly grant analyst access.
                  </p>
                </fieldset>
              </div>

              {busy ? (
                <div className="rounded-[var(--r-md)] border border-line bg-surface-2/50 p-3">
                  <div className="mb-2 flex items-center gap-2 text-xs text-ink-soft">
                    <LoaderCircle className="size-3.5 animate-spin text-accent" aria-hidden="true" />
                    {stage === "uploading"
                      ? "Uploading and validating the file…"
                      : "Chunking, embedding and indexing into Qdrant + BM25…"}
                  </div>
                  <Progress
                    indeterminate={stage === "uploading"}
                    value={stage === "indexing" ? 72 : 30}
                    label="Indexing progress"
                  />
                </div>
              ) : null}

              {error ? (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-[var(--r-sm)] border border-[rgba(255,133,133,0.28)] bg-danger-soft px-3 py-2 text-xs text-danger"
                >
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                  <span>{error}</span>
                </div>
              ) : null}
            </>
          )}
        </DialogBody>

        <DialogFooter>
          {stage === "done" ? (
            <Button variant="primary" onClick={() => onOpenChange(false)}>
              Done
            </Button>
          ) : (
            <>
              <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
                Cancel
              </Button>
              <Button variant="primary" onClick={() => void submit()} disabled={busy || !file}>
                {busy ? <LoaderCircle className="animate-spin" /> : <FileUp />}
                {busy ? "Indexing…" : "Upload and index"}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
