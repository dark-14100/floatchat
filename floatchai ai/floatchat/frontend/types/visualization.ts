/* ═══════════════════════════════════════════════════════════════
   Feature 6 — Data Visualization Dashboard: Shared Types
   ═══════════════════════════════════════════════════════════════ */

// ── Row / column primitives ──────────────────────────────────

/** A single data row coming from the SSE results stream. */
export type ChartRow = Record<string, string | number | boolean | null>;

// ── Chart type detection ─────────────────────────────────────

/** All chart / map types the visualization layer can render. */
export type ChartType =
  | "ocean_profile"
  | "ts_diagram"
  | "salinity_overlay"
  | "time_series"
  | "float_position_map"
  | "float_trajectory_map"
  | "region_selector";

/** Output of the shape-detection heuristic (`lib/detectShape.ts`). */
export interface DetectedShape {
  /** Primary chart type to render, or `null` if no visualization applies. */
  primary: ChartType | null;
  /** Optional secondary chart type (e.g. ts_diagram available via toggle). */
  secondary?: ChartType;
}

// ── Colorscales ──────────────────────────────────────────────

/** Names of the hand-coded cmocean colorscales in `lib/colorscales.ts`. */
export type ColorscaleName =
  | "thermal"
  | "haline"
  | "deep"
  | "dense"
  | "oxy"
  | "matter";

// ── Shared prop fragments ────────────────────────────────────

/** Base props every chart / map component receives. */
export interface VisualizationBaseProps {
  rows: ChartRow[];
  columns: string[];
  colorscale?: ColorscaleName;
}

// ── Chart component props ────────────────────────────────────

export interface OceanProfileChartProps extends VisualizationBaseProps {
  /** Variable names to plot on the x-axis (e.g. ["temperature","salinity"]). */
  variables?: string[];
}

export interface TSdiagramProps extends VisualizationBaseProps {
  /** If true, overlay density contour lines (skipped v1, defaults false). */
  showDensityContours?: boolean;
}

export interface SalinityOverlayChartProps extends VisualizationBaseProps {
  /** Start in T-S diagram mode instead of overlay mode. */
  startAsTSDiagram?: boolean;
}

export interface TimeSeriesChartProps extends VisualizationBaseProps {
  /** Maximum pressure (dbar) for depth filtering. Undefined = all depths. */
  maxPressure?: number;
}

// ── Map component props ──────────────────────────────────────

export interface FloatPositionMapProps extends VisualizationBaseProps {
  /** Variable to use for marker color coding (e.g. "temperature"). */
  colorVariable?: string;
}

export interface FloatTrajectoryMapProps extends VisualizationBaseProps {
  /** Column name containing the float identifier for multi-float paths. */
  floatIdColumn?: string;
}

export interface RegionSelectorProps {
  /** Callback fired when the user finishes drawing a region. */
  onRegionSelect: (geojson: GeoJSON.Polygon | GeoJSON.MultiPolygon) => void;
  /** Initial map center [lat, lng]. */
  center?: [number, number];
  /** Initial zoom level. */
  zoom?: number;
}

// ── VisualizationPanel (orchestrator) ────────────────────────

export interface VisualizationPanelProps {
  columns: string[];
  rows: ChartRow[];
  messageId: string;
}

// ── Dashboard ────────────────────────────────────────────────

export interface DashboardWidget {
  /** Unique widget id. */
  id: string;
  /** Human-readable label shown in the widget header. */
  label: string;
  /** Chart type to render. */
  chartType: ChartType;
  /** Column names from the original result. */
  columns: string[];
  /** Snapshot of the data rows. */
  rows: ChartRow[];
  /** react-grid-layout position / size. */
  layout: { x: number; y: number; w: number; h: number };
}
