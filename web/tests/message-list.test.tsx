import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MessageList } from "@/components/chat/message-list";
import type { Message } from "@/lib/types";

function assistantMessage(overrides: Partial<Message> = {}): Message {
  return {
    id: 11,
    sender: "assistant",
    content: "A firm must apply customer due diligence before establishing a relationship.",
    route_used: "SINGLE_SEARCH",
    user_role: "analyst",
    metadata: {
      grounded: true,
      response_type: "rag",
      citations: [
        {
          doc_id: "FCA-1",
          doc_name: "FCA Handbook",
          doc_title: "FCA Handbook — SYSC",
          section_title: "Outsourcing",
          clause_id: "SYSC 8.1.1",
          page_number: 12,
          snippet: "A firm must take reasonable steps.",
          source_url: "https://www.handbook.fca.org.uk/handbook/SYSC/8/1.html",
          source_name: "FCA",
          is_internal: false,
        },
      ],
      suggested_follow_ups: ["What records must be kept?"],
    },
    created_at: "2026-01-01T10:00:00Z",
    ...overrides,
  };
}

function renderList(messages: Message[]) {
  return render(
    <MessageList
      messages={messages}
      streamingId={null}
      onRegenerate={vi.fn()}
      onEdit={vi.fn()}
      onFollowUp={vi.fn()}
      onStreamDone={vi.fn()}
      sending={false}
    />,
  );
}

describe("MessageList", () => {
  it("collapses sources by default and reveals them on demand", async () => {
    const user = userEvent.setup();
    renderList([assistantMessage()]);

    const trigger = screen.getByRole("button", { name: /sources \(1\)/i });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("FCA Handbook — SYSC")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open source/i })).toHaveAttribute(
      "href",
      "https://www.handbook.fca.org.uk/handbook/SYSC/8/1.html",
    );
  });

  it("never renders a public link for an internal citation, even with a malicious URL", async () => {
    const user = userEvent.setup();
    const message = assistantMessage();
    message.metadata = {
      ...message.metadata,
      citations: [
        {
          doc_id: "AUD-2024-03",
          doc_name: "Internal Audit KYC Review",
          section_title: "Findings",
          clause_id: "AUD-2024-03 §4",
          page_number: 4,
          snippet: "Two control gaps were identified.",
          source_url: "https://evil.example/leak",
          is_internal: true,
        },
      ],
    };

    renderList([message]);
    await user.click(screen.getByRole("button", { name: /sources \(1\)/i }));

    expect(screen.queryByRole("link", { name: /open source/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /verify on google/i })).not.toBeInTheDocument();
    expect(screen.getByText(/internal document — no public verification link/i)).toBeInTheDocument();
  });

  it("flags a citation outside the asking role as unauthorized", async () => {
    const user = userEvent.setup();
    const message = assistantMessage();
    message.metadata = {
      ...message.metadata,
      citations: [
        {
          doc_id: "AUD-2024-03",
          doc_name: "Internal Audit KYC Review",
          section_title: "Findings",
          clause_id: "AUD-2024-03 §4",
          page_number: 4,
          snippet: "Two control gaps were identified.",
          is_internal: true,
          allowed_roles: ["auditor"],
        },
      ],
    };

    renderList([message]);
    await user.click(screen.getByRole("button", { name: /sources \(1\)/i }));

    expect(screen.getByText(/unauthorized access/i)).toBeInTheDocument();
    expect(screen.getByText(/restricted to Auditor/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/internal document — no public verification link/i),
    ).not.toBeInTheDocument();
  });

  it("renders a distinct refusal card instead of citations", () => {
    const message = assistantMessage({
      content: "I can't find that in the documents available to your role.",
      metadata: {
        grounded: false,
        response_type: "direct",
        refusal_category: "NO_RELEVANT_PASSAGES",
        citations: [],
        suggested_follow_ups: [],
      },
    });

    renderList([message]);

    expect(screen.getByText(/no permitted source supports this answer/i)).toBeInTheDocument();
    expect(screen.getByText("NO_RELEVANT_PASSAGES")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sources/i })).not.toBeInTheDocument();
  });

  it("labels general chat as not grounded", () => {
    renderList([
      assistantMessage({
        content: "Basel III is an international regulatory framework.",
        route_used: "GENERAL_CHAT",
        metadata: {
          grounded: false,
          response_type: "general_chat",
          citations: [],
          suggested_follow_ups: [],
        },
      }),
    ]);

    expect(screen.getByText(/open knowledge · not grounded/i)).toBeInTheDocument();
  });

  it("exposes suggested follow-ups as buttons", async () => {
    const user = userEvent.setup();
    const onFollowUp = vi.fn();
    render(
      <MessageList
        messages={[assistantMessage()]}
        streamingId={null}
        onRegenerate={vi.fn()}
        onEdit={vi.fn()}
        onFollowUp={onFollowUp}
        onStreamDone={vi.fn()}
        sending={false}
      />,
    );

    await user.click(screen.getByRole("button", { name: "What records must be kept?" }));
    expect(onFollowUp).toHaveBeenCalledWith("What records must be kept?");
  });
});
