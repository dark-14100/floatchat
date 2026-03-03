# FloatChat — Feature 7: Geospatial Exploration
## Product Requirements Document (PRD)

**Feature Name:** Geospatial Exploration
**Version:** 1.0
**Status:** Ready for Development
**Owner:** Full-Stack Engineering
**Depends On:** Feature 2 (PostGIS spatial queries, `ocean_regions` table, DAL), Feature 4 (NL Query Engine — deep link to chat with pre-filled query), Feature 5 (Chat Interface — map selection triggers a new chat query), Feature 6 (Visualization — `RegionSelector` component is reused here, `FloatPositionMap` and `FloatTrajectoryMap` are reused)

---

## 1. Purpose & Background

### 1.1 What Problem Does This Solve?
Some researchers do not start from a question — they start from a place. They want to look at a map, find an area of interest, and explore what float data exists there. Natural language is not always the right starting point for spatial discovery.

Feature 7 gives researchers a full map-first interface. They can click anywhere on the ocean, draw a radius, select a named basin, or type a location name — and the system immediately shows them what float data exists in that area. From there, a single click sends that spatial context to the chat interface as a pre-filled query, bridging visual exploration with the NL query pipeline.

### 1.2 What This Feature Is
A dedicated `/map` route in the Next.js frontend with a full-screen Leaflet map and a supporting FastAPI backend module, consisting of:
- A full-screen map showing all active float latest positions from the database
- Click-to-query: clicking a point on the map finds the N nearest active floats
- Radius query tool: draw a circle and query all profiles within it
- Ocean basin filter: sidebar list of named regions that filter the map view
- Coordinate and place-name search bar using the geography lookup table from Feature 4
- Float detail panel: click a float marker to see its metadata and a mini profile chart
- Deep link: any map selection can be sent to the chat interface as a pre-filled NL query

### 1.3 What This Feature Is Not
- It is not a replacement for the chat interface — it is a complementary discovery tool
- It does not generate SQL directly — it passes spatial context to Feature 4 via the chat
- It does not render full visualization dashboards — those are Feature 6. It renders lightweight inline previews only.
- It does not ingest data — that is Feature 1

### 1.4 Relationship to Other Features
- Feature 2 provides `ocean_regions` table polygons, `mv_float_latest_position` materialized view, and the `get_profiles_by_radius` and `get_profiles_by_basin` DAL functions that power the backend endpoints
- Feature 4's geography lookup table (`data/geography_lookup.json`) is reused for place-name resolution — no new geocoding service is required for v1
- Feature 5's chat interface is the destination for deep links — the map passes a pre-filled query string to `/chat` with spatial context
- Feature 6's `RegionSelector` component is reused as the circle/polygon draw tool. `FloatPositionMap` rendering patterns are reused for the full-screen map.
- Feature 9 (Guided Query Assistant) may embed the map as a region selection widget in future

---

## 2. Goals & Success Criteria

### 2.1 Goals
- Load all active float latest positions on the map in under 3 seconds
- Allow researchers to visually discover float coverage before writing a query
- Make spatial selection feel direct and immediate — click, draw, filter, and results appear inline
- Deep link any map selection to the chat with a one-click action
- Work correctly on tablet-sized screens (768px+)

### 2.2 Success Criteria

| Criterion | Target |
|---|---|
| Map initial load (all float positions) | < 3 seconds |
| Nearest floats query latency (p95) | < 500ms |
| Radius query result latency (p95) | < 1 second |
| Basin filter apply latency | < 300ms (client-side polygon filter) |
| Place-name resolution latency | < 100ms (local lookup, no API call) |
| Float detail panel load latency | < 500ms |
| Deep link to chat | One click, pre-filled query, < 200ms navigation |

---

## 3. User Stories

### 3.1 Researcher
- **US-01:** As a researcher, I want to open a map and immediately see where all active ARGO floats are located, so that I can understand data coverage before asking questions.
- **US-02:** As a researcher, I want to click anywhere on the ocean and see the nearest active floats, so that I can discover data near a location of interest.
- **US-03:** As a researcher, I want to draw a circle on the map and see all float profiles within it, so that I can define my study area visually.
- **US-04:** As a researcher, I want to click a named ocean basin in the sidebar and filter the map to that region, so that I can focus on a specific ocean area without knowing coordinates.
- **US-05:** As a researcher, I want to type "Arabian Sea" or "Chennai" in the search bar and have the map navigate there, so that I can find locations without knowing their coordinates.
- **US-06:** As a researcher, I want to click a float marker and see its metadata, last profile date, and available variables, so that I can decide if this float has the data I need.
- **US-07:** As a researcher, I want a "Query in Chat" button on any map selection, so that I can send my spatial filter directly to the chat interface without retyping it.

---

## 4. Functional Requirements

### 4.1 Backend: New Spatial Endpoints

**FR-01 — Nearest Floats Endpoint**
```
GET /api/v1/map/nearest-floats?lat={lat}&lon={lon}&n={n}&max_distance_km={km}
```
Returns the N nearest active floats to a given point. Default `n=10`, max `n=50`. Default `max_distance_km=500`. Uses `ST_DWithin` + `ST_Distance` against `mv_float_latest_position`. Returns: list of dicts with `float_id`, `platform_number`, `float_type`, `latitude`, `longitude`, `distance_km` (rounded to 1 decimal), `last_seen` (ISO timestamp), `variables_available` (list of variable names).

**FR-02 — Radius Query Endpoint**
```
POST /api/v1/map/radius-query
Body: { "lat": float, "lon": float, "radius_km": float, "variables": list[str] (optional) }
```
Returns all float profiles within the radius. Uses `get_profiles_by_radius` from Feature 2's DAL. Max radius: 2000km. Default variables: all available. Returns: `profile_count`, `float_count`, `profiles` (list of profile metadata — not full measurement data), `bbox` (bounding box of results as GeoJSON). This endpoint returns metadata only — measurement data is retrieved by Feature 4 when the user sends the query to chat.

**FR-03 — Float Detail Endpoint**
```
GET /api/v1/map/floats/{platform_number}
```
Returns full metadata for a single float. Fields: `platform_number`, `wmo_id`, `float_type`, `deployment_date`, `deployment_lat`, `deployment_lon`, `country`, `program`, `last_profile_date`, `last_latitude`, `last_longitude`, `cycle_count`, `variables_available`, `active_date_range_start`, `active_date_range_end`. Also returns the last 5 depth profiles as lightweight data for the mini chart (pressure + temperature only, no full measurement set).

**FR-04 — Basin Floats Endpoint**
```
GET /api/v1/map/basin-floats?basin_name={name}
```
Returns all active float latest positions within a named ocean basin. Uses `get_profiles_by_basin` from Feature 2's DAL and the `ocean_regions` table. Applies fuzzy name matching via `resolve_region_name` from Feature 3's discovery module. Returns: list of float position dicts (same shape as FR-01 response, without `distance_km`).

**FR-05 — All Active Floats Endpoint**
```
GET /api/v1/map/active-floats
```
Returns the latest position of all active floats from `mv_float_latest_position`. Used to populate the initial map load. Response is intentionally lightweight: only `platform_number`, `float_type`, `latitude`, `longitude`, `last_seen`. No measurement data. Cached in Redis with key `map_active_floats` and TTL of 300 seconds (5 minutes) — this endpoint will be called on every map load.

**FR-06 — Backend Router**
Create `app/api/v1/map.py` FastAPI router. Mount at `/api/v1/map` in `main.py`. All endpoints use `get_readonly_db()`. No auth required for read endpoints in v1. All endpoints log request params and latency via structlog.

### 4.2 Frontend: Map Page

**FR-07 — Map Route**
Add `/map` route to the Next.js app at `app/map/page.tsx`. Full-screen layout — the map fills the entire viewport. The `SessionSidebar` is not rendered on this page — instead a compact left panel (240px wide) sits alongside the full-screen map.

**FR-08 — Navigation**
Add a "Map" link to `SessionSidebar.tsx` alongside the existing "Dashboard" link added in Feature 6. Use the `Map` icon from `lucide-react`.

**FR-09 — Full-Screen Map Component (`ExplorationMap`)**
The primary map component. Built with `react-leaflet`. Takes up the full available width (viewport minus the 240px left panel). Minimum height: 100vh.

Base tiles: OpenStreetMap. Attribution: "© OpenStreetMap contributors" — legally required. No Mapbox, no API key needed.

On mount: fetches all active float positions from `GET /api/v1/map/active-floats`. Renders each float as a `CircleMarker` using `react-leaflet-cluster` for clustering at low zoom levels. Float marker color: `--color-ocean-primary` for core floats, `--color-coral` for BGC floats (this color distinction helps researchers identify the more data-rich floats).

Map click handler: on click anywhere on the ocean (not on a marker), triggers the nearest floats query (FR-01) and opens the `NearestFloatsPanel`.

**FR-10 — Float Marker Interaction**
Clicking a float marker opens the `FloatDetailPanel` (FR-14) for that float. Hovering a marker shows a minimal tooltip with `platform_number` and `float_type`. Clicked marker is highlighted with a larger radius and white outline while its detail panel is open.

**FR-11 — Basin Polygon Overlay**
Load all ocean basin polygons from `ocean_regions` via a new lightweight endpoint or the existing Feature 3 discovery module. Render each basin as a semi-transparent `Polygon` layer on the map. Default state: polygon borders are very faint (opacity 0.15) and do not fill. When a basin is selected in the sidebar, its polygon fills with `--color-ocean-lighter` at 30% opacity and the border brightens to full `--color-ocean-primary`.

**FR-12 — Drawn Region Overlay**
Reuse Feature 6's `RegionSelector` component embedded inside `ExplorationMap`. When the user draws a circle or polygon, the drawn region is persisted in local component state and displayed on the map. The drawn region feeds the `RadiusQueryPanel` (FR-15).

For circle drawing specifically: use `leaflet-draw`'s circle tool. After drawing, display the radius in km as a label on the map.

### 4.3 Frontend: Left Panel Components

**FR-13 — `NearestFloatsPanel` Component**
Appears in the left panel after a map click. Shows: "Nearest floats to [{lat}, {lon}]" as the title, a scrollable list of up to 10 float cards. Each float card shows: platform number, float type badge, distance in km, last seen date. Clicking a card highlights that float on the map and opens `FloatDetailPanel`. "Query these floats in chat" button at the bottom — generates a pre-filled query string like "show profiles from floats {list of platform numbers}" and navigates to `/chat` with the query pre-filled. A "Clear" button dismisses the panel and removes the click marker from the map.

**FR-14 — `FloatDetailPanel` Component**
Appears in the left panel when a float marker is clicked. Header: platform number in large type, float type badge, active status indicator (green dot if last seen within 30 days). Sections:
- **Location:** last known lat/lon, formatted as decimal degrees + DMS notation
- **Program:** country, deployment program name, deployment date
- **Variables:** list of available variables as colored chips (temperature, salinity, oxygen, etc.)
- **Last active:** formatted date, cycle count
- **Mini profile chart:** a compact `OceanProfileChart` (from Feature 6, dynamically imported) showing the last temperature profile only. Height 200px. No export buttons on the mini version.
- **"Open in Chat" button:** sends "show profiles from float {platform_number}" to chat. Navigates to `/chat`.
- **"View trajectory" button:** triggers `FloatTrajectoryMap` (from Feature 6) in a modal overlay showing the full float path.

**FR-15 — `RadiusQueryPanel` Component**
Appears in the left panel after a circle is drawn on the map. Shows: circle center coordinates, radius in km (with a slider to adjust from 50km to 2000km — adjusting the slider redraws the circle and re-queries). Result preview: profile count, float count. "Query in Chat" button generates "show profiles within {radius}km of {lat}, {lon}" and navigates to `/chat`. "Clear" button removes the circle and dismisses the panel.

**FR-16 — `BasinFilterPanel` Component**
A persistent section in the left panel showing the ocean basin list. Two levels: major basins (Indian Ocean, Pacific Ocean, Atlantic Ocean, Southern Ocean, Arctic Ocean) and sub-regions (Arabian Sea, Bay of Bengal, Caribbean Sea, Mediterranean Sea, Red Sea, Persian Gulf, Gulf of Mexico, Laccadive Sea). Each basin is a clickable item. Clicking: filters the map to show only floats in that basin (calls FR-04 endpoint), highlights the basin polygon on the map, and shows float count for that basin. "Show all basins" link resets the filter. Active basin is visually highlighted in the panel.

**FR-17 — `SearchBar` Component**
A search input at the top of the left panel. Accepts: decimal lat/lon pairs (e.g., `12.5, 80.2`), degree notation (e.g., `12°30'N 80°12'E`), or place names (e.g., "Chennai", "Arabian Sea"). Resolution priority:
1. Detect if input is a coordinate pair — parse and use directly
2. Detect if input matches an ocean basin name — apply basin filter
3. Look up in Feature 4's geography lookup (`data/geography_lookup.json`) for place name resolution
4. If no match, show "Location not found" — no external geocoding API in v1

On successful resolution: animate the map to the resolved location (`flyTo` with zoom 6), drop a temporary location pin, and trigger nearest floats query. No third-party geocoding service in v1.

**FR-18 — `MapToolbar` Component**
A compact floating toolbar overlaid on the top-right of the map. Contains:
- Zoom in / zoom out buttons (supplement the built-in Leaflet controls)
- "Draw circle" toggle — activates the circle draw tool
- "Draw polygon" toggle — activates the polygon draw tool (reuses `RegionSelector`)
- "Reset view" button — returns map to default center and zoom
- Float type filter toggle: "All floats" / "BGC only" / "Core only" — filters the markers shown without re-fetching from the server

### 4.4 Frontend: Deep Link System

**FR-19 — Deep Link to Chat**
Every "Query in Chat" or "Open in Chat" button navigates to `/chat` with a query pre-filled in the chat input. Use Next.js router with a query parameter: `/chat?prefill={encoded_query_string}`. Feature 5's chat page reads the `prefill` parameter on mount and populates the `ChatInput` with the value. This requires a small additive change to Feature 5's `/chat/[session_id]/page.tsx` — read and apply the `prefill` param on mount.

**FR-20 — Pre-filled Query Formats**
The map generates pre-filled queries in these formats:
- Nearest floats: `"show recent profiles from floats {wmo1}, {wmo2}, {wmo3}"`
- Radius query: `"show profiles within {radius}km of latitude {lat}, longitude {lon}"`
- Basin filter: `"show active floats in the {basin_name}"`
- Float detail: `"show all profiles from float {platform_number}"`
- Trajectory: `"show trajectory of float {platform_number}"`

These are designed to be valid inputs to Feature 4's NL query engine and geography resolver.

---

## 5. Non-Functional Requirements

### 5.1 Performance
- Initial map load with all active floats must complete under 3 seconds. The `active-floats` endpoint returns lightweight data (5 fields per float) and is Redis-cached for 5 minutes.
- Marker clustering is mandatory — rendering 4,000+ individual markers without clustering will freeze the browser
- Basin polygon loading: load all 15 polygons on map mount, render as lightweight GeoJSON layers
- Float detail endpoint must return in under 500ms — it fetches float metadata + last 5 profiles

### 5.2 Responsive Design
- The map view is functional on screens 768px and wider (tablet and up)
- Below 768px: left panel collapses to a bottom sheet that slides up when triggered
- Map fills full viewport width on mobile when the panel is collapsed

### 5.3 Accessibility
- All map controls in `MapToolbar` have ARIA labels
- `NearestFloatsPanel`, `FloatDetailPanel`, `RadiusQueryPanel`, and `BasinFilterPanel` are keyboard navigable
- Color-only distinctions (core vs BGC float color) are supplemented by the float type badge text

---

## 6. New Configuration Settings

Add to `Settings` class in `backend/app/config.py`:
- `MAP_ACTIVE_FLOATS_CACHE_TTL` — default `300` (5 minutes Redis cache for active floats endpoint)
- `MAP_NEAREST_FLOATS_DEFAULT_N` — default `10`
- `MAP_NEAREST_FLOATS_MAX_N` — default `50`
- `MAP_NEAREST_FLOATS_DEFAULT_RADIUS_KM` — default `500`
- `MAP_RADIUS_QUERY_MAX_KM` — default `2000`
- `MAP_FLOAT_DETAIL_LAST_PROFILES` — default `5` (how many recent profiles for the mini chart)

---

## 7. File Structure

```
floatchat/
├── backend/
│   ├── app/
│   │   └── api/
│   │       └── v1/
│   │           └── map.py              # FastAPI router for all map endpoints
│   └── tests/
│       └── test_map_api.py
└── frontend/
    ├── app/
    │   └── map/
    │       └── page.tsx                # /map route — full-screen map layout
    ├── components/
    │   └── map/
    │       ├── ExplorationMap.tsx
    │       ├── NearestFloatsPanel.tsx
    │       ├── FloatDetailPanel.tsx
    │       ├── RadiusQueryPanel.tsx
    │       ├── BasinFilterPanel.tsx
    │       ├── SearchBar.tsx
    │       └── MapToolbar.tsx
    └── lib/
        └── mapQueries.ts               # API client functions for map endpoints
```

Files to modify:
- `backend/app/config.py` — add 6 new map settings
- `backend/app/main.py` — register map router
- `frontend/package.json` — verify all Leaflet packages installed (from Feature 6); add `turf` if needed
- `frontend/app/layout.tsx` — Leaflet CSS already imported from Feature 6; verify
- `frontend/components/layout/SessionSidebar.tsx` — add "Map" nav link
- `frontend/app/chat/[session_id]/page.tsx` — read `prefill` query param on mount (additive only)

---

## 8. Frontend Dependencies

All Leaflet packages were installed in Feature 6. Verify they are present before proceeding:
- `leaflet` 1.x ✓ (Feature 6)
- `react-leaflet` 4.x ✓ (Feature 6)
- `react-leaflet-cluster` 2.x ✓ (Feature 6)
- `leaflet-draw` 1.x ✓ (Feature 6)
- `react-leaflet-draw` 0.x ✓ (Feature 6)

New packages to add:
- `@turf/turf` — for frontend geospatial calculations (circle radius display, polygon area, coordinate validation). Used in `RadiusQueryPanel` for converting Leaflet circle radius to km and validating drawn regions.

---

## 9. Testing Requirements

### 9.1 Backend Tests (`test_map_api.py`)
- `GET /api/v1/map/active-floats` returns list with required fields only
- `GET /api/v1/map/active-floats` returns cached response on second call within TTL
- `GET /api/v1/map/nearest-floats?lat=7.9&lon=80.7&n=5` returns 5 floats ordered by distance
- `GET /api/v1/map/nearest-floats` with `n` exceeding max returns capped results
- `POST /api/v1/map/radius-query` with valid body returns `profile_count` and `float_count`
- `POST /api/v1/map/radius-query` with radius exceeding max returns HTTP 400
- `GET /api/v1/map/floats/{platform_number}` returns correct float metadata
- `GET /api/v1/map/floats/{platform_number}` with unknown platform returns HTTP 404
- `GET /api/v1/map/basin-floats?basin_name=Arabian+Sea` returns floats within the polygon
- `GET /api/v1/map/basin-floats?basin_name=unknown_place` returns HTTP 400 with suggestions

### 9.2 Frontend Tests
- `SearchBar` parses `"12.5, 80.2"` as a valid coordinate pair
- `SearchBar` resolves "Arabian Sea" to correct coordinates via geography lookup
- `SearchBar` shows "Location not found" for unrecognised input
- `FR-20` query formats produce the expected pre-filled strings for all five cases
- `BasinFilterPanel` renders all 15 named regions
- Deep link: navigating to `/chat?prefill=test+query` populates the chat input on mount

---

## 10. Dependencies & Prerequisites

| Dependency | Reason | Must Be Ready Before |
|---|---|---|
| Feature 2 complete | `mv_float_latest_position`, DAL functions, `ocean_regions` table | Day 1 |
| Feature 3 complete | `resolve_region_name` fuzzy matching for basin endpoint | Day 1 |
| Feature 4 complete | Geography lookup file for place-name search | Day 1 |
| Feature 5 complete | Chat `prefill` param and deep link destination | Day 1 |
| Feature 6 complete | `RegionSelector`, `FloatPositionMap`, `OceanProfileChart` (mini chart) | Day 1 |
| Leaflet packages installed | All installed in Feature 6 | Already done |

---

## 11. Out of Scope for v1.0

- External geocoding API (OpenCage, Mapbox) — geography lookup file is sufficient for v1
- Satellite imagery base tiles — OpenStreetMap only in v1
- 3D ocean depth visualisation on the map
- Animated float trajectory playback directly on the map
- Real-time float position updates (WebSocket feed)
- Custom user-defined regions saved across sessions
- Offline map support

---

## 12. Open Questions

| # | Question | Owner | Due |
|---|---|---|---|
| Q1 | Should `ExplorationMap` reuse `FloatPositionMap` from Feature 6 as a base, or be built as a new full-screen component that shares only utilities? `FloatPositionMap` was designed for inline chat rendering — the full-screen map has different interaction requirements. | Frontend | Before ExplorationMap implementation |
| Q2 | The `active-floats` endpoint could return thousands of floats. Should it paginate or return all at once? Clustering handles the rendering side, but the network payload could be large. A rough estimate: 4,000 floats × 5 fields ≈ 200KB JSON — acceptable for a one-time load. | Backend | Before FR-05 implementation |
| Q3 | Should the `/map` page have its own URL-based state (e.g., `/map?lat=7.9&lon=80.7&zoom=6`) so researchers can share a map view via URL? | Product | Before map route implementation |
| Q4 | The `FloatDetailPanel` mini chart uses `OceanProfileChart` from Feature 6. This pulls in the full Plotly bundle just for a 200px chart. Should a lightweight SVG sparkline be used instead for the mini chart? | Frontend | Before FloatDetailPanel implementation |
| Q5 | Should the drawn radius circle persist in the URL so that refreshing the page restores the drawn region and query result? | Product | Before RadiusQueryPanel implementation |
