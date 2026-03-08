"use client";

import { useSearchParams } from "next/navigation";

import IngestionJobsTable from "@/components/admin/IngestionJobsTable";

export default function AdminIngestionJobsPage() {
  const searchParams = useSearchParams();
  const focusJobId = searchParams.get("focusJob");

  return (
    <div className="space-y-4 p-4 md:p-5">
      <div>
        <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">Ingestion Monitoring</h1>
        <p className="text-sm text-[var(--color-text-secondary)]">Track all ingestion jobs in real time and retry failed jobs.</p>
      </div>
      <IngestionJobsTable focusJobId={focusJobId} />
    </div>
  );
}
