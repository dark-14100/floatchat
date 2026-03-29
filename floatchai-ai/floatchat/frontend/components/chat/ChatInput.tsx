"use client";

/**
 * ChatInput — Text input area fixed at the bottom of the main panel.
 *
 * Features:
 * - <textarea> (not <input>) per Hard Rule 6
 * - Auto-resize up to 6 lines (144px), then scroll
 * - Enter submits, Shift+Enter inserts newline
 * - Disabled while isLoading
 * - Character count at >450 chars
 * - Exposes ref for programmatic focus
 */

import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useRef,
  useState,
  type KeyboardEvent,
  type ChangeEvent,
} from "react";
import { SendHorizonal, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

// ── Types ──────────────────────────────────────────────────────────────────

export interface ChatInputHandle {
  focus: () => void;
}

interface ChatInputProps {
  onSubmit: (value: string) => void;
  isLoading: boolean;
  placeholder?: string;
}

// ── Constants ──────────────────────────────────────────────────────────────

const MAX_HEIGHT = 144; // 6 lines ≈ 24px per line
const CHAR_WARN_THRESHOLD = 450;
const LINE_HEIGHT = 24;

// ── Component ──────────────────────────────────────────────────────────────

const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(
  ({ onSubmit, isLoading, placeholder = "Ask about ocean data..." }, ref) => {
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const [value, setValue] = useState("");

    useImperativeHandle(ref, () => ({
      focus: () => textareaRef.current?.focus(),
    }));

    // Auto-resize textarea height
    const adjustHeight = useCallback(() => {
      const el = textareaRef.current;
      if (!el) return;
      // Reset to single line to measure scrollHeight
      el.style.height = `${LINE_HEIGHT}px`;
      const newHeight = Math.min(el.scrollHeight, MAX_HEIGHT);
      el.style.height = `${newHeight}px`;
    }, []);

    const handleChange = useCallback(
      (e: ChangeEvent<HTMLTextAreaElement>) => {
        setValue(e.target.value);
        adjustHeight();
      },
      [adjustHeight],
    );

    const handleSubmit = useCallback(() => {
      const trimmed = value.trim();
      if (!trimmed || isLoading) return;
      onSubmit(trimmed);
      setValue("");
      // Reset height after clearing
      requestAnimationFrame(() => {
        const el = textareaRef.current;
        if (el) el.style.height = `${LINE_HEIGHT}px`;
      });
    }, [value, isLoading, onSubmit]);

    const handleKeyDown = useCallback(
      (e: KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          handleSubmit();
        }
      },
      [handleSubmit],
    );

    return (
      <div className="border-t border-border bg-background px-4 py-3">
        <div className="mx-auto flex max-w-3xl items-end gap-2">
          <div className="relative flex-1">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={handleChange}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              disabled={isLoading}
              rows={1}
              aria-label="Chat message input"
              className="w-full resize-none rounded-lg border border-input bg-secondary px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              style={{ height: `${LINE_HEIGHT}px`, maxHeight: `${MAX_HEIGHT}px` }}
            />
            {value.length > CHAR_WARN_THRESHOLD && (
              <span className="absolute bottom-1 right-3 text-xs text-muted-foreground">
                {value.length}
              </span>
            )}
          </div>
          <Button
            size="icon"
            onClick={handleSubmit}
            disabled={isLoading || !value.trim()}
            aria-label="Send message"
            className="h-10 w-10 shrink-0"
          >
            {isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <SendHorizonal className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>
    );
  },
);

ChatInput.displayName = "ChatInput";

export default ChatInput;
