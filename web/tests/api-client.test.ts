import { describe, expect, it } from "vitest";

import { ApiError, isRefusalResponse, toApiError } from "@/lib/api-client";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("toApiError", () => {
  it("reads the sanitized error envelope", async () => {
    const error = await toApiError(
      jsonResponse(403, { error: { code: "FORBIDDEN", message: "Role is not permitted." } }),
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(403);
    expect(error.code).toBe("FORBIDDEN");
    expect(error.message).toBe("Role is not permitted.");
  });

  it("falls back to a safe message for a given status", async () => {
    const error = await toApiError(jsonResponse(429, {}));
    expect(error.code).toBe("RATE_OR_SPEND_LIMIT");
    expect(error.message).toMatch(/limit|cap/i);
  });

  it("does not leak non-JSON bodies or stack traces", async () => {
    const error = await toApiError(
      new Response("Traceback (most recent call last): secret internal path", { status: 500 }),
    );
    expect(error.message).not.toContain("Traceback");
    expect(error.message).not.toContain("secret");
  });

  it("truncates overly long upstream messages", async () => {
    const error = await toApiError(
      jsonResponse(400, { error: { code: "BAD_REQUEST", message: "x".repeat(900) } }),
    );
    expect(error.message.length).toBeLessThanOrEqual(400);
  });

  it("ignores non-string codes and messages", async () => {
    const error = await toApiError(
      jsonResponse(503, { error: { code: 42, message: { nested: true } } }),
    );
    expect(error.code).toBe("SERVICE_UNAVAILABLE");
    expect(error.message).toMatch(/unavailable/i);
  });
});

describe("isRefusalResponse", () => {
  const grader = {
    enabled: true,
    path: "keep",
    relevant_count: 1,
    ambiguous_count: 0,
    irrelevant_count: 0,
    rewrite_used: false,
    refused: false,
    refusal_reason: "",
    grader_calls: 1,
    tokens_used: 10,
    latency_ms: 10,
  };
  const base = {
    answer: "Firms must apply CDD.",
    refusal: null,
    refusal_category: null,
    grader,
  };

  it("is false for a normal grounded answer", () => {
    expect(isRefusalResponse(base)).toBe(false);
  });

  it("is true when the grader refused", () => {
    expect(isRefusalResponse({ ...base, grader: { ...grader, refused: true } })).toBe(true);
  });

  it("is true when a refusal category is present", () => {
    expect(isRefusalResponse({ ...base, refusal_category: "NO_RELEVANT_PASSAGES" })).toBe(true);
  });

  it("recognises the refusal marker in the answer text", () => {
    expect(
      isRefusalResponse({
        ...base,
        answer: "I can't find that in the documents available to your role.",
      }),
    ).toBe(true);
  });
});
