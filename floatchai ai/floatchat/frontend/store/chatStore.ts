/**
 * FloatChat — Zustand Chat Store
 *
 * Manages sessions, messages, SSE stream state, and suggestions.
 * No async logic in the store — components call lib/api.ts
 * and dispatch actions.
 */

import { create } from "zustand";
import type {
  ChatSession,
  ChatMessage,
  Suggestion,
  StreamState,
} from "@/types/chat";
import type { ChartRow } from "@/types/visualization";
import type { DashboardWidget } from "@/types/visualization";

// ── Store interface ────────────────────────────────────────────────────────

interface ChatStore {
  // State
  sessions: ChatSession[];
  activeSessionId: string | null;
  messages: Record<string, ChatMessage[]>;
  resultRows: Record<string, ChartRow[]>;
  pinnedWidgets: DashboardWidget[];
  isLoading: boolean;
  streamState: StreamState;
  pendingInterpretation: string | null;
  loadTimeSuggestions: Suggestion[];

  // Actions
  setSessions: (sessions: ChatSession[]) => void;
  addSession: (session: ChatSession) => void;
  removeSession: (sessionId: string) => void;
  setActiveSession: (sessionId: string | null) => void;
  setMessages: (sessionId: string, messages: ChatMessage[]) => void;
  appendMessage: (sessionId: string, message: ChatMessage) => void;
  setResultRows: (messageId: string, rows: ChartRow[]) => void;
  addWidget: (widget: Omit<DashboardWidget, "layout">) => void;
  removeWidget: (widgetId: string) => void;
  updateWidgetLayout: (widgetId: string, layout: DashboardWidget["layout"]) => void;
  updateLastMessage: (
    sessionId: string,
    updates: Partial<ChatMessage>,
  ) => void;
  setLoading: (loading: boolean) => void;
  setStreamState: (state: StreamState) => void;
  setPendingInterpretation: (interpretation: string | null) => void;
  setLoadTimeSuggestions: (suggestions: Suggestion[]) => void;
}

// ── Store implementation ───────────────────────────────────────────────────

export const useChatStore = create<ChatStore>((set) => ({
  // Initial state
  sessions: [],
  activeSessionId: null,
  messages: {},
  resultRows: {},
  pinnedWidgets: [],
  isLoading: false,
  streamState: null,
  pendingInterpretation: null,
  loadTimeSuggestions: [],

  // Actions
  setSessions: (sessions) => set({ sessions }),

  addSession: (session) =>
    set((state) => ({
      sessions: [session, ...state.sessions],
    })),

  removeSession: (sessionId) =>
    set((state) => ({
      sessions: state.sessions.filter((s) => s.session_id !== sessionId),
    })),

  setActiveSession: (sessionId) => set({ activeSessionId: sessionId }),

  setMessages: (sessionId, messages) =>
    set((state) => ({
      messages: { ...state.messages, [sessionId]: messages },
    })),

  appendMessage: (sessionId, message) =>
    set((state) => ({
      messages: {
        ...state.messages,
        [sessionId]: [...(state.messages[sessionId] ?? []), message],
      },
    })),

  setResultRows: (messageId, rows) =>
    set((state) => ({
      resultRows: { ...state.resultRows, [messageId]: rows },
    })),

  addWidget: (widget) =>
    set((state) => {
      if (state.pinnedWidgets.length >= 10) {
        return state;
      }
      if (state.pinnedWidgets.some((w) => w.id === widget.id)) {
        return state;
      }
      return {
        pinnedWidgets: [
          ...state.pinnedWidgets,
          {
            ...widget,
            layout: {
              x: 0,
              y: Infinity,
              w: 4,
              h: 6,
            },
          },
        ],
      };
    }),

  removeWidget: (widgetId) =>
    set((state) => ({
      pinnedWidgets: state.pinnedWidgets.filter((widget) => widget.id !== widgetId),
    })),

  updateWidgetLayout: (widgetId, layout) =>
    set((state) => ({
      pinnedWidgets: state.pinnedWidgets.map((widget) =>
        widget.id === widgetId ? { ...widget, layout } : widget,
      ),
    })),

  updateLastMessage: (sessionId, updates) =>
    set((state) => {
      const msgs = state.messages[sessionId];
      if (!msgs || msgs.length === 0) return state;
      const last = msgs[msgs.length - 1];
      return {
        messages: {
          ...state.messages,
          [sessionId]: [
            ...msgs.slice(0, -1),
            { ...last, ...updates },
          ],
        },
      };
    }),

  setLoading: (loading) => set({ isLoading: loading }),

  setStreamState: (streamState) => set({ streamState }),

  setPendingInterpretation: (interpretation) =>
    set({ pendingInterpretation: interpretation }),

  setLoadTimeSuggestions: (suggestions) =>
    set({ loadTimeSuggestions: suggestions }),
}));
