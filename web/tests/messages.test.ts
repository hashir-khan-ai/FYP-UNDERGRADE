import { describe, expect, it } from "vitest";

import {
  isRefusalTurn,
  lastUserPrompt,
  messageFromChatResponse,
  optimisticUserMessage,
  turnFlags,
} from "@/lib/messages";
import type { ChatResponse, Message } from "@/lib/types";

const citation: ChatResponse["citations"][number] = {
  doc_id: "FCA-1",
  doc_name: "FCA Handbook",
  section_title: "SYSC 8",
  clause_id: "SYSC 8.1.1",
  page_number: 12,
  snippet: "A firm must…",
  chunk_id: "FCA-1::chunk-0",
};

function response(overrides: Partial<ChatResponse> = {}): ChatResponse {
  return {
    session_id: "11111111-1111-4111-8111-111111111111",
    answer: "Firms must apply customer due diligence.",
    route_taken: "SINGLE_SEARCH",
    route: "SINGLE_SEARCH",
    citations: [citation],
    reasoning_trace: ["route=SINGLE_SEARCH", "retrieved=1"],
    retrieval_stats: {
      total_chunks_retrieved: 1,
      top_rerank_score: 0.91,
      retry_count: 0,
      rewritten_query: null,
    },
    llm_stats: {
      profile: "mock",
      model: "mock-llm",
      prompt_version: "v1",
      calls: 1,
      cached_calls: 0,
      prompt_tokens: 100,
      completion_tokens: 40,
      cached_response: false,
    },
    spend: { calls_used: 1, calls_limit: 50, tokens_used: 140, tokens_limit: 50000, exhausted: false },
    latency_ms: 120,
    audit_id: 7,
    role: "analyst",
    rbac_enabled: true,
    candidates_filtered_by_role: 2,
    router: {
      enabled: true,
      route: "SINGLE_SEARCH",
      confidence: 0.88,
      sub_questions: [],
      fallback_used: false,
      fallback_reason: null,
      direct_category: null,
      latency_ms: 10,
      tokens_used: 12,
    },
    grader: {
      enabled: true,
      path: "keep",
      relevant_count: 1,
      ambiguous_count: 0,
      irrelevant_count: 0,
      rewrite_used: false,
      refused: false,
      refusal_reason: "",
      grader_calls: 1,
      tokens_used: 12,
      latency_ms: 12,
    },
    grader_path: "keep",
    refusal: null,
    refusal_category: null,
    timings: { retrieve: 20, generate: 80 },
    citations_dropped: 0,
    heading_path_enabled: true,
    response_mode: "compliance",
    intent_mode: "auto",
    response_type: "rag",
    grounded: true,
    suggested_follow_ups: ["What records must be kept?"],
    ...overrides,
  };
}

describe("messageFromChatResponse", () => {
  it("persists the full rendering contract into message metadata", () => {
    const message = messageFromChatResponse(response(), "compliance", "auto");

    expect(message.sender).toBe("assistant");
    expect(message.route_used).toBe("SINGLE_SEARCH");
    expect(message.metadata?.citations).toHaveLength(1);
    expect(message.metadata?.grounded).toBe(true);
    expect(message.metadata?.response_type).toBe("rag");
    expect(message.metadata?.suggested_follow_ups).toHaveLength(1);
    expect(message.metadata?.chunk_ids).toEqual(["FCA-1::chunk-0"]);
    expect(message.metadata?.llm_profile).toBe("mock");
    expect(message.metadata?.timings).toEqual({ retrieve: 20, generate: 80 });
  });
});

describe("turnFlags", () => {
  it("marks a grounded RAG answer", () => {
    const message = messageFromChatResponse(response(), "compliance", "auto");
    expect(turnFlags(message)).toMatchObject({
      grounded: true,
      responseType: "rag",
      isRefusal: false,
      isGeneralChat: false,
    });
  });

  it("marks general chat as not grounded even if the flag is wrong", () => {
    const message: Message = {
      id: 1,
      sender: "assistant",
      content: "Basel III is a framework.",
      route_used: "GENERAL_CHAT",
      user_role: "analyst",
      metadata: { grounded: true, response_type: "general_chat" },
      created_at: null,
    };
    expect(turnFlags(message).grounded).toBe(false);
    expect(turnFlags(message).isGeneralChat).toBe(true);
  });

  it("detects refusals from metadata or the answer marker", () => {
    const flagged = messageFromChatResponse(
      response({
        answer: "I can't find that in the documents available to your role.",
        refusal_category: "NO_RELEVANT_PASSAGES",
        grounded: false,
        response_type: "direct",
        citations: [],
      }),
      "compliance",
      "rag",
    );
    expect(turnFlags(flagged).isRefusal).toBe(true);

    const markerOnly: Message = {
      id: 2,
      sender: "assistant",
      content: "I can't find that in the documents available to your role.",
      route_used: "SINGLE_SEARCH",
      user_role: "analyst",
      metadata: null,
      created_at: null,
    };
    expect(isRefusalTurn(markerOnly.content, markerOnly.metadata)).toBe(true);
  });
});

describe("conversation helpers", () => {
  it("builds an optimistic user turn", () => {
    const message = optimisticUserMessage("  What is CDD?  ");
    expect(message.sender).toBe("user");
    expect(message.content).toBe("  What is CDD?  ");
    expect(message.id).toBeLessThan(0);
  });

  it("finds the last user prompt for regeneration", () => {
    const messages: Message[] = [
      optimisticUserMessage("first"),
      { ...optimisticUserMessage("second"), id: -2 },
      {
        id: 3,
        sender: "assistant",
        content: "answer",
        route_used: "SINGLE_SEARCH",
        user_role: "analyst",
        metadata: null,
        created_at: null,
      },
    ];
    expect(lastUserPrompt(messages)).toBe("second");
    expect(lastUserPrompt([])).toBeNull();
  });
});
