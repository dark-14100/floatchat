import React from "react";
import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ChatSessionPage from "@/app/chat/[session_id]/page";

const createQueryStreamMock = vi.fn();
const createConfirmStreamMock = vi.fn();

let prefillValue: string | null = null;

const store = {
  setActiveSession: vi.fn(),
  appendMessage: vi.fn(),
  updateLastMessage: vi.fn(),
  setLoading: vi.fn(),
  setStreamState: vi.fn(),
  setPendingInterpretation: vi.fn(),
  setResultRows: vi.fn(),
  isLoading: false,
  streamState: null,
  pendingInterpretation: null,
};

vi.mock("next/navigation", () => ({
  useParams: () => ({ session_id: "sess-123" }),
  useSearchParams: () => ({
    get: (key: string) => (key === "prefill" ? prefillValue : null),
  }),
}));

vi.mock("@/store/chatStore", () => ({
  useChatStore: (selector: (s: typeof store) => unknown) => selector(store),
}));

vi.mock("@/lib/sse", () => ({
  createQueryStream: (...args: unknown[]) => createQueryStreamMock(...args),
  createConfirmStream: (...args: unknown[]) => createConfirmStreamMock(...args),
}));

vi.mock("@/components/chat/ChatThread", () => ({
  default: () => <div data-testid="chat-thread" />,
}));

vi.mock("@/components/chat/ChatInput", () => ({
  default: React.forwardRef(function MockChatInput() {
    return <div data-testid="chat-input" />;
  }),
}));

describe("ChatSessionPage prefill deep-link", () => {
  beforeEach(() => {
    prefillValue = null;
    createQueryStreamMock.mockReset();
    createConfirmStreamMock.mockReset();
    store.setActiveSession.mockReset();
    store.appendMessage.mockReset();
    store.updateLastMessage.mockReset();
    store.setLoading.mockReset();
    store.setStreamState.mockReset();
    store.setPendingInterpretation.mockReset();
    store.setResultRows.mockReset();

    createQueryStreamMock.mockReturnValue({
      abort: vi.fn(),
    });
  });

  it("auto-submits prefill query from URL search params", () => {
    prefillValue = "Show nearest floats around 10,72";

    render(<ChatSessionPage />);

    expect(createQueryStreamMock).toHaveBeenCalledTimes(1);
    expect(createQueryStreamMock.mock.calls[0][0]).toBe("sess-123");
    expect(createQueryStreamMock.mock.calls[0][1]).toBe("Show nearest floats around 10,72");
    expect(createQueryStreamMock.mock.calls[0][2]).toBe(false);
    expect(store.appendMessage).toHaveBeenCalledTimes(1);
  });

  it("does not auto-submit when prefill is missing", () => {
    render(<ChatSessionPage />);

    expect(createQueryStreamMock).not.toHaveBeenCalled();
  });
});
