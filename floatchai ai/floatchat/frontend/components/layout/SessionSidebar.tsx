"use client";

/**
 * SessionSidebar — Left panel showing chat sessions.
 *
 * - "FloatChat" branding at top
 * - "New Conversation" button → creates session, navigates to /chat/{id}
 * - Scrollable session list (unlimited, CSS overflow) ordered by last_active_at desc
 * - Each item: name (or "New conversation"), relative time, message count
 * - Active session highlighted
 * - Context menu (DropdownMenu) with Rename + Delete
 * - Responsive: collapses to hamburger on <768px
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import {
  MessageSquarePlus,
  MoreHorizontal,
  Pencil,
  Trash2,
  MessagesSquare,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

import { useChatStore } from "@/store/chatStore";
import {
  listSessions,
  createSession,
  renameSession,
  deleteSession,
} from "@/lib/api";
import type { ChatSession } from "@/types/chat";

// ── Relative time helper ───────────────────────────────────────────────────

function relativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);

  if (diffSec < 60) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHr < 24) return `${diffHr}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;
  return date.toLocaleDateString();
}

// ── Component ──────────────────────────────────────────────────────────────

interface SessionSidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function SessionSidebar({ isOpen, onClose }: SessionSidebarProps) {
  const router = useRouter();
  const pathname = usePathname();

  const sessions = useChatStore((s) => s.sessions);
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const setSessions = useChatStore((s) => s.setSessions);
  const addSession = useChatStore((s) => s.addSession);
  const removeSession = useChatStore((s) => s.removeSession);
  const setActiveSession = useChatStore((s) => s.setActiveSession);

  // Rename dialog state
  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<ChatSession | null>(null);
  const [renameName, setRenameName] = useState("");

  // ── Load sessions on mount ─────────────────────────────────────────────

  useEffect(() => {
    listSessions()
      .then(setSessions)
      .catch(() => {
        // API unavailable — keep empty list
      });
  }, [setSessions]);

  // ── Derive active session from pathname ────────────────────────────────

  useEffect(() => {
    const match = pathname.match(/\/chat\/([a-f0-9-]+)/);
    if (match) {
      setActiveSession(match[1]);
    }
  }, [pathname, setActiveSession]);

  // ── New conversation ───────────────────────────────────────────────────

  const handleNewConversation = useCallback(async () => {
    try {
      const res = await createSession();
      // Build a minimal ChatSession for the store
      const newSession: ChatSession = {
        session_id: res.session_id,
        name: null,
        message_count: 0,
        created_at: res.created_at,
        last_active_at: res.created_at,
        is_active: true,
      };
      addSession(newSession);
      setActiveSession(res.session_id);
      router.push(`/chat/${res.session_id}`);
      onClose(); // close sidebar on mobile after navigation
    } catch {
      // Silently fail — user can retry
    }
  }, [addSession, setActiveSession, router, onClose]);

  // ── Session click ──────────────────────────────────────────────────────

  const handleSessionClick = useCallback(
    (sessionId: string) => {
      setActiveSession(sessionId);
      router.push(`/chat/${sessionId}`);
      onClose();
    },
    [setActiveSession, router, onClose],
  );

  // ── Rename ─────────────────────────────────────────────────────────────

  const openRenameDialog = useCallback((session: ChatSession) => {
    setRenameTarget(session);
    setRenameName(session.name ?? "");
    setRenameDialogOpen(true);
  }, []);

  const handleRename = useCallback(async () => {
    if (!renameTarget || !renameName.trim()) return;
    try {
      await renameSession(renameTarget.session_id, renameName.trim());
      // Update in store
      setSessions(
        sessions.map((s) =>
          s.session_id === renameTarget.session_id
            ? { ...s, name: renameName.trim() }
            : s,
        ),
      );
    } catch {
      // Fail silently
    }
    setRenameDialogOpen(false);
    setRenameTarget(null);
  }, [renameTarget, renameName, sessions, setSessions]);

  // ── Delete ─────────────────────────────────────────────────────────────

  const handleDelete = useCallback(
    async (sessionId: string) => {
      try {
        await deleteSession(sessionId);
        removeSession(sessionId);
        // If the deleted session was active, navigate away
        if (activeSessionId === sessionId) {
          setActiveSession(null);
          router.push("/chat");
        }
      } catch {
        // Fail silently
      }
    },
    [removeSession, activeSessionId, setActiveSession, router],
  );

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <>
      {/* Backdrop for mobile */}
      {isOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={`
          fixed inset-y-0 left-0 z-40 flex w-[280px] flex-col
          border-r border-border bg-card
          transition-transform duration-200 ease-in-out
          md:relative md:translate-x-0
          ${isOpen ? "translate-x-0" : "-translate-x-full"}
        `}
      >
        {/* Header */}
        <div className="flex h-14 items-center justify-between border-b border-border px-4">
          <div className="flex items-center gap-2">
            <MessagesSquare className="h-5 w-5 text-primary" />
            <span className="text-lg font-semibold text-foreground">
              FloatChat
            </span>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-muted-foreground hover:text-foreground md:hidden"
            aria-label="Close sidebar"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* New Conversation button */}
        <div className="p-3">
          <Button
            onClick={handleNewConversation}
            className="w-full justify-start gap-2"
            variant="outline"
          >
            <MessageSquarePlus className="h-4 w-4" />
            New Conversation
          </Button>
        </div>

        {/* Session list */}
        <ScrollArea className="flex-1">
          <div className="flex flex-col gap-0.5 px-2 pb-4">
            {sessions.map((session) => {
              const isActive = session.session_id === activeSessionId;
              return (
                <div
                  key={session.session_id}
                  className={`
                    group flex items-center gap-2 rounded-md px-3 py-2
                    cursor-pointer text-sm transition-colors
                    ${
                      isActive
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                    }
                  `}
                  onClick={() => handleSessionClick(session.session_id)}
                >
                  {/* Session info */}
                  <div className="flex-1 min-w-0">
                    <div className="truncate font-medium">
                      {session.name || "New conversation"}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span>{relativeTime(session.last_active_at)}</span>
                      {session.message_count > 0 && (
                        <span>· {session.message_count} msgs</span>
                      )}
                    </div>
                  </div>

                  {/* Context menu */}
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button
                        className="
                          shrink-0 rounded p-1 opacity-0 transition-opacity
                          hover:bg-accent group-hover:opacity-100
                          data-[state=open]:opacity-100
                        "
                        onClick={(e) => e.stopPropagation()}
                        aria-label="Session options"
                      >
                        <MoreHorizontal className="h-4 w-4" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-40">
                      <DropdownMenuItem
                        onClick={(e) => {
                          e.stopPropagation();
                          openRenameDialog(session);
                        }}
                      >
                        <Pencil className="mr-2 h-4 w-4" />
                        Rename
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(session.session_id);
                        }}
                        className="text-destructive focus:text-destructive"
                      >
                        <Trash2 className="mr-2 h-4 w-4" />
                        Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              );
            })}

            {sessions.length === 0 && (
              <div className="px-3 py-8 text-center text-sm text-muted-foreground">
                No conversations yet.
                <br />
                Start a new one above!
              </div>
            )}
          </div>
        </ScrollArea>
      </aside>

      {/* Rename dialog */}
      <Dialog open={renameDialogOpen} onOpenChange={setRenameDialogOpen}>
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <DialogTitle>Rename conversation</DialogTitle>
          </DialogHeader>
          <Input
            value={renameName}
            onChange={(e) => setRenameName(e.target.value)}
            placeholder="Conversation name"
            maxLength={255}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleRename();
            }}
          />
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRenameDialogOpen(false)}
            >
              Cancel
            </Button>
            <Button onClick={handleRename} disabled={!renameName.trim()}>
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
