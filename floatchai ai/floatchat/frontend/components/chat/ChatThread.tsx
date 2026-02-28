"use client";

/**
 * ChatThread — Scrollable message area for a chat session.
 *
 * Features:
 * - Load 50 messages on mount
 * - Auto-scroll to bottom on new messages
 * - "Scroll to bottom" button when user scrolls up + new message incoming
 * - Infinite scroll upward (cursor pagination)
 * - Empty state → SuggestionsPanel
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { ArrowDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getMessages } from "@/lib/api";
import { useChatStore } from "@/store/chatStore";
import type { ChatMessage as ChatMessageType, StreamState } from "@/types/chat";
import ChatMessage from "./ChatMessage";
import LoadingMessage from "./LoadingMessage";
import SuggestionsPanel from "./SuggestionsPanel";

// ── Types ──────────────────────────────────────────────────────────────────

interface ChatThreadProps {
  sessionId: string;
  streamState: StreamState;
  pendingInterpretation: string | null;
  /** Used for the inline loading message result data during streaming */
  streamResultRows?: Record<string, string | number | boolean | null>[];
  streamResultColumns?: string[];
  onFollowUpSelect: (query: string) => void;
  onConfirm: (messageId: string) => void;
  onCancelConfirm: () => void;
  onRetry: (query: string) => void;
  onSuggestionSelect: (query: string) => void;
}

// ── Constants ──────────────────────────────────────────────────────────────

const PAGE_SIZE = 50;
const SCROLL_THRESHOLD = 200; // px from bottom to show "scroll to bottom"

// ── Component ──────────────────────────────────────────────────────────────

export default function ChatThread({
  sessionId,
  streamState,
  pendingInterpretation,
  onFollowUpSelect,
  onConfirm,
  onCancelConfirm,
  onRetry,
  onSuggestionSelect,
}: ChatThreadProps) {
  const messages = useChatStore((s) => s.messages[sessionId] ?? []);
  const setMessages = useChatStore((s) => s.setMessages);
  const isLoading = useChatStore((s) => s.isLoading);

  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [hasOlderMessages, setHasOlderMessages] = useState(true);
  const prevScrollHeightRef = useRef<number>(0);

  // ── Load initial messages ──────────────────
  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const msgs = await getMessages(sessionId, PAGE_SIZE);
        if (!cancelled) {
          setMessages(sessionId, msgs);
          setHasOlderMessages(msgs.length >= PAGE_SIZE);
        }
      } catch {
        // If session doesn't exist or error, leave messages empty
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [sessionId, setMessages]);

  // ── Auto-scroll to bottom when new messages arrive ─────
  useEffect(() => {
    if (!scrollRef.current) return;
    const el = scrollRef.current;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;

    // Only auto-scroll if user is near bottom (or loading just finished)
    if (distFromBottom < SCROLL_THRESHOLD || !isLoading) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages.length, isLoading]);

  // ── Scroll listener for "scroll to bottom" button ──────
  const handleScroll = useCallback(() => {
    if (!scrollRef.current) return;
    const el = scrollRef.current;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    setShowScrollBtn(distFromBottom > SCROLL_THRESHOLD && isLoading);
  }, [isLoading]);

  // ── Infinite scroll upward ─────────────────────────────
  const handleScrollUp = useCallback(async () => {
    if (!scrollRef.current || loadingOlder || !hasOlderMessages) return;
    const el = scrollRef.current;

    // Trigger when scrolled near the top
    if (el.scrollTop > 50) return;

    const oldestMessage = messages[0];
    if (!oldestMessage) return;

    setLoadingOlder(true);
    prevScrollHeightRef.current = el.scrollHeight;

    try {
      const olderMsgs = await getMessages(
        sessionId,
        PAGE_SIZE,
        oldestMessage.message_id,
      );

      if (olderMsgs.length > 0) {
        setMessages(sessionId, [...olderMsgs, ...messages]);
        setHasOlderMessages(olderMsgs.length >= PAGE_SIZE);

        // Preserve scroll position after prepending
        requestAnimationFrame(() => {
          if (scrollRef.current) {
            const newScrollHeight = scrollRef.current.scrollHeight;
            scrollRef.current.scrollTop =
              newScrollHeight - prevScrollHeightRef.current;
          }
        });
      } else {
        setHasOlderMessages(false);
      }
    } catch {
      // Silently fail — user can try scrolling again
    } finally {
      setLoadingOlder(false);
    }
  }, [loadingOlder, hasOlderMessages, messages, sessionId, setMessages]);

  // ── Combined scroll handler ────────────────────────────
  const onScroll = useCallback(() => {
    handleScroll();
    handleScrollUp();
  }, [handleScroll, handleScrollUp]);

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    setShowScrollBtn(false);
  }, []);

  // ── Empty state ────────────────────────────────────────
  if (messages.length === 0 && !isLoading) {
    return <SuggestionsPanel onSelect={onSuggestionSelect} />;
  }

  return (
    <div className="relative flex-1 overflow-hidden">
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="flex h-full flex-col gap-4 overflow-y-auto px-4 py-6"
      >
        {/* Loading indicator for older messages */}
        {loadingOlder && (
          <div className="flex justify-center py-2">
            <span className="text-xs text-muted-foreground">
              Loading older messages...
            </span>
          </div>
        )}

        {/* Messages */}
        <div className="mx-auto w-full max-w-3xl space-y-4">
          {messages.map((msg) => (
            <ChatMessage
              key={msg.message_id}
              message={msg}
              onFollowUpSelect={onFollowUpSelect}
              onConfirm={onConfirm}
              onCancelConfirm={onCancelConfirm}
              onRetry={onRetry}
            />
          ))}

          {/* Streaming loading message */}
          {isLoading && streamState && streamState !== "done" && (
            <div className="flex w-full justify-start">
              <div className="flex max-w-[80%] items-start gap-2">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary">
                  <span className="text-xs text-muted-foreground">AI</span>
                </div>
                <LoadingMessage
                  streamState={streamState}
                  interpretation={pendingInterpretation}
                />
              </div>
            </div>
          )}
        </div>

        {/* Scroll anchor */}
        <div ref={bottomRef} />
      </div>

      {/* Scroll to bottom button */}
      {showScrollBtn && (
        <Button
          size="icon"
          variant="secondary"
          onClick={scrollToBottom}
          className="absolute bottom-4 right-4 h-8 w-8 rounded-full shadow-lg"
          aria-label="Scroll to bottom"
        >
          <ArrowDown className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}
