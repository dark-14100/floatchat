"use client";

/**
 * /chat — Creates a new session and redirects to /chat/{session_id}.
 *
 * This page exists so that navigating to /chat always starts a fresh
 * conversation. The actual chat UI lives at /chat/[session_id]/page.tsx.
 */

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { createSession } from "@/lib/api";
import { useChatStore } from "@/store/chatStore";
import type { ChatSession } from "@/types/chat";

export default function ChatIndexPage() {
  const router = useRouter();
  const addSession = useChatStore((s) => s.addSession);
  const setActiveSession = useChatStore((s) => s.setActiveSession);
  const creating = useRef(false);

  useEffect(() => {
    if (creating.current) return;
    creating.current = true;

    createSession()
      .then((res) => {
        const session: ChatSession = {
          session_id: res.session_id,
          name: null,
          message_count: 0,
          created_at: res.created_at,
          last_active_at: res.created_at,
          is_active: true,
        };
        addSession(session);
        setActiveSession(res.session_id);
        router.replace(`/chat/${res.session_id}`);
      })
      .catch(() => {
        // If API is down, show a fallback message
      });
  }, [addSession, setActiveSession, router]);

  return (
    <div className="flex h-full items-center justify-center text-muted-foreground">
      <div className="flex items-center gap-2">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
        <span className="text-sm">Starting a new conversation…</span>
      </div>
    </div>
  );
}
