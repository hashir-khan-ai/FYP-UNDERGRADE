import { describe, expect, it } from "vitest";

import { INTENT_MODES, RESPONSE_MODES, intentModeLabel, intentModeMeta, responseModeMeta } from "@/lib/modes";

describe("intent modes", () => {
  it("offers exactly the three product scopes", () => {
    expect(INTENT_MODES.map((mode) => mode.value)).toEqual(["auto", "rag", "general"]);
    expect(INTENT_MODES.map((mode) => mode.label)).toEqual([
      "Auto",
      "Company Docs RAG",
      "General Chat",
    ]);
  });

  it("resolves metadata and falls back safely to Auto", () => {
    expect(intentModeMeta("rag").shortLabel).toBe("Company docs");
    expect(intentModeLabel("general")).toBe("General Chat");
    expect(intentModeMeta("unexpected").value).toBe("auto");
    expect(intentModeLabel(undefined as unknown as string)).toBe("Auto");
  });

  it("documents that Company Docs RAG refuses rather than guessing", () => {
    expect(intentModeMeta("rag").hint).toMatch(/refuses/i);
  });
});

describe("response modes", () => {
  it("maps strict and explain styles", () => {
    expect(RESPONSE_MODES.map((mode) => mode.value)).toEqual(["compliance", "explain"]);
    expect(responseModeMeta("explain").label).toBe("Explain");
  });

  it("falls back to strict compliance", () => {
    expect(responseModeMeta("anything").value).toBe("compliance");
  });
});
