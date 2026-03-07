"use client";

import { useState } from "react";

import AnomalyDetailPanel from "@/components/anomaly/AnomalyDetailPanel";
import AnomalyFeedList from "@/components/anomaly/AnomalyFeedList";

export default function AnomaliesPage() {
  const [selectedAnomalyId, setSelectedAnomalyId] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  return (
    <div className="flex h-full flex-col bg-[var(--color-bg-base)] p-4 md:p-5">
      <div className="mb-3">
        <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">Anomalies</h1>
        <p className="text-sm text-[var(--color-text-secondary)]">
          Review recently detected contextual anomalies and investigate in chat.
        </p>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[380px_1fr]">
        <AnomalyFeedList
          selectedAnomalyId={selectedAnomalyId}
          onSelectAnomaly={setSelectedAnomalyId}
          refreshToken={refreshToken}
        />

        <div className="min-h-0 overflow-y-auto">
          {selectedAnomalyId ? (
            <AnomalyDetailPanel
              anomalyId={selectedAnomalyId}
              onReviewed={() => setRefreshToken((v) => v + 1)}
            />
          ) : (
            <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-6 text-sm text-[var(--color-text-secondary)]">
              Select an anomaly from the feed to view full details.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
