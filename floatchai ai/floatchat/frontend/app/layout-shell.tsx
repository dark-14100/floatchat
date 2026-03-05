"use client";

/**
 * LayoutShell — Client-side shell for the two-panel layout.
 *
 * Handles:
 * - Sidebar open/close state
 * - Hamburger toggle on mobile (<768px)
 * - Auth bootstrap via silent refresh on protected routes
 * - Bypasses shell chrome for auth pages
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Menu } from "lucide-react";
import SessionSidebar from "@/components/layout/SessionSidebar";
import BackgroundIllustration from "@/components/layout/BackgroundIllustration";
import { useAuthStore } from "@/store/authStore";
import type { RefreshResponse } from "@/types/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const AUTH_ROUTES = ["/login", "/signup", "/forgot-password", "/reset-password"];

interface LayoutShellProps {
  children: React.ReactNode;
}

export function LayoutShell({ children }: LayoutShellProps) {
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [isAuthInitializing, setIsAuthInitializing] = useState(true);
  const hasInitializedAuth = useRef(false);

  const setAuth = useAuthStore((state) => state.setAuth);
  const clearAuth = useAuthStore((state) => state.clearAuth);
  const currentUser = useAuthStore((state) => state.currentUser);
  const accessToken = useAuthStore((state) => state.accessToken);

  const pathname = usePathname();
  const isAuthRoute = AUTH_ROUTES.some(
    (route) => pathname === route || pathname.startsWith(`${route}/`),
  );
  const isMapRoute = pathname === "/map";

  useEffect(() => {
    if (isAuthRoute) {
      setIsAuthInitializing(false);
      return;
    }

    if (hasInitializedAuth.current) {
      setIsAuthInitializing(false);
      return;
    }

    if (currentUser && accessToken) {
      hasInitializedAuth.current = true;
      setIsAuthInitializing(false);
      return;
    }

    hasInitializedAuth.current = true;

    const initializeAuth = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
          },
        });

        if (!response.ok) {
          clearAuth();
          const redirectTarget =
            typeof window !== "undefined"
              ? `${window.location.pathname}${window.location.search}`
              : pathname;
          router.replace(`/login?redirect=${encodeURIComponent(redirectTarget)}`);
          return;
        }

        const payload = (await response.json()) as RefreshResponse;
        setAuth(payload.user, payload.access_token);
      } catch {
        clearAuth();
        const redirectTarget =
          typeof window !== "undefined"
            ? `${window.location.pathname}${window.location.search}`
            : pathname;
        router.replace(`/login?redirect=${encodeURIComponent(redirectTarget)}`);
      } finally {
        setIsAuthInitializing(false);
      }
    };

    void initializeAuth();
  }, [isAuthRoute, currentUser, accessToken, setAuth, clearAuth, pathname, router]);

  const openSidebar = useCallback(() => setSidebarOpen(true), []);
  const closeSidebar = useCallback(() => setSidebarOpen(false), []);

  if (isAuthRoute) {
    return <>{children}</>;
  }

  if (isAuthInitializing) {
    return (
      <>
        <BackgroundIllustration />
        <div className="relative z-[1] flex min-h-screen items-center justify-center bg-bg-base text-text-secondary">
          <div className="flex items-center gap-2 text-sm">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
            <span>Restoring your session…</span>
          </div>
        </div>
      </>
    );
  }

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
