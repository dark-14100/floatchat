"use client";

/**
 * VisualizationPanel — Orchestrator for Feature 6.
 *
 * Determines the correct chart / map component based on result shape
 * and renders it. All child components are dynamically imported with
 * `{ ssr: false }` so Plotly and Leaflet never execute on the server
 * (Hard Rule 1).
 *
 * Usage: pass as `chartComponent` prop in ChatMessage.
 * Does NOT import or depend on any Feature 5 component.
 *
 * Leaflet CSS must be imported globally in layout.tsx (Hard Rule 4).
 */

import React, { useMemo } from "react";
import dynamic from "next/dynamic";
import { Pin } from "lucide-react";
import { detectShape } from "@/lib/detectShape";
import { useChatStore } from "@/store/chatStore";
import type {
    VisualizationPanelProps,
    ChartRow,
    ChartType,
} from "@/types/visualization";

// Shared loading component for dynamic imports
function LoadingPlaceholder() {
    return (
        <div
            className="flex h-[300px] w-full items-center justify-center rounded-lg border border-border/40 bg-muted/30"
            role="status"
            aria-label="Loading visualization"
        >
            <div className="flex flex-col items-center gap-2 text-muted-foreground">
                <div className="h-6 w-6 animate-spin rounded-full border-2 border-current border-t-transparent" />
                <span className="text-xs">Loading chart…</span>
            </div>
        </div>
    );
}

// ── Dynamic imports (SSR disabled — Hard Rule 1) ──────────────────────────

const OceanProfileChart = dynamic(
    () => import("./OceanProfileChart"),
    { ssr: false, loading: LoadingPlaceholder },
);

const TSdiagram = dynamic(
    () => import("./TSdiagram"),
    { ssr: false, loading: LoadingPlaceholder },
);

const SalinityOverlayChart = dynamic(
    () => import("./SalinityOverlayChart"),
    { ssr: false, loading: LoadingPlaceholder },
);

const TimeSeriesChart = dynamic(
    () => import("./TimeSeriesChart"),
    { ssr: false, loading: LoadingPlaceholder },
);

const FloatPositionMap = dynamic(
    () => import("./FloatPositionMap"),
    { ssr: false, loading: LoadingPlaceholder },
);

const FloatTrajectoryMap = dynamic(
    () => import("./FloatTrajectoryMap"),
    { ssr: false, loading: LoadingPlaceholder },
);

// ── Variable column helpers ───────────────────────────────────────────────

const VARIABLE_COLUMNS = [
    "temperature",
    "temp",
    "salinity",
    "psal",
    "dissolved_oxygen",
    "chlorophyll",
    "nitrate",
    "ph",
] as const;

/** Detect which variable columns are present in the data. */
function findVariableColumns(columns: string[]): string[] {
    const lc = columns.map((c) => c.toLowerCase());
    return lc.filter((c) =>
        (VARIABLE_COLUMNS as readonly string[]).includes(c),
    );
}

// ── Component ─────────────────────────────────────────────────────────────

export default function VisualizationPanel({
    columns,
    rows,
    messageId,
}: VisualizationPanelProps) {
    const addWidget = useChatStore((s) => s.addWidget);
    const pinnedWidgets = useChatStore((s) => s.pinnedWidgets);

    // Detect shape once per data change
    const shape = useMemo(
        () => detectShape(columns, rows as ChartRow[]),
        [columns, rows],
    );

    const isPinned = useMemo(
        () => pinnedWidgets.some((widget) => widget.id === messageId),
        [pinnedWidgets, messageId],
    );

    const canPin = !isPinned && pinnedWidgets.length < 10 && shape.primary !== null;

    const handlePin = () => {
        if (!shape.primary || !canPin) return;
        addWidget({
            id: messageId,
            label: `Result ${messageId.slice(0, 8)}`,
            chartType: shape.primary,
            columns,
            rows,
        });
    };

    // Nothing to render for unrecognised shapes (FR-07)
    if (shape.primary === null) {
        return null;
    }

    return (
        <div
            className="mt-3 w-full"
            aria-label={`Visualization: ${shape.primary}`}
        >
            <div className="mb-2 flex justify-end">
                <button
                    type="button"
                    onClick={handlePin}
                    disabled={!canPin}
                    className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] px-2.5 py-1 text-xs font-medium text-[var(--color-text-secondary)] transition-colors duration-normal hover:bg-[var(--color-bg-subtle)] disabled:cursor-not-allowed disabled:opacity-60"
                    aria-label="Pin visualization to dashboard"
                >
                    <Pin size={12} />
                    <span>
                        {isPinned
                            ? "Pinned"
                            : pinnedWidgets.length >= 10
                                ? "Dashboard Full"
                                : "Pin to Dashboard"}
                    </span>
                </button>
            </div>
            {renderChart(shape.primary, shape.secondary ?? null, columns, rows as ChartRow[])}
        </div>
    );
}

// ── Render dispatcher ─────────────────────────────────────────────────────

function renderChart(
    primary: ChartType,
    secondary: ChartType | null,
    columns: string[],
    rows: ChartRow[],
): React.ReactNode {
    const baseProps = { rows, columns };

    switch (primary) {
        case "salinity_overlay":
            return (
                <SalinityOverlayChart
                    {...baseProps}
                    startAsTSDiagram={secondary === "ts_diagram"}
                />
            );

        case "ts_diagram":
            return <TSdiagram {...baseProps} showDensityContours={false} />;

        case "ocean_profile": {
            const vars = findVariableColumns(columns);
            return <OceanProfileChart {...baseProps} variables={vars} />;
        }

        case "time_series":
            return <TimeSeriesChart {...baseProps} />;

        case "float_position_map": {
            const colorVar = findVariableColumns(columns)[0] ?? undefined;
            return <FloatPositionMap {...baseProps} colorVariable={colorVar} />;
        }

        case "float_trajectory_map":
            return <FloatTrajectoryMap {...baseProps} />;

        // RegionSelector is triggered by user action, not auto-detected
        case "region_selector":
            return null;

        default:
            return null;
    }
}
