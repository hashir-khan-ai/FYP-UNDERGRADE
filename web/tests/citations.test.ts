import { describe, expect, it } from "vitest";

import {
  citationAllowedRoles,
  citationClause,
  citationHasAccess,
  citationHeading,
  citationLinks,
  citationTitle,
  googleVerificationUrl,
  safeHttpUrl,
} from "@/lib/citations";
import type { Citation } from "@/lib/types";

const baseCitation: Citation = {
  doc_id: "FCA-2024-1",
  doc_name: "FCA Handbook",
  doc_title: "FCA Handbook — SYSC",
  section_title: "Outsourcing",
  clause_id: "SYSC 8.1.1",
  page_number: 42,
  snippet: "A firm must take reasonable steps…",
  source_url: "https://www.handbook.fca.org.uk/handbook/SYSC/8/1.html",
  source_name: "FCA",
  is_internal: false,
};

describe("safeHttpUrl", () => {
  it("accepts absolute http(s) URLs", () => {
    expect(safeHttpUrl("https://www.bankofengland.co.uk/prudential-regulation")).toBe(
      "https://www.bankofengland.co.uk/prudential-regulation",
    );
    expect(safeHttpUrl("http://example.com/rule")).toBe("http://example.com/rule");
  });

  it("rejects script, data, relative, localhost and credential-bearing URLs", () => {
    expect(safeHttpUrl("javascript:alert(1)")).toBeNull();
    expect(safeHttpUrl("data:text/html,<script>alert(1)</script>")).toBeNull();
    expect(safeHttpUrl("/internal/policy.pdf")).toBeNull();
    expect(safeHttpUrl("http://localhost:8000/admin")).toBeNull();
    expect(safeHttpUrl("https://user:pass@example.com/doc")).toBeNull();
    expect(safeHttpUrl("")).toBeNull();
    expect(safeHttpUrl(null)).toBeNull();
  });

  it("rejects absurdly long URLs", () => {
    expect(safeHttpUrl(`https://example.com/${"a".repeat(2100)}`)).toBeNull();
  });
});

describe("citationLinks", () => {
  it("returns the trusted official source plus a verification search", () => {
    const links = citationLinks(baseCitation);

    expect(links.sourceUrl).toBe(baseCitation.source_url);
    expect(links.isInternal).toBe(false);
    expect(links.verificationUrl).toContain("https://www.google.com/search?q=");
    expect(links.verificationUrl).toContain(encodeURIComponent("FCA Handbook — SYSC"));
  });

  it("never exposes a public link for an internal document, even if the payload lies", () => {
    const links = citationLinks({
      ...baseCitation,
      is_internal: true,
      source_url: "https://evil.example/leak",
      verification_url: "https://evil.example/verify",
      source_name: "Internal Audit",
    });

    expect(links.sourceUrl).toBeNull();
    expect(links.verificationUrl).toBeNull();
    expect(links.isInternal).toBe(true);
    expect(links.internalNote).toMatch(/no public verification link/i);
    expect(links.authority).toBe("Internal Audit");
  });

  it("prefers an explicit verification URL when it is safe", () => {
    const links = citationLinks({
      ...baseCitation,
      source_url: null,
      verification_url: "https://www.legislation.gov.uk/uksi/2017/692",
    });

    expect(links.sourceUrl).toBeNull();
    expect(links.verificationUrl).toBe("https://www.legislation.gov.uk/uksi/2017/692");
  });

  it("drops an unsafe source URL instead of rendering it", () => {
    const links = citationLinks({ ...baseCitation, source_url: "javascript:alert(1)" });
    expect(links.sourceUrl).toBeNull();
  });
});

describe("citation access", () => {
  it("normalises permitted roles and treats missing metadata as accessible", () => {
    expect(citationAllowedRoles(baseCitation)).toEqual([]);
    expect(citationHasAccess(baseCitation, "analyst")).toBe(true);
    expect(citationAllowedRoles({ ...baseCitation, allowed_roles: [" Auditor ", "Manager"] })).toEqual([
      "auditor",
      "manager",
    ]);
  });

  it("denies a role that is not in the permitted list", () => {
    const restricted: Citation = { ...baseCitation, allowed_roles: ["auditor"] };
    expect(citationHasAccess(restricted, "auditor")).toBe(true);
    expect(citationHasAccess(restricted, "Analyst")).toBe(false);
    expect(citationHasAccess(restricted, null)).toBe(false);
  });
});

describe("citation display fallbacks", () => {
  it("uses stable fallbacks for missing metadata", () => {
    const sparse: Citation = {
      doc_id: "DOC-1",
      doc_name: "",
      section_title: "",
      clause_id: "",
      page_number: null,
      snippet: "",
    };

    expect(citationTitle(sparse)).toBe("Untitled regulatory document");
    expect(citationHeading(sparse)).toBe("Section not stated");
    expect(citationClause(sparse)).toBe("Clause not stated");
  });

  it("builds a Google verification query without inventing a canonical regulator URL", () => {
    const url = googleVerificationUrl(baseCitation);
    expect(url).not.toBeNull();
    expect(url).toContain("google.com/search");
    expect(url).toContain(encodeURIComponent("SYSC 8.1.1"));
    expect(url).toContain(encodeURIComponent("page 42"));
  });
});
