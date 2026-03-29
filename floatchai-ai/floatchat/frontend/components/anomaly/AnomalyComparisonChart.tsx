"use client";

import { useMemo } from "react";
import dynamic from "next/dynamic";

const Plot = dynamic(() => import("react-plotly.js"), {
  ssr: false,
  loading: () => (
    <div className="py-8 text-center text-xs text-[var(--color-text-secondary)]">Loading chart...</div>
  ),
});

interface AnomalyComparisonChartProps {
  variable: string;
  baselineValue: number | null;
  observedValue: number | null;
  deviationPercent: number | null;
}

export default function AnomalyComparisonChart({
  variable,
  baselineValue,
  observedValue,
  deviationPercent,
}: AnomalyComparisonChartProps) {
  const data = useMemo(() => {
    if (baselineValue === null || observedValue === null) {
      return [];
    }

    return [
      {
        type: "bar",
        x: ["Baseline", "Observed"],
        y: [baselineValue, observedValue],
        marker: {
          color: ["#1B7A9E", "#E8785A"],
        },
        hovertemplate: "%{x}: %{y:.4f}<extra></extra>",
      },
    ];
  }, [baselineValue, observedValue]);

  const subtitle = useMemo(() => {
    if (deviationPercent === null) return "Stored baseline comparison";
    return `Deviation: ${deviationPercent.toFixed(2)}%`;
  }, [deviationPercent]);

  return (
    <div className="rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3">
      <div className="mb-2 text-xs text-[var(--color-text-secondary)]">{variable} comparison</div>
      {data.length === 0 ? (
        <div className="py-8 text-center text-xs text-[var(--color-text-secondary)]">
          Baseline or observed value is unavailable for this anomaly.
        </div>
      ) : (
        <Plot
          data={data as any}
          layout={{
            autosize: true,
            height: 260,
            margin: { t: 20, r: 20, b: 45, l: 50 },
            paper_bgcolor: "transparent",
            plot_bgcolor: "transparent",
            font: {
              family: "DM Sans, system-ui, sans-serif",
              size: 12,
              color: "#8BA5BC",
            },
            showlegend: false,
            yaxis: {
              title: { text: variable },
              gridcolor: "rgba(139, 165, 188, 0.15)",
              zerolinecolor: "rgba(139, 165, 188, 0.2)",
            },
            xaxis: {
              gridcolor: "rgba(139, 165, 188, 0.05)",
              zerolinecolor: "rgba(139, 165, 188, 0.1)",
            },
            annotations: [
              {
                x: 0.5,
                y: 1.08,
                xref: "paper",
                yref: "paper",
                text: subtitle,
                showarrow: false,
                font: { size: 11, color: "#8BA5BC" },
              },
            ],
          }}
          config={{ displayModeBar: false, responsive: true }}
          useResizeHandler
          style={{ width: "100%", height: "100%" }}
        />
      )}
    </div>
  );
}
