"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Database, FileClock, ShieldCheck, LayoutDashboard, MessageSquare } from "lucide-react";

const LINKS = [
  { href: "/admin", label: "Dashboard", icon: LayoutDashboard },
  { href: "/admin/datasets", label: "Datasets", icon: Database },
  { href: "/admin/ingestion-jobs", label: "Ingestion Jobs", icon: FileClock },
  { href: "/admin/audit-log", label: "Audit Log", icon: ShieldCheck },
] as const;

export default function AdminSidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-full w-[250px] shrink-0 flex-col border-r border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)]">
      <div className="border-b border-[var(--color-border-subtle)] px-4 py-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">Admin Console</p>
        <p className="mt-1 text-sm text-[var(--color-text-secondary)]">Dataset lifecycle operations</p>
      </div>

      <nav className="flex-1 space-y-1 p-2">
        {LINKS.map((link) => {
          const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
          const Icon = link.icon;
          return (
            <Link
              key={link.href}
              href={link.href}
              className={[
                "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-[var(--color-ocean-lighter)] text-[var(--color-ocean-primary)]"
                  : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-elevated)] hover:text-[var(--color-text-primary)]",
              ].join(" ")}
            >
              <Icon className="h-4 w-4" />
              <span>{link.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-[var(--color-border-subtle)] p-3">
        <Link
          href="/chat"
          className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-bg-elevated)] hover:text-[var(--color-text-primary)]"
        >
          <MessageSquare className="h-4 w-4" />
          Back to Chat
        </Link>
      </div>
    </aside>
  );
}
