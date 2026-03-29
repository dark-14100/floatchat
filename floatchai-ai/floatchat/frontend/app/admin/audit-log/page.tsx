"use client";

import AuditLogTable from "@/components/admin/AuditLogTable";

export default function AdminAuditLogPage() {
  return (
    <div className="space-y-4 p-4 md:p-5">
      <div>
        <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">Admin Audit Log</h1>
        <p className="text-sm text-[var(--color-text-secondary)]">Append-only record of state-changing admin actions.</p>
      </div>
      <AuditLogTable />
    </div>
  );
}
