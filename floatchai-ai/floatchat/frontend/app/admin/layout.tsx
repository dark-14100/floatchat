"use client";

import { useEffect, useMemo } from "react";
import { usePathname, useRouter } from "next/navigation";
import AdminSidebar from "@/components/admin/AdminSidebar";
import { useAuthStore } from "@/store/authStore";

function segmentToLabel(segment: string): string {
  if (!segment) return "Dashboard";
  return segment
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const currentUser = useAuthStore((state) => state.currentUser);

  useEffect(() => {
    if (!currentUser) {
      return;
    }
    if (currentUser.role !== "admin") {
      router.replace("/");
    }
  }, [currentUser, router]);

  const breadcrumb = useMemo(() => {
    const segments = pathname.split("/").filter(Boolean).slice(1);
    if (segments.length === 0) {
      return "Dashboard";
    }
    return segments.map(segmentToLabel).join(" / ");
  }, [pathname]);

  if (!currentUser) {
    return (
      <div className="flex h-full items-center justify-center bg-[var(--color-bg-base)] text-sm text-[var(--color-text-secondary)]">
        Checking admin access...
      </div>
    );
  }

  if (currentUser.role !== "admin") {
    return (
      <div className="flex h-full items-center justify-center bg-[var(--color-bg-base)] text-sm text-[var(--color-text-secondary)]">
        Redirecting...
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 bg-[var(--color-bg-base)]">
      <AdminSidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-b border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] px-5 py-3">
          <p className="text-xs uppercase tracking-wide text-[var(--color-text-muted)]">Feature 10</p>
          <p className="text-sm font-medium text-[var(--color-text-primary)]">{breadcrumb}</p>
        </header>
        <main className="min-h-0 flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
