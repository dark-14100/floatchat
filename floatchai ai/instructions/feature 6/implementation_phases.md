# Feature 6 — Data Visualization Dashboard: Implementation Phases

> **Status:** Approved  
> **Depends on:** Features 1–5 complete  
> **Scope:** Pure frontend — no new backend work

---

## Pre-Implementation Summary

### Gap Resolutions

| Gap | Resolution |
|-----|-----------|
| A1–A3: Design spec not implemented | Implement full ocean design tokens in Phase 1 (globals.css, tailwind.config.ts, layout.tsx). Backward-compatible mapping keeps Feature 5 working. |
| B1: Rows not stored in chatStore | Add `resultRows: Record<string, ChartRow[]>` to chatStore.ts (Phase 4). |
| C1: RegionSelector placement | Build standalone, don't auto-render. Reserve for Feature 7. |
| C2: T-S density contours | Skip v1. Prop defaults to `false`. |
| C3: Dashboard widget cap | Max 10 pinned widgets. |
| C4: Zoom / pan state | Local to each component, not stored globally. |
| D1: SalinityOverlayChart unreachable | New `salinity_overlay` shape added to detection priority (before `ts_diagram`). T-S diagram accessible via toggle button on overlay chart. |
| D5: ChatThread.tsx modification | NOT modified. Visualization wired internally in ChatMessage.tsx. |
| D6: Row storage approach | Parallel `resultRows` field in chatStore.ts. types/chat.ts NOT modified. |
| E2: page.tsx modification | Permitted — additive `setResultRows` call only. |

### Permitted File Modifications (Existing Files)

| File | Change |
|------|--------|
| `frontend/app/globals.css` | Replace CSS variables with ocean design tokens (Phase 1) |
| `frontend/tailwind.config.ts` | Extend with ocean colors, fonts, shadows, animations (Phase 1) |
| `frontend/app/layout.tsx` | Replace Geist fonts with Google Fonts (Phase 1); add Leaflet CSS import (Phase 4) |
| `frontend/store/chatStore.ts` | Add `resultRows` state + `setResultRows` action (Phase 4) |
| `frontend/components/chat/ChatMessage.tsx` | Import VisualizationPanel via `next/dynamic`, render when data exists (Phase 7) |
| `frontend/app/chat/[session_id]/page.tsx` | Add `setResultRows(id, rows)` after `appendMessage` (Phase 4) |
| `frontend/components/layout/SessionSidebar.tsx` | Add Dashboard nav link between `</ScrollArea>` and `</aside>` (Phase 8) |
| `frontend/package.json` | Add visualization dependencies (Phase 2 — via npm install) |

### Hard Rules (from system prompt)

1. Every visualization component must be loaded with `next/dynamic(() => import(...), { ssr: false })`
2. Never import Plotly or Leaflet at the top level of a server component
3. All new files go under `components/visualization/`, `lib/`, or `types/`
4. Leaflet CSS imported once in `layout.tsx`, nowhere else
5. cmocean colorscales hand-coded in `lib/colorscales.ts` — no npm cmocean package
6. Every chart component accepts a `colorscale` prop defaulting to the appropriate cmocean scale
7. VisualizationPanel is the only component ChatMessage interacts with
8. Dashboard route is `/dashboard`, not nested under `/chat`
9. All components must be typed — no `any`
10. Existing Feature 5 tests must remain green after every phase

---

## Phase 1 — Design System Foundation

**Goal:** Implement the ocean design spec tokens so all subsequent components use the correct palette.

### Files Modified
- `frontend/app/globals.css` — replace CSS custom properties with ocean design tokens (light + dark)
- `frontend/tailwind.config.ts` — extend theme with ocean colors, fonts (display/body/mono), border-radius, box-shadow, keyframes/animation
- `frontend/app/layout.tsx` — replace Geist local fonts with Google Fonts (Fraunces, DM Sans, JetBrains Mono)

### Acceptance Criteria
- All existing shadcn component class names still resolve (backward-compatible variable mapping)
- `tsc --noEmit` passes
- `npm run build` succeeds
- All 45 Feature 5 tests pass
- Light/dark mode toggle works with new tokens

### Design Token Source
- `instructions/floatchat_design_spec.md` §2 (Color System), §3 (Typography), §4 (Spacing & Layout), §5 (Elevation & Shadows), §6 (Motion & Animation)

---

## Phase 2 — Package Installation + TypeScript Types

**Goal:** Install all visualization dependencies and create shared TypeScript types.

### Commands
```bash
npm install plotly.js react-plotly.js leaflet react-leaflet react-leaflet-cluster leaflet-draw react-leaflet-draw react-grid-layout
npm install -D @types/plotly.js @types/leaflet @types/react-grid-layout
```

### Files Created
- `frontend/types/visualization.ts` — all visualization types:
  - `ChartRow` = `Record<string, string | number | boolean | null>`
  - `ChartType` = `"ocean_profile" | "ts_diagram" | "salinity_overlay" | "time_series" | "float_position_map" | "float_trajectory_map" | "region_selector"`
  - `DetectedShape` — output of shape detection
  - `ColorscaleName` — union of cmocean scale names
  - `VisualizationPanelProps`
  - `OceanProfileChartProps`, `TSdiagramProps`, `SalinityOverlayChartProps`, `TimeSeriesChartProps`
  - `FloatPositionMapProps`, `FloatTrajectoryMapProps`, `RegionSelectorProps`
  - `DashboardWidget`

### Acceptance Criteria
- `tsc --noEmit` passes
- `npm run build` succeeds
- All 45 tests pass

---

## Phase 3 — Colorscales Module + Shape Detection

**Goal:** Hand-implement cmocean colorscales and the shape-detection heuristic.

### Files Created
- `frontend/lib/colorscales.ts` — 6 colorscales as Plotly-compatible `[number, string][]` arrays:
  - `THERMAL`, `HALINE`, `DEEP`, `DENSE`, `OXY`, `MATTER`
  - `getColorscale(name: ColorscaleName): Plotly.ColorScale`

- `frontend/lib/detectShape.ts` — column-analysis heuristic:
  - Input: `columns: string[]`, `rows: ChartRow[]` (first 50 rows sampled)
  - Priority order:
    1. Has `latitude` + `longitude` + `juld` / `timestamp` → `float_trajectory_map`
    2. Has `latitude` + `longitude` (no time) → `float_position_map`
    3. Has `temperature` + `salinity` + `pressure`/`depth` → `salinity_overlay`
    4. Has `temperature` + `salinity` (no depth) → `ts_diagram`
    5. Has `pressure`/`depth` + any numeric variable → `ocean_profile`
    6. Has a date column + any numeric variable → `time_series`
    7. Fallback: `null` (no visualization)

### Acceptance Criteria
- Unit tests for `getColorscale` (returns correct array length)
- Unit tests for `detectShape` with mock column sets covering all 7 cases + fallback
- `tsc --noEmit` passes

---

## Phase 4 — Store Update + Leaflet CSS

**Goal:** Wire row persistence so visualization components can access data.

### Files Modified
- `frontend/store/chatStore.ts`:
  - Add state: `resultRows: Record<string, ChartRow[]>`
  - Add action: `setResultRows: (messageId: string, rows: ChartRow[]) => void`
  - Action implementation: `set((s) => ({ resultRows: { ...s.resultRows, [messageId]: rows } }))`

- `frontend/app/chat/[session_id]/page.tsx`:
  - After `appendMessage(sessionId, assistantMsg)` (≈line 150), add:
    ```ts
    setResultRows(assistantMsg.message_id, results.rows);
    ```
  - Import `setResultRows` from chatStore

- `frontend/app/layout.tsx`:
  - Add `import "leaflet/dist/leaflet.css";` (Hard Rule 4 — single import location)

### Acceptance Criteria
- Rows persist in store after SSE completes
- `resultRows[messageId]` is accessible from any component via `useChatStore`
- Leaflet CSS loads globally
- All 45 tests pass
- `npm run build` succeeds

---

## Phase 5 — Chart Components (Plotly)

**Goal:** Build all 4 Plotly-based chart components.

### ⚠️ AGENT REMINDER
> `SalinityOverlayChart` internally imports `TSdiagram` — that import **must** use `next/dynamic` with `{ ssr: false }`, same rule as everywhere else.

### Files Created
- `frontend/components/visualization/OceanProfileChart.tsx`
  - Vertical profile: X = variable value, Y = pressure (inverted axis)
  - Dual X-axis support for temperature + salinity
  - Color-coded by float ID
  - Accepts `colorscale` prop (default: `THERMAL`)
  - Export button (PNG/SVG via Plotly `toImage`)
  - `"use client"` directive

- `frontend/components/visualization/TSdiagram.tsx`
  - Scatter: X = temperature, Y = salinity, color = depth
  - Interactive zoom + hover
  - Accepts `colorscale` prop (default: `DEEP`)
  - Export button
  - `"use client"` directive

- `frontend/components/visualization/SalinityOverlayChart.tsx`
  - Dual-trace vertical profile: temperature + salinity on shared depth axis
  - Toggle button to switch to T-S diagram view (renders TSdiagram via `next/dynamic`)
  - Accepts `colorscale` prop (default: `HALINE`)
  - Export button
  - `"use client"` directive

- `frontend/components/visualization/TimeSeriesChart.tsx`
  - Line chart: X = date, Y = variable
  - Multi-float overlay support
  - Depth filter control (surface = pressure < 10 dbar)
  - Accepts `colorscale` prop (default: `THERMAL`)
  - Export button
  - `"use client"` directive

### Acceptance Criteria
- Each component renders with mock data in a unit test (snapshot or assertion on DOM)
- `tsc --noEmit` passes
- All components use `"use client"` directive
- No top-level Plotly import in any server component
- Export button triggers `Plotly.toImage`

---

## Phase 6 — Map Components (Leaflet)

**Goal:** Build all 3 Leaflet-based map components.

### Files Created
- `frontend/components/visualization/FloatPositionMap.tsx`
  - Marker scatter map of float positions
  - Color-coded by variable value using cmocean `THERMAL` scale
  - Marker clustering at low zoom (via react-leaflet-cluster)
  - Click marker → popup with float details
  - `"use client"` directive

- `frontend/components/visualization/FloatTrajectoryMap.tsx`
  - Polyline tracing float path over time
  - Color gradient: start (blue) → end (red)
  - Click waypoint → popup with cycle details
  - `"use client"` directive

- `frontend/components/visualization/RegionSelector.tsx`
  - Draw tool (rectangle + polygon) on map
  - Emits GeoJSON polygon via `onRegionSelect` callback
  - Built standalone — not auto-rendered by VisualizationPanel
  - Reserved for Feature 7 integration
  - `"use client"` directive

### Acceptance Criteria
- Each component renders without SSR errors
- `tsc --noEmit` passes
- Leaflet CSS is NOT imported in any of these files (loaded from layout.tsx)
- RegionSelector emits valid GeoJSON on draw complete
- All existing tests pass

---

## Phase 7 — VisualizationPanel + ChatMessage Integration

**Goal:** Build the orchestrator and wire it into the chat UI.

### Files Created
- `frontend/components/visualization/VisualizationPanel.tsx`
  - Accepts `columns: string[]`, `rows: ChartRow[]`, `messageId: string`
  - Calls `detectShape(columns, rows)` to determine chart type
  - Renders the correct chart/map component via `next/dynamic`
  - Shows chart-type badge and "No visualization available" fallback
  - Tab bar if multiple visualizations are applicable (e.g., overlay + profile)
  - `"use client"` directive

- `frontend/components/visualization/index.ts`
  - Barrel export for all visualization components

### Files Modified
- `frontend/components/chat/ChatMessage.tsx`:
  - Import VisualizationPanel via `next/dynamic(() => import("../visualization/VisualizationPanel"), { ssr: false })`
  - In `SuccessMessage`, when `message.result_metadata` is non-null:
    - Read `resultRows[message.message_id]` from `useChatStore`
    - If rows exist and length > 0, render `<VisualizationPanel columns={message.result_metadata.columns} rows={rows} messageId={message.message_id} />`
  - Remove old `chartComponent` / `mapComponent` prop rendering (replace with VisualizationPanel)

### Acceptance Criteria
- Chat messages with result data show the correct chart automatically
- Messages without result data show no visualization (no error)
- `tsc --noEmit` passes
- `npm run build` succeeds
- All 45 existing tests pass
- VisualizationPanel is the ONLY component ChatMessage interacts with (Hard Rule 7)

---

## Phase 8 — Dashboard Route + Navigation

**Goal:** Build the `/dashboard` page and add navigation.

### Files Created
- `frontend/app/dashboard/page.tsx`
  - Grid layout using `react-grid-layout`
  - Max 10 pinned widgets
  - Each widget renders a VisualizationPanel with stored data
  - Responsive breakpoints (lg/md/sm)
  - "Pin to Dashboard" button added to VisualizationPanel (stores widget config in Zustand)
  - `"use client"` directive

- `frontend/app/dashboard/layout.tsx`
  - Dashboard layout wrapper (sidebar + content area)

### Store Addition
- `frontend/store/chatStore.ts` (or new `dashboardStore.ts`):
  - `pinnedWidgets: DashboardWidget[]` (max 10)
  - `addWidget`, `removeWidget`, `updateWidgetLayout` actions

### Files Modified
- `frontend/components/layout/SessionSidebar.tsx`:
  - Add Dashboard `Link` with `BarChart2` icon (from lucide-react) between `</ScrollArea>` (line 313) and `</aside>` (line 314)

### Acceptance Criteria
- `/dashboard` route loads without errors
- Widgets can be pinned from chat and appear on dashboard
- Max 10 widget cap enforced
- Grid is draggable and resizable
- Dashboard link visible in sidebar
- All existing tests pass
- `npm run build` succeeds

---

## Phase 9 — Tests + Documentation

**Goal:** Comprehensive test coverage and README update.

### Files Created
- `frontend/tests/test_colorscales.test.ts` — unit tests for all 6 scales
- `frontend/tests/test_detectShape.test.ts` — unit tests for all 7 detection cases + fallback
- `frontend/tests/test_visualization_panel.test.tsx` — render tests for VisualizationPanel with mock data
- `frontend/tests/test_charts.test.tsx` — render tests for all 4 chart components
- `frontend/tests/test_maps.test.tsx` — render tests for all 3 map components
- `frontend/tests/test_dashboard.test.tsx` — dashboard route render + pin/unpin logic

### Files Modified
- `frontend/README.md` — add Feature 6 section documenting:
  - Chart types and when they're auto-selected
  - Dashboard usage
  - Colorscale reference
  - Shape detection rules

### Acceptance Criteria
- All new tests pass
- All 45 existing Feature 5 tests still pass
- `npm run build` succeeds
- `tsc --noEmit` passes
- Total test count ≥ 65

---

## Progress Tracker

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Design System Foundation | ⬜ Not started |
| 2 | Package Installation + TypeScript Types | ⬜ Not started |
| 3 | Colorscales Module + Shape Detection | ⬜ Not started |
| 4 | Store Update + Leaflet CSS | ✅ Complete |
| 5 | Chart Components (Plotly) | ✅ Complete |
| 6 | Map Components (Leaflet) | ✅ Complete |
| 7 | VisualizationPanel + ChatMessage Integration | ⬜ Not started |
| 8 | Dashboard Route + Navigation | ⬜ Not started |
| 9 | Tests + Documentation | ⬜ Not started |

---

## Key Decisions Reference

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Charting library | Plotly.js | PRD specifies Plotly; richer ocean-science chart support |
| Map library | Leaflet.js | PRD specifies Leaflet; lighter than Mapbox, no API key needed |
| Colorscales | Hand-coded in lib/colorscales.ts | Hard Rule 5; avoids cmocean npm dependency |
| Row storage | `resultRows` in chatStore | Avoids modifying types/chat.ts; parallel field |
| Viz orchestration | VisualizationPanel only | Hard Rule 7; single integration point |
| Dashboard cap | 10 widgets | User decision C3 |
| RegionSelector | Standalone, not auto-rendered | Reserve for Feature 7 |
| T-S density contours | Skipped v1 | User decision C2 |
| SalinityOverlayChart shape | `salinity_overlay` priority | User decision D1 |
| Design system | Full implementation in Phase 1 | Enables correct styling for all components |
