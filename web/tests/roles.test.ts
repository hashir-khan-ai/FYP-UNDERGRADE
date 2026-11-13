import { describe, expect, it } from "vitest";

import {
  canUploadDocuments,
  canViewAudit,
  normalizeRole,
  roleLabel,
  roleScope,
} from "@/lib/auth";

describe("role helpers", () => {
  it("normalises known roles only", () => {
    expect(normalizeRole("Analyst")).toBe("analyst");
    expect(normalizeRole(" auditor ")).toBe("auditor");
    expect(normalizeRole("admin")).toBeNull();
    expect(normalizeRole(null)).toBeNull();
  });

  it("keeps upload rights with manager and auditor", () => {
    expect(canUploadDocuments("manager")).toBe(true);
    expect(canUploadDocuments("auditor")).toBe(true);
    expect(canUploadDocuments("analyst")).toBe(false);
    expect(canUploadDocuments("unknown")).toBe(false);
  });

  it("keeps audit summaries auditor-only", () => {
    expect(canViewAudit("auditor")).toBe(true);
    expect(canViewAudit("manager")).toBe(false);
    expect(canViewAudit("analyst")).toBe(false);
  });

  it("describes the role scope without implying UI authorisation", () => {
    expect(roleScope("analyst")).toMatch(/public/i);
    expect(roleScope("manager")).toMatch(/internal policies/i);
    expect(roleScope("auditor")).toMatch(/full corpus/i);
    expect(roleLabel("manager")).toBe("Manager");
  });
});
