# FloatChat — Feature 6: Data Visualization Dashboard
## Product Requirements Document (PRD)

**Feature Name:** Data Visualization Dashboard
**Version:** 1.0
**Status:** Ready for Development
**Owner:** Frontend Engineering
**Depends On:** Feature 5 (Chat Interface — `ChatMessage` component slots must exist), Feature 4 (NL Query Engine — result data shape is the input to all charts), Feature 2 (Database — column names and types determine how data is shaped for charts)

---

## 1. Purpose & Background

### 1.1 What Problem Does This Solve?
Raw query results are tables of numbers. A researcher asking "show temperature profiles near Sri Lanka in 2023" receives a table of pressure/temperature pairs. Without visualization, they must export the data and plot it themselves in Python or MATLAB — negating the purpose of FloatChat.

Feature 6 closes this gap. Every query result that contains plottable data is automatically visualized inline in the chat thread. Charts and maps appear immediately after the result table, without navigation, without export, without additional steps.

### 1.2 What This Feature Is
A suite of purpose-built React visualization components for oceanographic data, consisting of:
- Four chart types covering the core ARGO analysis patterns: vertical ocean profiles, T-S diagrams, time series, and salinity overlays
- Three map views: float trajectories, float positions with variable-encoded color, and an interactive region selector
- A `VisualizationPanel` that automatically selects and renders the appropriate visualization based on query result shape
- Chart export functionality (PNG and SVG) on every chart
- cmocean colorscales implemented as custom Plotly color arrays for oceanographic accuracy
- A standalone dashboard view where multiple visualizations can be arranged in a grid

### 1.3 What This Feature Is Not
- It does not query the database — it only visualizes data already returned by Feature 4
- It does not replace the `ResultTable` component from Feature 5 — charts appear alongside tables, not instead of them
- It does not handle data export — that is Feature 8
- It does not provide the chat interface — that is Feature 5

### 1.4 Relationship to Other Features
- Feature 4 produces the result data that Feature 6 visualizes. The column names from Feature 4's result (`pressure`, `temperature`, `salinity`, `latitude`, `longitude`, `juld_timestamp`, `platform_number`, etc.) are the inputs to every chart component.
- Feature 5 provides the `chartComponent` and `mapComponent` slots in `ChatMessage`. Feature 6 fills these slots — the `VisualizationPanel` is passed as the `chartComponent` prop.
- Feature 7 (Geospatial Exploration) handles the full-featured interactive map. Feature 6's map components are simpler inline visualizations — they display results, they do not drive queries. The `RegionSelector` from Feature 6 emits a GeoJSON polygon that the chat interface passes back to Feature 4.
- Feature 8 (Export) exports raw data. Feature 6's chart export (PNG/SVG) is visual export — a screenshot of the chart, not the underlying data.

---

## 2. Goals & Success Criteria

### 2.1 Goals
- Automatically render the right chart for every query result without requiring user action
- Make oceanographic patterns immediately visible: thermoclines, mixed layers, water mass characteristics
- Use standard oceanographic conventions: inverted depth axis, cmocean colormaps, dbar units
- Render charts in under 1 second for results under 10,000 data points
- Allow researchers to export any chart as a publication-quality PNG or SVG

### 2.2 Success Criteria

| Criterion | Target |
|---|---|
| Chart render time for 10,000 rows | < 1 second |
| Chart render time for 100,000 rows | < 3 seconds |
| Auto-selection accuracy (correct chart for result shape) | ≥ 95% of standard query patterns |
| PNG export resolution | ≥ 300 DPI equivalent |
| Mobile render: charts viewable on 375px width | Yes — horizontally scrollable |
| cmocean colormaps visually match reference | Yes — verified against cmocean Python library |

---

## 3. User Stories

### 3.1 Researcher
- **US-01:** As a researcher, I want to see a depth-vs-temperature plot automatically appear after a temperature query, so that I can immediately identify thermoclines without exporting data.
- **US-02:** As a researcher, I want to see a T-S diagram after a query that returns both temperature and salinity, so that I can identify water masses.
- **US-03:** As a researcher, I want to see float positions on a map after any spatial query, so that I can understand the geographic distribution of the data.
- **US-04:** As a researcher, I want to export any chart as a PNG for my publication or report, without leaving the chat interface.
- **US-05:** As a researcher, I want to draw a region on a map and have FloatChat query the data within that region, so that I can explore areas not easily described in text.
- **US-06:** As a researcher, I want to see float trajectories colored by time, so that I can understand how floats moved through an area.
- **US-07:** As a researcher, I want multiple floats overlaid on the same chart in different colors, so that I can compare profiles from different locations or times.

### 3.2 System (Internal Consumer)
- **US-08:** As Feature 5 (`ChatMessage`), I need the `VisualizationPanel` to be passable as a `chartComponent` or `mapComponent` prop so that it renders inline in the conversation thread.
- **US-09:** As Feature 7 (Geospatial Exploration), I need the `RegionSelector` component to be independently importable and reusable in the full map view.

---

## 4. Functional Requirements

### 4.1 Charting Library

**FR-01 — Charting Library Selection**
Use Plotly.js (`react-plotly.js` wrapper) for all chart types. Do not use Recharts, Chart.js, D3, or Victory. Plotly is chosen for: built-in PNG/SVG export, WebGL-accelerated rendering for large datasets, built-in zoom/pan/hover, and the ability to define custom colorscales matching cmocean.

**FR-02 — Mapping Library Selection**
Use Leaflet.js (`react-leaflet`) for all map views. Do not use Mapbox GL JS. Leaflet is open-source with no API key requirement, sufficient for inline result display, and well-supported with React.

**FR-03 — cmocean Colorscales**
Implement the following cmocean colorscales as Plotly-compatible color arrays (lists of `[position, "rgb(r,g,b)"]` pairs). Each must be sampled at 11 stops and verified visually against the cmocean reference:
- `thermal` — for temperature (blue-green-yellow-red)
- `haline` — for salinity (purple-blue-green-yellow)
- `deep` — for depth/pressure (white-blue-dark navy)
- `dense` — for density (blue-gray-purple)
- `oxy` — for dissolved oxygen (dark red-orange-light yellow)
- `matter` — for turbidity/matter (dark red-orange-yellow)

Store all colorscales in a single file `lib/colorscales.ts` as exported constants. All chart components import from this file — never define colorscale arrays inline in a component.

### 4.2 Data Shape Detection

**FR-04 — `detectResultShape(columns, rows)` Function**
A pure function that inspects the column names and first few rows of a query result and returns a `ResultShape` discriminated union. The `VisualizationPanel` calls this function to decide which visualization to render.

Result shapes and their detection rules:

| Shape | Detection Rule | Visualization |
|---|---|---|
| `vertical_profile` | Has `pressure` AND (`temperature` OR `salinity`) | `OceanProfileChart` |
| `ts_diagram` | Has `pressure` AND `temperature` AND `salinity` | `TSdiagram` (overrides `vertical_profile`) |
| `time_series` | Has `juld_timestamp` AND one variable column AND no `pressure` | `TimeSeriesChart` |
| `float_positions` | Has `latitude` AND `longitude` AND no `pressure` | `FloatPositionMap` |
| `float_trajectory` | Has `latitude` AND `longitude` AND `juld_timestamp` AND `platform_number` | `FloatTrajectoryMap` (overrides `float_positions`) |
| `unknown` | None of the above | No visualization, show `ResultTable` only |

Rules for `ts_diagram`: takes priority over `vertical_profile` when both temperature and salinity are present alongside pressure. Rules for `float_trajectory`: takes priority over `float_positions` when `platform_number` and `juld_timestamp` are both present.

**FR-05 — Detection is Non-Blocking**
If `detectResultShape` throws for any reason, return `unknown`. Never let detection failure prevent the result table from rendering.

### 4.3 VisualizationPanel

**FR-06 — `VisualizationPanel` Component**
The top-level orchestrator component. Accepts props: `rows`, `columnNames`, `resultShape` (optional — if not provided, calls `detectResultShape` internally). Renders:
1. The appropriate chart or map component based on `resultShape`
2. Nothing additional if `resultShape === 'unknown'` — the `ResultTable` is already rendered by Feature 5

`VisualizationPanel` must be importable as a standalone component and passable as a prop. It must not import or depend on any Feature 5 components.

**FR-07 — No Visualization for Unknown Shape**
When `resultShape === 'unknown'`, `VisualizationPanel` renders `null`. It does not show an error or placeholder. The result table from Feature 5 is sufficient.

### 4.4 Chart Components

**FR-08 — `OceanProfileChart` Component**
Vertical ocean profile. Layout: X-axis = variable value, Y-axis = pressure in dbar with axis **inverted** (0 at top, max at bottom — deeper is lower on the plot). This is the standard oceanographic convention.

Supported variables: temperature (`temperature`), salinity (`salinity`), dissolved oxygen (`dissolved_oxygen`), chlorophyll (`chlorophyll`), nitrate (`nitrate`), pH (`ph`). If multiple variable columns are present, render dual X-axes (primary on bottom, secondary on top).

Color: when multiple profiles are present (multiple `platform_number` values), color-code traces by `platform_number`. When a single float is plotted, use the `thermal` colorscale mapped to depth.

Axis labels: X-axis label derived from column name — map `temperature` → "Temperature (°C)", `salinity` → "Salinity (PSU)", `dissolved_oxygen` → "Dissolved Oxygen (μmol/kg)", `pressure` → "Pressure (dbar)". Y-axis always: "Pressure (dbar)".

Hover tooltip: shows `pressure`, variable value, `platform_number`, and `juld_timestamp` formatted as a date.

**FR-09 — `TSdiagram` Component**
Temperature-Salinity scatter plot. X-axis = salinity (PSU), Y-axis = temperature (°C). Points colored by `pressure` using the `deep` colorscale. Colorbar shown on the right.

Interactive: zoom and pan enabled. Point hover shows temperature, salinity, pressure, platform_number, and timestamp.

Density contours: optionally overlay sigma-t (potential density) contour lines on the T-S space. The contour calculation must be done client-side using the simplified equation of state. This is optional for v1 — render if feasible, skip if complex, but do not block the T-S diagram on it.

**FR-10 — `TimeSeriesChart` Component**
Line chart. X-axis = `juld_timestamp` formatted as dates. Y-axis = the variable column value. If multiple `platform_number` values exist in the results, render one line per float, color-coded.

Filterable by depth: accept a `maxPressure` prop (default: no filter). When provided, only plot points where `pressure < maxPressure`. This enables "surface only" time series.

Axis labels: X-axis "Date", Y-axis derived from column name using the same mapping as `OceanProfileChart`.

Hover tooltip: date, value, platform_number.

**FR-11 — `SalinityOverlayChart` Component**
Same as `OceanProfileChart` but always renders temperature and salinity overlaid on the same plot with dual X-axes. Temperature on the primary (bottom) X-axis, salinity on the secondary (top) X-axis. Used when the query returns both variables together and the detected shape is `vertical_profile` (not `ts_diagram`).

`VisualizationPanel` selects `SalinityOverlayChart` over `OceanProfileChart` when both `temperature` and `salinity` columns are present but `ts_diagram` is not triggered (i.e., no `pressure` column, or `ts_diagram` detection is explicitly overridden).

### 4.5 Map Components

**FR-12 — `FloatPositionMap` Component**
Leaflet map showing float positions as circle markers. Base tile layer: OpenStreetMap. Each marker positioned at `latitude`, `longitude`.

Color encoding: if a variable column is present alongside lat/lon (e.g., `temperature`, `salinity`), color the markers using the appropriate cmocean colorscale. Include a colorbar legend below or beside the map. If no variable column, use a flat color (ocean blue).

Clustering: use `react-leaflet-cluster` to cluster markers at low zoom levels. This is essential for large result sets — rendering 10,000 individual markers without clustering causes browser freezes.

Marker click: show a popup with all column values for that row.

Map bounds: automatically fit the map view to the bounding box of all markers on load.

**FR-13 — `FloatTrajectoryMap` Component**
Leaflet map showing float paths as polylines. Each unique `platform_number` gets its own polyline, ordered by `juld_timestamp` ascending.

Color gradient: each polyline is colored with a blue-to-red gradient from earliest to latest timestamp. Implement this by rendering the polyline as a series of short line segments, each colored according to its temporal position.

Markers: render a circle marker at each position point. On click, show a popup with `juld_timestamp`, `latitude`, `longitude`, and `platform_number`. On the start point, show a distinct marker (e.g., filled square). On the end point, show a distinct marker (e.g., filled circle with outline).

Map bounds: fit to all trajectories on load.

**FR-14 — `RegionSelector` Component**
A Leaflet map with a polygon draw tool. The researcher draws a bounding box or freehand polygon on the map. When drawing is complete, the component calls an `onRegionSelected(geojson: GeoJSONPolygon)` callback prop with the selected region as a GeoJSON polygon.

Drawing tool: use `react-leaflet-draw` for the drawing interaction. Support both rectangle and polygon drawing. Only one region can be active at a time — drawing a new region replaces the previous one.

After selection, display the drawn polygon as a filled semi-transparent overlay. Show a "Use this region" button that calls `onRegionSelected`. Show a "Clear" button that removes the polygon.

The `onRegionSelected` callback is wired in Feature 5's chat interface to inject the region into a new query.

**FR-15 — Map Tile Attribution**
All map components must display OpenStreetMap attribution in the bottom-right corner as required by the OSM tile usage policy. Attribution text: "© OpenStreetMap contributors".

### 4.6 Chart Export

**FR-16 — PNG Export**
Every chart component (not map components) must have a "Download PNG" button. Plotly's built-in `downloadImage` function handles this. PNG dimensions: 1200×800 pixels at scale 2 (effectively 300 DPI equivalent). File name: `floatchat_{chart_type}_{timestamp}.png`.

**FR-17 — SVG Export**
Every chart component must also have a "Download SVG" button. Plotly's `downloadImage` with format `svg`. SVG export is resolution-independent and suitable for publication figures. File name: `floatchat_{chart_type}_{timestamp}.svg`.

**FR-18 — Export Button Placement**
Export buttons appear in the top-right corner of each chart as a small icon button row. Use a download icon from `lucide-react`. Do not use Plotly's built-in modebar for export — implement custom buttons so the UI is consistent with the rest of FloatChat. Hide Plotly's default modebar (`displayModeBar: false`).

### 4.7 Dashboard View

**FR-19 — Standalone Dashboard Route**
Add a `/dashboard` route to the Next.js app. The dashboard displays multiple visualizations simultaneously in a draggable, resizable grid layout using `react-grid-layout`.

**FR-20 — Dashboard Data Source**
The dashboard reads visualization data from the Zustand store — specifically from the last N query results stored in the chat session. It does not make its own API calls. If no query results exist in the store, the dashboard shows an empty state with instructions to run queries in the chat first.

**FR-21 — Grid Layout**
Default grid: 3 columns, each visualization occupies 1 column by default. Researchers can drag to reorder and resize to expand a chart to 2 or 3 columns. Use `react-grid-layout`'s `Responsive` component for this. Grid state is stored in local component state — not persisted.

**FR-22 — Dashboard Navigation**
Add a "Dashboard" link in the `SessionSidebar` of Feature 5, below the session list. Navigating to the dashboard does not end the current chat session.

---

## 5. Non-Functional Requirements

### 5.1 Performance
- Charts must render in under 1 second for results under 10,000 data points
- For results between 10,000 and 100,000 data points, use Plotly's WebGL renderer (`scattergl` trace type instead of `scatter`) to maintain acceptable performance
- Map clustering is mandatory for result sets over 500 markers
- All chart components must be lazy-loaded — not included in the initial page bundle

### 5.2 Accessibility
- All charts must have ARIA labels on the chart container
- Export buttons must have descriptive ARIA labels
- Color-only encoding (e.g., float trajectory time gradient) must be supplemented with tooltip information so colorblind users can still access the data

### 5.3 Responsiveness
- Charts are horizontally scrollable on screens below 600px
- Minimum chart height: 300px. Charts do not compress below this on small screens.
- Map components have a minimum height of 300px and expand to fill available width

---

## 6. New Frontend Dependencies

Add to `frontend/package.json`:

| Package | Version | Purpose |
|---|---|---|
| plotly.js | 2.x | Charting engine |
| react-plotly.js | 2.x | React wrapper for Plotly |
| leaflet | 1.x | Map rendering |
| react-leaflet | 4.x | React wrapper for Leaflet |
| react-leaflet-cluster | 2.x | Marker clustering |
| leaflet-draw | 1.x | Polygon draw tool |
| react-leaflet-draw | 0.x | React wrapper for leaflet-draw |
| react-grid-layout | 1.x | Dashboard grid |
| @types/plotly.js | 2.x | TypeScript types for Plotly |
| @types/leaflet | 1.x | TypeScript types for Leaflet |

Do not add the `cmocean` npm package — the colorscales are implemented directly in `lib/colorscales.ts` as Plotly-compatible arrays.

---

## 7. New Configuration Settings

No new backend settings. No new environment variables. All configuration is frontend-only and handled via component props and constants.

Add one frontend constant to `lib/colorscales.ts`:
- `DEFAULT_MAP_CENTER` — `[20.0, 60.0]` (Indian Ocean centroid, appropriate for ARGO data default view)
- `DEFAULT_MAP_ZOOM` — `4`

---

## 8. File Structure

```
floatchat/
└── frontend/
    ├── components/
    │   └── visualization/
    │       ├── VisualizationPanel.tsx
    │       ├── OceanProfileChart.tsx
    │       ├── TSdiagram.tsx
    │       ├── TimeSeriesChart.tsx
    │       ├── SalinityOverlayChart.tsx
    │       ├── FloatPositionMap.tsx
    │       ├── FloatTrajectoryMap.tsx
    │       └── RegionSelector.tsx
    ├── lib/
    │   ├── colorscales.ts          # cmocean colorscale arrays + map constants
    │   └── detectResultShape.ts    # Pure shape detection function
    ├── types/
    │   └── visualization.ts        # ResultShape union + chart prop types
    └── app/
        └── dashboard/
            └── page.tsx            # /dashboard route
```

Files to modify:
- `frontend/app/layout.tsx` — add "Dashboard" link to sidebar (or coordinate with Feature 5's `SessionSidebar`)
- `frontend/package.json` — add new visualization dependencies
- `frontend/store/chatStore.ts` — ensure last N query results are accessible to the dashboard

---

## 9. TypeScript Types

Define in `types/visualization.ts`:

- `ResultShape` — discriminated union: `'vertical_profile' | 'ts_diagram' | 'time_series' | 'float_positions' | 'float_trajectory' | 'unknown'`
- `ChartRow` — `Record<string, string | number | null>` — a single result row
- `VisualizationPanelProps` — `rows`, `columnNames`, `resultShape` (optional)
- `OceanProfileChartProps` — `rows`, `variableColumns` (array of column names to plot), `colorByFloat` (boolean)
- `TSdiagramProps` — `rows`, `showDensityContours` (boolean, default false)
- `TimeSeriesChartProps` — `rows`, `variableColumn`, `maxPressure` (optional)
- `FloatPositionMapProps` — `rows`, `colorVariable` (optional column name)
- `FloatTrajectoryMapProps` — `rows`
- `RegionSelectorProps` — `onRegionSelected: (geojson: GeoJSONPolygon) => void`
- `GeoJSONPolygon` — proper GeoJSON Polygon type with `type: "Polygon"` and `coordinates: number[][][]`
- `ExportFormat` — `'png' | 'svg'`

---

## 10. Testing Requirements

### 10.1 Unit Tests (`test_visualization.ts`)
- Test `detectResultShape` with columns `['pressure', 'temperature']` returns `vertical_profile`
- Test `detectResultShape` with columns `['pressure', 'temperature', 'salinity']` returns `ts_diagram`
- Test `detectResultShape` with columns `['juld_timestamp', 'temperature']` returns `time_series`
- Test `detectResultShape` with columns `['latitude', 'longitude']` returns `float_positions`
- Test `detectResultShape` with columns `['latitude', 'longitude', 'juld_timestamp', 'platform_number']` returns `float_trajectory`
- Test `detectResultShape` with columns `['platform_number', 'cycle_number']` returns `unknown`
- Test `detectResultShape` throwing does not propagate — returns `unknown`

### 10.2 Component Tests
- Test `OceanProfileChart` renders with pressure column inverted (Y-axis max at bottom)
- Test `TSdiagram` renders with temperature on Y and salinity on X
- Test `TimeSeriesChart` renders one line per unique `platform_number`
- Test `VisualizationPanel` renders `null` for `unknown` shape
- Test `RegionSelector` calls `onRegionSelected` callback with valid GeoJSON

### 10.3 Colorscale Tests
- Test all 6 cmocean colorscales are arrays of `[number, string]` tuples
- Test all colorscales start at position 0 and end at position 1
- Test `thermal` colorscale contains expected anchor colors (blue at 0, red at 1)

---

## 11. Dependencies & Prerequisites

| Dependency | Reason | Must Be Ready Before |
|---|---|---|
| Feature 5 complete | `ChatMessage` component with `chartComponent`/`mapComponent` slots must exist | Day 1 |
| Feature 4 complete | Result shape (column names) must be understood to build detection logic | Day 1 |
| Feature 5's Zustand store | Dashboard reads last N results from store | Before dashboard phase |

---

## 12. Out of Scope for v1.0

- Animated charts (e.g., float position evolving over time as animation frames)
- 3D ocean section plots
- Custom colorscale editor in the UI
- Server-side chart rendering (all rendering is client-side)
- Persistent dashboard layouts (grid state is not saved)
- Cross-session comparison (comparing results from different chat sessions)

---

## 13. Open Questions

| # | Question | Owner | Due |
|---|---|---|---|
| Q1 | Should `RegionSelector` be a standalone map or always embedded inside a `ChatMessage`? If it's standalone, it needs its own route. If embedded, it appears after spatial query results with a "Refine this region" button. | Product | Before RegionSelector implementation |
| Q2 | Should the T-S diagram density contours be implemented in v1? The calculation requires the simplified TEOS-10 equation of state client-side. It is a significant addition but greatly increases scientific value. | Backend / Science | Before TSdiagram implementation |
| Q3 | How many recent query results should the dashboard display? All results from the current session, or a fixed cap (e.g., last 10)? | Product | Before dashboard phase |
| Q4 | Should chart interactions (zoom state, selected region) be synced to the Zustand store so they persist when the user navigates away and returns? | Frontend | Before chart component implementation |
| Q5 | Leaflet requires a CSS import (`leaflet/dist/leaflet.css`). In Next.js App Router, global CSS imports must go in `layout.tsx`. Does this conflict with any existing global styles from Feature 5? | Frontend | Before map component implementation |
