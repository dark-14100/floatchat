"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { getFloatDetail, type FloatDetail } from "@/lib/mapQueries";

const OceanProfileChart = dynamic(
  () => import("@/components/visualization/OceanProfileChart"),
  { ssr: false },
);

interface FloatDetailPanelProps {
  platformNumber: string;
  onClose: () => void;
}

function toDms(value: number, isLat: boolean): string {
  const absolute = Math.abs(value);
  const degrees = Math.floor(absolute);
  const minutesFloat = (absolute - degrees) * 60;
  const minutes = Math.floor(minutesFloat);
  const seconds = Math.round((minutesFloat - minutes) * 60);
  const hemi = isLat ? (value >= 0 ? "N" : "S") : (value >= 0 ? "E" : "W");
  return `${degrees}°${minutes}'${seconds}" ${hemi}`;
}

export default function FloatDetailPanel({ platformNumber, onClose }: FloatDetailPanelProps) {
  const router = useRouter();
  const [detail, setDetail] = useState<FloatDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    getFloatDetail(platformNumber)
      .then((value) => {
        if (!mounted) return;
        setDetail(value);
      })
      .finally(() => {
        if (!mounted) return;
        setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [platformNumber]);

  const miniRows = useMemo(() => {
    if (!detail) return [];

    const rows: Array<Record<string, string | number | boolean | null>> = [];
    for (const profile of detail.recent_profiles) {
      const len = Math.min(profile.pressure_levels.length, profile.temperature_levels.length);
      for (let index = 0; index < len; index += 1) {
        rows.push({
          platform_number: detail.platform_number,
          cycle_number: profile.cycle_number,
          pressure: profile.pressure_levels[index],
          temperature: profile.temperature_levels[index],
        });
      }
    }
    return rows;
  }, [detail]);

  const isActive = detail?.last_profile_date
    ? (Date.now() - new Date(detail.last_profile_date).getTime()) / (1000 * 60 * 60 * 24) <= 30
    : false;

  return (
    <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3">
      {loading && (
        <div className="text-xs text-[var(--color-text-secondary)]">Loading float details…</div>
      )}

      {!loading && detail && (
        <>
          <div className="mb-3 flex items-start justify-between gap-2">
            <div>
              <h2 className="text-base font-semibold text-[var(--color-text-primary)]">{detail.platform_number}</h2>
              <div className="mt-1 flex items-center gap-2 text-xs">
                <span className="rounded-full bg-[var(--color-ocean-lighter)] px-2 py-0.5 font-medium text-[var(--color-ocean-deep)]">
                  {detail.float_type ?? "unknown"}
                </span>
                <span className="inline-flex items-center gap-1 text-[var(--color-text-secondary)]">
                  <span className={`inline-block h-2 w-2 rounded-full ${isActive ? "bg-[var(--color-seafoam)]" : "bg-[var(--color-text-muted)]"}`} />
                  {isActive ? "Active" : "Inactive"}
                </span>
              </div>
            </div>
            <button onClick={onClose} className="text-xs text-[var(--color-text-secondary)]">Close</button>
          </div>

          <div className="space-y-2 text-xs text-[var(--color-text-secondary)]">
            <div>
              <div className="font-medium text-[var(--color-text-primary)]">Location</div>
              <div>
                {detail.last_latitude?.toFixed(4)}, {detail.last_longitude?.toFixed(4)}
              </div>
              {detail.last_latitude !== null && detail.last_longitude !== null && (
                <div>
                  {toDms(detail.last_latitude, true)} • {toDms(detail.last_longitude, false)}
                </div>
              )}
            </div>

            <div>
              <div className="font-medium text-[var(--color-text-primary)]">Program</div>
              <div>{detail.country ?? "Unknown"} • {detail.program ?? "Unknown"}</div>
              <div>{detail.deployment_date ? new Date(detail.deployment_date).toLocaleDateString() : "Unknown deployment date"}</div>
            </div>

            <div>
              <div className="font-medium text-[var(--color-text-primary)]">Last active</div>
              <div>
                {detail.last_profile_date ? new Date(detail.last_profile_date).toLocaleDateString() : "Unknown"} • Cycles {detail.cycle_count}
              </div>
            </div>
          </div>

          <div className="mini-chart-wrapper mt-3 overflow-hidden rounded-md border border-[var(--color-border-subtle)]" style={{ height: 200 }}>
            {miniRows.length > 0 ? (
              <OceanProfileChart
                rows={miniRows}
                columns={["platform_number", "cycle_number", "pressure", "temperature"]}
                variables={["temperature"]}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-xs text-[var(--color-text-secondary)]">
                No recent profile data.
              </div>
            )}
          </div>

          <div className="mt-3 flex gap-2">
            <button
              onClick={() => router.push(`/chat?prefill=${encodeURIComponent(`show all profiles from float ${detail.platform_number}`)}`)}
              className="flex-1 rounded-md bg-[var(--color-ocean-primary)] px-3 py-2 text-xs font-medium text-[var(--color-text-inverse)]"
            >
              Open in Chat
            </button>
            <button
              onClick={() => router.push(`/chat?prefill=${encodeURIComponent(`show trajectory of float ${detail.platform_number}`)}`)}
              className="rounded-md border border-[var(--color-border-default)] px-3 py-2 text-xs text-[var(--color-text-secondary)]"
            >
              View trajectory
            </button>
          </div>

          <style jsx global>{`
            .mini-chart-wrapper > div > div.absolute.right-4.top-3 {
              display: none !important;
            }
          `}</style>
        </>
      )}
    </div>
  );
}
