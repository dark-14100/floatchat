"use client";

/**
 * LayoutShell — Client-side shell for the two-panel layout.
 *
 * Handles:
 * - Sidebar open/close state
 * - Hamburger toggle on mobile (<768px)
 * - Anonymous UUID generation + localStorage persistence
 */

import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Menu } from "lucide-react";
import SessionSidebar from "@/components/layout/SessionSidebar";
import BackgroundIllustration from "@/components/layout/BackgroundIllustration";

interface LayoutShellProps {
  children: React.ReactNode;
}

export function LayoutShell({ children }: LayoutShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const pathname = usePathname();
  const isMapRoute = pathname === "/map";

  // ── Generate anonymous user UUID on first visit ──────────────────────

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!localStorage.getItem("floatchat_user_id")) {
      localStorage.setItem("floatchat_user_id", crypto.randomUUID());
    }
  }, []);

  const openSidebar = useCallback(() => setSidebarOpen(true), []);
  const closeSidebar = useCallback(() => setSidebarOpen(false), []);

  return (
    <>
      {/* Background illustration — outside flex so fixed isn't clipped */}
      <BackgroundIllustration />

      <div className="flex h-screen w-screen overflow-hidden bg-bg-base text-foreground">
        {/* Sidebar */}
        {!isMapRoute && <SessionSidebar isOpen={sidebarOpen} onClose={closeSidebar} />}

        {/* Main panel */}
        <div className="relative z-[1] flex flex-1 flex-col overflow-hidden">
          {/* Mobile hamburger header */}
          {!isMapRoute && (
            <div className="flex h-14 items-center border-b border-border px-4 md:hidden">
              <button
                onClick={openSidebar}
                className="rounded p-1 text-muted-foreground hover:text-foreground"
                aria-label="Open sidebar"
              >
                <Menu className="h-6 w-6" />
              </button>
              <span className="ml-3 text-sm font-semibold text-foreground">
                FloatChat
              </span>
            </div>
          )}

          {/* Page content */}
          <main className="flex-1 overflow-hidden">{children}</main>
        </div>
      </div>
    </>
  );
}
