/**
 * Zustand store tests.
 *
 * - Store updates through correct state sequences
 * - Session management actions
 * - Message append/update
 */

import { describe, it, expect, beforeEach } from "vitest";
import { useChatStore } from "@/store/chatStore";
import type { ChatSession, ChatMessage } from "@/types/chat";

function makeSession(overrides: Partial<ChatSession> = {}): ChatSession {
  return {
    session_id: "sess-1",
    name: null,
    message_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    last_active_at: "2026-01-01T00:00:00Z",
    is_active: true,
    ...overrides,
  };
}

function makeMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    message_id: "msg-1",
    session_id: "sess-1",
    role: "user",
    content: "test",
    nl_query: null,
    generated_sql: null,
    result_metadata: null,
    follow_up_suggestions: null,
    error: null,
    status: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("chatStore", () => {
  beforeEach(() => {
    // Reset state between tests
    useChatStore.setState({
      sessions: [],
      activeSessionId: null,
      messages: {},
      isLoading: false,
      streamState: null,
      pendingInterpretation: null,
      loadTimeSuggestions: [],
    });
  });

  // ── Session actions ────────────────────────────────────

  it("setSessions replaces the sessions list", () => {
    const sessions = [makeSession(), makeSession({ session_id: "sess-2" })];
    useChatStore.getState().setSessions(sessions);
    expect(useChatStore.getState().sessions).toHaveLength(2);
  });

  it("addSession prepends a session", () => {
    useChatStore.getState().setSessions([makeSession()]);
    useChatStore.getState().addSession(makeSession({ session_id: "new" }));
    const ids = useChatStore.getState().sessions.map((s) => s.session_id);
    expect(ids).toEqual(["new", "sess-1"]);
  });

  it("removeSession removes by id", () => {
    useChatStore
      .getState()
      .setSessions([makeSession(), makeSession({ session_id: "sess-2" })]);
    useChatStore.getState().removeSession("sess-1");
    expect(useChatStore.getState().sessions).toHaveLength(1);
    expect(useChatStore.getState().sessions[0].session_id).toBe("sess-2");
  });

  it("setActiveSession updates activeSessionId", () => {
    useChatStore.getState().setActiveSession("sess-1");
    expect(useChatStore.getState().activeSessionId).toBe("sess-1");
  });

  // ── Message actions ────────────────────────────────────

  it("setMessages sets messages for a session", () => {
    const msgs = [makeMessage(), makeMessage({ message_id: "msg-2" })];
    useChatStore.getState().setMessages("sess-1", msgs);
    expect(useChatStore.getState().messages["sess-1"]).toHaveLength(2);
  });

  it("appendMessage adds to existing messages", () => {
    useChatStore.getState().setMessages("sess-1", [makeMessage()]);
    useChatStore.getState().appendMessage("sess-1", makeMessage({ message_id: "msg-2" }));
    expect(useChatStore.getState().messages["sess-1"]).toHaveLength(2);
  });

  it("appendMessage creates array if none exists", () => {
    useChatStore.getState().appendMessage("sess-x", makeMessage({ session_id: "sess-x" }));
    expect(useChatStore.getState().messages["sess-x"]).toHaveLength(1);
  });

  it("updateLastMessage updates the last message", () => {
    useChatStore
      .getState()
      .setMessages("sess-1", [
        makeMessage(),
        makeMessage({ message_id: "msg-2", content: "original" }),
      ]);
    useChatStore
      .getState()
      .updateLastMessage("sess-1", { content: "updated" });

    const msgs = useChatStore.getState().messages["sess-1"];
    expect(msgs[1].content).toBe("updated");
    expect(msgs[0].content).toBe("test"); // first message unchanged
  });

  it("updateLastMessage is a no-op if messages array is empty", () => {
    useChatStore.getState().setMessages("sess-1", []);
    useChatStore.getState().updateLastMessage("sess-1", { content: "updated" });
    expect(useChatStore.getState().messages["sess-1"]).toHaveLength(0);
  });

  // ── Stream state actions ───────────────────────────────

  it("setLoading toggles isLoading", () => {
    useChatStore.getState().setLoading(true);
    expect(useChatStore.getState().isLoading).toBe(true);
    useChatStore.getState().setLoading(false);
    expect(useChatStore.getState().isLoading).toBe(false);
  });

  it("setStreamState updates stream state", () => {
    useChatStore.getState().setStreamState("thinking");
    expect(useChatStore.getState().streamState).toBe("thinking");
    useChatStore.getState().setStreamState("executing");
    expect(useChatStore.getState().streamState).toBe("executing");
    useChatStore.getState().setStreamState(null);
    expect(useChatStore.getState().streamState).toBeNull();
  });

  it("simulates correct SSE state sequence", () => {
    const store = useChatStore.getState();

    // 1) Start loading
    store.setLoading(true);
    store.setStreamState("thinking");
    expect(useChatStore.getState().isLoading).toBe(true);
    expect(useChatStore.getState().streamState).toBe("thinking");

    // 2) Interpreting
    store.setStreamState("interpreting");
    store.setPendingInterpretation("Looking for temperature data...");
    expect(useChatStore.getState().streamState).toBe("interpreting");
    expect(useChatStore.getState().pendingInterpretation).toBe(
      "Looking for temperature data...",
    );

    // 3) Executing
    store.setStreamState("executing");
    expect(useChatStore.getState().streamState).toBe("executing");

    // 4) Done
    store.setStreamState("done");
    store.setLoading(false);
    store.setPendingInterpretation(null);
    expect(useChatStore.getState().streamState).toBe("done");
    expect(useChatStore.getState().isLoading).toBe(false);
    expect(useChatStore.getState().pendingInterpretation).toBeNull();
  });

  // ── Suggestions ────────────────────────────────────────

  it("setLoadTimeSuggestions stores suggestions", () => {
    useChatStore.getState().setLoadTimeSuggestions([
      { query: "Show floats", description: "test" },
    ]);
    expect(useChatStore.getState().loadTimeSuggestions).toHaveLength(1);
    expect(useChatStore.getState().loadTimeSuggestions[0].query).toBe(
      "Show floats",
    );
  });
});
