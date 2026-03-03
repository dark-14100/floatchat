# FloatChat — Feature 7: Geospatial Exploration
## Implementation Phases

---

## Plan: Feature 7 — Geospatial Exploration Implementation Phases

**TL;DR — 10 sequential phases delivering Feature 7's 6 backend endpoints (including the new basin-polygons endpoint) and 8 frontend components. Backend phases (1–2) complete first, then frontend phases (3–8) build up from types/API client to map core to panels to integration. Phases 9–10 cover tests. Every phase is independently verifiable. Key decisions: `variables_available` dropped for v1, `ExplorationMap` built fresh, circle tool implemented outside `RegionSelector`, `layout-shell.tsx` added to permitted modifications, auto-submit for deep links.**

---

### Phase 1 — Backend: Configuration & Router Registration

**Goal:** Add all Feature 7 config settings and register an empty map router so the server starts cleanly with the new routes visible.

**Files to create:**
- `backend/app/api/v1/map.py` — Router skeleton with `APIRouter(prefix="/map", tags=["Map"])`, no endpoint implementations yet

**Files to modify:**
- `backend/app/config.py` — Add 6 new settings under a `# Geospatial Map (Feature 7)` section: `MAP_ACTIVE_FLOATS_CACHE_TTL` (300), `MAP_NEAREST_FLOATS_DEFAULT_N` (10), `MAP_NEAREST_FLOATS_MAX_N` (50), `MAP_NEAREST_FLOATS_DEFAULT_RADIUS_KM` (500), `MAP_RADIUS_QUERY_MAX_KM` (2000), `MAP_FLOAT_DETAIL_LAST_PROFILES` (5)
- `backend/app/main.py` — Import and register map router at `/api/v1`

**Tasks:**
1. Add the 6 settings to the `Settings` class in `config.py` after the Feature 5 section
2. Create `map.py` with an empty `APIRouter` and a single placeholder `GET /active-floats` that returns `[]`
3. Import map router in `main.py` and register with `app.include_router(map_router, prefix="/api/v1")`
4. Verify the server starts and `/docs` shows the Map tag

**PRD requirements fulfilled:** FR-06 (partially — router created and mounted)

**Depends on:** Nothing

**Done when:**
- [ ] Server starts without errors
- [ ] `GET /api/v1/map/active-floats` returns `200 []`
- [ ] `/docs` shows the Map tag with the placeholder endpoint
- [ ] All 6 config settings are accessible via `settings.MAP_*`
- [ ] No existing tests broken

---

### Phase 2 — Backend: All 6 Endpoints

**Goal:** Implement all 6 map endpoints with Redis caching, structlog logging, and correct response shapes.

**Files to modify:**
- `backend/app/api/v1/map.py` — Full implementation of all 6 endpoints

**Tasks:**
1. Add `_get_redis_client()` helper (replicate pattern from `chat.py`)
2. Implement `GET /active-floats` — query `mv_float_latest_position` joined with `floats` for `float_type`; Redis cache with key `map_active_floats` and TTL from settings; fields: `platform_number`, `float_type`, `latitude`, `longitude`, `last_seen`; graceful Redis failure
3. Implement `GET /nearest-floats` — query params: `lat`, `lon`, `n` (default from settings, capped silently at max), `max_distance_km`; join `mv_float_latest_position` with `floats` for `float_type`; use `ST_DWithin` + `ST_Distance`; return HTTP 400 for invalid lat/lon; fields: `float_id`, `platform_number`, `float_type`, `latitude`, `longitude`, `distance_km` (rounded 1dp), `last_seen`; NO `variables_available` (dropped per B1 resolution)
4. Implement `POST /radius-query` — body: `lat`, `lon`, `radius_km`, `variables` (optional); HTTP 400 if radius exceeds `MAP_RADIUS_QUERY_MAX_KM`; call `get_profiles_by_radius(lat, lon, radius_km * 1000, None, None, db=db)` from DAL; return `profile_count`, `float_count`, `profiles` (metadata only), `bbox`
5. Implement `GET /floats/{platform_number}` — query `floats` table joined with `mv_float_latest_position` for last position, `COUNT(*)` from profiles for `cycle_count`, `MIN/MAX(timestamp)` for date range; HTTP 404 if not found; also return last N profiles (from settings) with pressure + temperature data for mini chart; response: all float metadata + `recent_profiles` list
6. Implement `GET /basin-floats` — query param: `basin_name`; call `resolve_region_name(basin_name, db)` from `search/discovery.py`; on `ValueError`, return HTTP 400 with the exception message; direct query on `mv_float_latest_position` joined with `floats` using `ST_Within` against the resolved region's `geom`; return list of float position dicts
7. Implement `GET /basin-polygons` (new, per B6 resolution) — query all rows from `ocean_regions` table; use `ST_AsGeoJSON(geom)` to serialize geometries; return a GeoJSON FeatureCollection with `region_name` and `region_id` as feature properties; Redis cache with key `map_basin_polygons` and TTL 3600
8. Add Pydantic request/response models for all endpoints
9. Add structlog request param + latency logging to every endpoint

**PRD requirements fulfilled:** FR-01, FR-02, FR-03, FR-04, FR-05, FR-06, FR-11 (backend polygon data)

**Depends on:** Phase 1

**Done when:**
- [ ] `GET /api/v1/map/active-floats` returns float positions with `float_type`
- [ ] Second call to `/active-floats` within 5 min returns cached data (verify via structlog `cache_hit` log)
- [ ] `GET /api/v1/map/nearest-floats?lat=7.9&lon=80.7&n=5` returns up to 5 floats ordered by distance
- [ ] `GET /api/v1/map/nearest-floats` with `n=100` silently caps to 50
- [ ] `GET /api/v1/map/nearest-floats?lat=200&lon=0` returns HTTP 400
- [ ] `POST /api/v1/map/radius-query` with `radius_km=100` returns `profile_count` and `float_count`
- [ ] `POST /api/v1/map/radius-query` with `radius_km=3000` returns HTTP 400
- [ ] `GET /api/v1/map/floats/{valid_platform}` returns metadata + `recent_profiles`
- [ ] `GET /api/v1/map/floats/NONEXISTENT` returns HTTP 404
- [ ] `GET /api/v1/map/basin-floats?basin_name=Arabian+Sea` returns floats
- [ ] `GET /api/v1/map/basin-floats?basin_name=xyzabc` returns HTTP 400 with suggestions
- [ ] `GET /api/v1/map/basin-polygons` returns GeoJSON FeatureCollection with 15 features
- [ ] All endpoints log request params and latency via structlog
- [ ] No existing tests broken

---

### Phase 3 — Frontend: Dependencies, Types & API Client

**Goal:** Install `@turf/turf`, copy the geography lookup file, create the typed API client for all map endpoints, and add type shims for leaflet-draw.

**Files to create:**
- `frontend/lib/mapQueries.ts` — Typed async functions for all 6 endpoints, all response type interfaces
- `frontend/lib/geographyLookup.json` — Copy of `backend/data/geography_lookup.json` with a top comment note about manual sync
- `frontend/types/leaflet-draw.d.ts` — Type shim for leaflet-draw if needed for `tsc --noEmit`

**Files to modify:**
- `frontend/package.json` — Add `@turf/turf` dependency

**Tasks:**
1. Add `@turf/turf` to dependencies in `package.json` and run `npm install`
2. Copy `geography_lookup.json` to `frontend/lib/geographyLookup.json`
3. Create `mapQueries.ts` following the exact pattern of `lib/api.ts` — same `apiFetch` wrapper, same `ApiError` class (reuse via import), same header pattern
4. Define TypeScript interfaces: `ActiveFloat`, `NearestFloat`, `RadiusQueryResult`, `FloatDetail`, `RecentProfile`, `BasinFloat`, `BasinPolygonsResponse` (GeoJSON FeatureCollection)
5. Implement 6 typed functions: `getActiveFloats()`, `getNearestFloats(lat, lon, n?, maxDistanceKm?)`, `postRadiusQuery(lat, lon, radiusKm, variables?)`, `getFloatDetail(platformNumber)`, `getBasinFloats(basinName)`, `getBasinPolygons()`
6. Add `leaflet-draw.d.ts` type shim declaring the `react-leaflet-draw` module if TypeScript errors appear
7. Verify `tsc --noEmit` passes

**PRD requirements fulfilled:** Supports all frontend FRs (types and API client are prerequisites)

**Depends on:** Phase 2 (endpoints must exist for types to match)

**Done when:**
- [ ] `npm install` succeeds with `@turf/turf` installed
- [ ] `geographyLookup.json` exists in `frontend/lib/` with all entries from the backend copy
- [ ] `mapQueries.ts` exports all 6 functions with correct TypeScript types
- [ ] No `any` types anywhere in `mapQueries.ts`
- [ ] `tsc --noEmit` passes
- [ ] `npm run build` passes

---

### Phase 4 — Frontend: Map Page & ExplorationMap + MapToolbar

**Goal:** Create the `/map` route with a full-screen layout, the `ExplorationMap` core component with clustered float markers, and the `MapToolbar` overlay. Suppress `SessionSidebar` on `/map`.

**Files to create:**
- `frontend/app/map/page.tsx` — `"use client"`, full-screen layout with 240px left panel + map, page-level state management, dynamic imports of all map components with `{ ssr: false }`
- `frontend/components/map/ExplorationMap.tsx` — Full-screen `react-leaflet` map, OSM tiles + attribution, active float markers via `react-leaflet-cluster`, `CircleMarker` color from CSS variables at runtime (`getComputedStyle`), map click handler, float marker click handler, callback props to parent
- `frontend/components/map/MapToolbar.tsx` — Absolutely positioned toolbar with zoom, draw circle toggle, draw polygon toggle, reset view, float type filter (All/BGC/Core)

**Files to modify:**
- `frontend/app/layout-shell.tsx` — Add `usePathname()`, conditionally render `SessionSidebar` only when `pathname !== '/map'`

**Tasks:**
1. Modify `layout-shell.tsx`: import `usePathname` from `next/navigation`, add `const pathname = usePathname()`, wrap `<SessionSidebar>` in `{pathname !== '/map' && <SessionSidebar ... />}`. Mobile hamburger header should also be suppressed on `/map`.
2. Create `app/map/page.tsx` with `"use client"`, page-level state (`activePanel`, `selectedPoint`, `selectedFloat`, `drawnRadius`, `activeBasin`, `activeFloats`, `filteredFloats`, `floatTypeFilter`), dynamic imports of `ExplorationMap`, `MapToolbar`, and all panel components with `{ ssr: false }`
3. Create `ExplorationMap.tsx`: `MapContainer` with OSM `TileLayer` + attribution (Hard Rule 2), on mount call `getActiveFloats()`, render `CircleMarker` inside `MarkerClusterGroup`, read `--color-ocean-primary` and `--color-coral` from CSS vars at runtime (Hard Rule 3), handle map click (not on marker) → callback `onMapClick(lat, lon)`, handle marker click → callback `onFloatClick(platformNumber)`, expose `flyTo` method via ref or callback
4. Create `MapToolbar.tsx`: absolutely positioned `z-1000`, icon buttons using `lucide-react` (`ZoomIn`, `ZoomOut`, `Circle`, `Pentagon`, `RotateCcw`, `Filter`), float type filter as local state that filters markers passed to parent via callback, ARIA labels on all buttons
5. Wire everything together: `page.tsx` passes callbacks to `ExplorationMap`, toolbar filter state controls which markers are shown

**PRD requirements fulfilled:** FR-07, FR-09, FR-10 (marker interaction started), FR-18

**Depends on:** Phase 3

**Done when:**
- [ ] `/map` loads full-screen with a Leaflet map filling viewport minus 240px panel
- [ ] `SessionSidebar` is NOT visible on `/map`
- [ ] `SessionSidebar` IS still visible on `/chat/*` and `/dashboard`
- [ ] All active floats load and render as clustered circle markers
- [ ] Core floats use `--color-ocean-primary` color, BGC floats use `--color-coral`
- [ ] Clicking the ocean (not a marker) logs the click coordinates to console (nearest panel not yet wired)
- [ ] Clicking a marker logs the platform number to console (detail panel not yet wired)
- [ ] MapToolbar visible in top-right with all 6 buttons
- [ ] Float type filter (All/BGC/Core) filters markers client-side without re-fetching
- [ ] OSM attribution "© OpenStreetMap contributors" is visible (Hard Rule 2)
- [ ] No Leaflet CSS import in any component file (Hard Rule 4)
- [ ] `tsc --noEmit` passes
- [ ] `npm run build` passes

---

### Phase 5 — Frontend: Panel Components (Nearest, Detail, Radius)

**Goal:** Implement the three dynamic panels that appear in the left panel based on map interactions.

**Files to create:**
- `frontend/components/map/NearestFloatsPanel.tsx` — Title with coordinates, scrollable float card list (up to 10), each card: platform number, float type badge, distance km, last seen; click card → highlight + open detail; "Query in Chat" button; "Clear" button
- `frontend/components/map/FloatDetailPanel.tsx` — Header: platform number + type badge + active status dot; sections: location (decimal + DMS), program info, last active + cycle count; mini chart: dynamically imported `OceanProfileChart` in 200px wrapper with CSS hiding export buttons; "Open in Chat" + "View trajectory" buttons
- `frontend/components/map/RadiusQueryPanel.tsx` — Center coordinates, radius slider (50–2000km, step 50), debounced re-query on slider change (300ms), result preview (profile count, float count), "Query in Chat" button, "Clear" button

**Files to modify:**
- `frontend/app/map/page.tsx` — Wire panel rendering based on `activePanel` state, connect map callbacks to panel display

**Tasks:**
1. Create `NearestFloatsPanel`: receives `point`, `floats`, `onFloatSelect`, `onClear`; renders float cards using design spec tokens (`--color-bg-surface` for cards, `--color-ocean-primary` for badge); "Query these floats in chat" button generates query string per FR-20 format (`"show recent profiles from floats {wmo1}, {wmo2}, {wmo3}"`) and navigates via `router.push('/chat?prefill=' + encodeURIComponent(query))`
2. Create `FloatDetailPanel`: receives `platformNumber`, `onClose`; fetches `getFloatDetail(platformNumber)` on mount; shows loading shimmer while fetching; renders all metadata sections; mini chart wrapped in `div.mini-chart-wrapper` with CSS to hide export buttons; dynamically import `OceanProfileChart` with `{ ssr: false }`; "Open in Chat" navigates with query `"show all profiles from float {platform_number}"`; "View trajectory" navigates with `"show trajectory of float {platform_number}"`
3. Create `RadiusQueryPanel`: receives `center`, `initialRadiusKm`, `onRadiusChange`, `onClear`; fetches `postRadiusQuery` on mount and on debounced slider change; slider uses HTML range input styled with design tokens; "Query in Chat" generates `"show profiles within {radius}km of latitude {lat}, longitude {lon}"`
4. Implement circle drawing in `ExplorationMap`: use leaflet-draw circle handler directly (separate from `RegionSelector`); on circle drawn, extract center + radius, set `activePanel = 'radius'` and `drawnRadius` state; display radius label on map
5. Wire `page.tsx`: when `activePanel === 'nearest'`, render `NearestFloatsPanel`; when `'detail'`, render `FloatDetailPanel`; when `'radius'`, render `RadiusQueryPanel`; connect `onMapClick` → `getNearestFloats()` → set panel; connect `onFloatClick` → set panel; connect circle draw → set panel
6. Add CSS rule for mini chart export suppression (either in `globals.css` or as inline style in the wrapper)

**PRD requirements fulfilled:** FR-10, FR-12, FR-13, FR-14, FR-15, FR-19 (partially — deep link buttons navigate), FR-20 (query formats)

**Depends on:** Phase 4

**Done when:**
- [ ] Clicking ocean → `NearestFloatsPanel` appears with up to 10 nearest floats
- [ ] Clicking a float card in nearest panel highlights the marker and opens `FloatDetailPanel`
- [ ] `FloatDetailPanel` shows all metadata, mini chart at 200px, no export buttons visible
- [ ] Drawing a circle → `RadiusQueryPanel` appears with profile/float count
- [ ] Adjusting radius slider redraws circle and re-queries (debounced)
- [ ] "Query in Chat" buttons generate correct FR-20 format strings
- [ ] "Clear" buttons dismiss panels and remove overlays
- [ ] All panels use design spec CSS variable tokens (no hardcoded hex)
- [ ] `tsc --noEmit` passes
- [ ] `npm run build` passes

---

### Phase 6 — Frontend: BasinFilterPanel & SearchBar

**Goal:** Implement the persistent basin filter sidebar section with polygon overlays and the search bar with coordinate/place-name resolution.

**Files to create:**
- `frontend/components/map/BasinFilterPanel.tsx` — Two groups: 7 major basins + 8 sub-regions (all 15 from DB); each is a clickable button; on click: call `getBasinFloats(basinName)`, pass results up via `onBasinSelect` callback, highlight active basin; show float count after query returns; "Show all" resets filter; always visible — never hides a region (Hard Rule 10)
- `frontend/components/map/SearchBar.tsx` — Input at top of left panel; resolution priority: (1) decimal coordinate regex, (2) DMS regex, (3) ocean basin name match against the 15 region names, (4) geography lookup JSON import match, (5) "Location not found" error; on resolve: callback `onLocationResolved(lat, lon, label)` → parent triggers `flyTo` + nearest floats query

**Files to modify:**
- `frontend/app/map/page.tsx` — Add `SearchBar` at top of left panel, `BasinFilterPanel` below it; wire basin polygon overlay rendering in `ExplorationMap`
- `frontend/components/map/ExplorationMap.tsx` — Add basin polygon overlay rendering: fetch `getBasinPolygons()` on mount, render as semi-transparent `Polygon` layers; highlight active basin's polygon; accept `activeBaisin` prop; accept `flyTo` command via prop/ref

**Tasks:**
1. Create `BasinFilterPanel`: hardcode the 15 basin names in two groups matching the DB exactly; each item renders as a button with region name; clicking calls `getBasinFloats`; float count badge appears after response; active basin gets highlight styling (`--color-ocean-primary` text + left border); "Show all basins" link at top clears filter
2. Create `SearchBar`: input field with `Search` lucide icon; `onChange` + `onKeyDown` (Enter) handling; coordinate regex: `/^(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)$/`; DMS regex for degree notation; basin name matching: case-insensitive check against the 15 region names; geography lookup: import `geographyLookup.json`, compute center from `lat_min/max/lon_min/max`; display inline error for no match
3. Update `ExplorationMap`: call `getBasinPolygons()` on mount; parse GeoJSON FeatureCollection; render each basin as a `GeoJSON` or `Polygon` layer with default faint border (opacity 0.15); when `activeBasin` prop is set, fill that basin's polygon with `--color-ocean-lighter` at 30% opacity, border at full `--color-ocean-primary`
4. Wire in `page.tsx`: `SearchBar` at top of left panel → `onLocationResolved` triggers `flyTo` + nearest floats; `BasinFilterPanel` below → `onBasinSelect` updates `activeBasin` state + filters map markers; basin polygon highlight updates via prop
5. Ensure `SearchBar` triggers nearest floats query after every successful resolution

**PRD requirements fulfilled:** FR-11, FR-16, FR-17

**Depends on:** Phase 5

**Done when:**
- [ ] `BasinFilterPanel` renders all 15 regions in two groups (Hard Rule 10)
- [ ] Clicking "Arabian Sea" filters map to show only Arabian Sea floats and highlights the polygon
- [ ] "Show all basins" resets to all floats
- [ ] Float count badge appears next to each basin after query
- [ ] `SearchBar` resolves `"12.5, 80.2"` as coordinates and flies to that location
- [ ] `SearchBar` resolves `"Arabian Sea"` as a basin and triggers basin filter
- [ ] `SearchBar` resolves `"chennai"` (not in basin list) via geography lookup and flies to its center
- [ ] `SearchBar` shows "Location not found" for `"xyzabc"`
- [ ] Basin polygons render as faint overlays on the map
- [ ] Active basin polygon fills with highlight color
- [ ] `tsc --noEmit` passes
- [ ] `npm run build` passes

---

### Phase 7 — Frontend: SessionSidebar Nav Link

**Goal:** Add a "Map" navigation link to the `SessionSidebar` alongside the existing "Dashboard" link.

**Files to modify:**
- `frontend/components/layout/SessionSidebar.tsx` — Import `Map` icon from `lucide-react`; add a `<Link href="/map">` with Map icon + "Map" label alongside the existing Dashboard link in the sidebar footer

**Tasks:**
1. Add `Map` to the lucide-react icon import
2. Add a `<Link href="/map">` element in the sidebar footer, styled identically to the existing Dashboard link, positioned above or next to it
3. Verify the link navigates to `/map` correctly

**PRD requirements fulfilled:** FR-08

**Depends on:** Phase 4 (map page must exist)

**Done when:**
- [ ] "Map" link with Map icon is visible in the sidebar footer
- [ ] Clicking it navigates to `/map`
- [ ] Styling matches the existing "Dashboard" link exactly
- [ ] `tsc --noEmit` passes
- [ ] `npm run build` passes

---

### Phase 8 — Frontend: Deep Link Integration

**Goal:** Enable the `/chat/[session_id]` page to read a `prefill` query parameter and auto-submit it as a query on mount.

**Files to modify:**
- `frontend/app/chat/[session_id]/page.tsx` — Import `useSearchParams`, read `prefill` param on mount, auto-submit via `submitQuery` in a `useEffect`

**Tasks:**
1. Import `useSearchParams` from `next/navigation`
2. Add `const searchParams = useSearchParams()` inside the component
3. Add a `useEffect` that runs once on mount: if `searchParams.get('prefill')` is non-null and non-empty, decode it and call `submitQuery(decoded)`. Guard with a ref to prevent double-submission on StrictMode re-renders.
4. Verify all 5 FR-20 query formats work end-to-end: navigate from map panel → chat → query auto-submits → Feature 4 processes it

**PRD requirements fulfilled:** FR-19, FR-20

**Depends on:** Phase 5 (panels generate query strings), Phase 7 (navigation exists)

**Done when:**
- [ ] Navigating to `/chat/{session_id}?prefill=show+active+floats+in+the+Arabian+Sea` auto-submits the query
- [ ] The user message appears in the chat thread
- [ ] The SSE stream starts (thinking → interpreting → executing → results)
- [ ] Without `prefill` param, the chat page behaves exactly as before (no regression)
- [ ] Double-submission does not occur in React StrictMode
- [ ] `tsc --noEmit` passes
- [ ] `npm run build` passes

---

### Phase 9 — Backend: Tests

**Goal:** Write all backend test cases from PRD §9.1 plus tests for the new basin-polygons endpoint.

**Files to create:**
- `backend/tests/test_map_api.py` — All test cases using the same patterns and fixtures as existing Feature test files

**Tasks:**
1. Set up test fixtures: mock `mv_float_latest_position` with test data, mock `floats` table, mock `ocean_regions` with at least one region polygon, mock Redis client
2. Test `GET /active-floats` returns list with required fields only (`platform_number`, `float_type`, `latitude`, `longitude`, `last_seen`)
3. Test `GET /active-floats` returns cached response on second call within TTL
4. Test `GET /nearest-floats?lat=7.9&lon=80.7&n=5` returns up to 5 floats ordered by distance ascending
5. Test `GET /nearest-floats` with `n` exceeding max returns capped results (50)
6. Test `GET /nearest-floats?lat=200&lon=0` returns HTTP 400
7. Test `POST /radius-query` with valid body returns `profile_count` and `float_count`
8. Test `POST /radius-query` with `radius_km=3000` returns HTTP 400 with correct message
9. Test `GET /floats/{platform_number}` returns correct metadata + `recent_profiles`
10. Test `GET /floats/NONEXISTENT` returns HTTP 404
11. Test `GET /basin-floats?basin_name=Arabian+Sea` returns floats within the polygon
12. Test `GET /basin-floats?basin_name=unknown_place` returns HTTP 400 with suggestions
13. Test `GET /basin-polygons` returns GeoJSON FeatureCollection with correct structure

**PRD requirements fulfilled:** §9.1 (all 10 original test cases + 3 additional)

**Depends on:** Phase 2

**Done when:**
- [ ] All 13 tests pass
- [ ] `pytest tests/test_map_api.py -v` exits with 0
- [ ] No existing tests broken (`pytest` full suite passes)

---

### Phase 10 — Frontend: Tests

**Goal:** Write all frontend test cases from PRD §9.2.

**Files to create or modify:**
- `frontend/tests/test_map.test.tsx` — or a suitable test file matching the existing test convention

**Tasks:**
1. Test `SearchBar` parses `"12.5, 80.2"` as a valid coordinate pair → returns `{lat: 12.5, lon: 80.2}`
2. Test `SearchBar` resolves `"Arabian Sea"` to correct coordinates via geography lookup
3. Test `SearchBar` shows "Location not found" for unrecognised input
4. Test FR-20 query format generation: verify all 5 pre-filled string patterns produce the expected output for given inputs
5. Test `BasinFilterPanel` renders all 15 named regions
6. Test deep link: verify that mounting the chat page with `prefill=test+query` triggers `submitQuery` with `"test query"`

**PRD requirements fulfilled:** §9.2 (all 6 test cases)

**Depends on:** Phases 5, 6, 8

**Done when:**
- [ ] All 6 tests pass
- [ ] `npm run test` exits cleanly
- [ ] `tsc --noEmit` passes
- [ ] `npm run build` passes

---

## Verification

After all 10 phases:
- Full backend test suite: `pytest -v` — all pass
- Full frontend test/build: `npm run test && tsc --noEmit && npm run build` — all pass
- Manual smoke test: load `/map`, see clustered floats, click ocean → nearest panel, click marker → detail panel with mini chart, draw circle → radius panel with query, select basin → filter + polygon highlight, search "Chennai" → fly to + nearest, click "Query in Chat" → navigates to chat and auto-submits, sidebar shows Map link

---

## Decisions

- `variables_available` dropped from all responses (v1) — expensive aggregation, not critical for map
- `ExplorationMap` built fresh — `FloatPositionMap` designed for inline chat, wrong interaction model
- Circle tool separate from `RegionSelector` — `RegionSelector` doesn't support circles
- `OceanProfileChart` export buttons hidden via CSS wrapper — no modification to Feature 6 component
- `geography_lookup.json` copied to frontend as JSON module import — zero network overhead
- All 15 basin names shown as-is from DB — North/South not combined
- No URL state, no pagination, no URL radius persistence for v1
- Auto-submit `prefill` param — `ChatInput` doesn't expose `setValue`
- `layout-shell.tsx` added to permitted modifications — conditional sidebar suppression on `/map`
- New `GET /basin-polygons` endpoint added (6th) — required for FR-11 polygon overlays
