# FloatChat — Complete Feature Breakdown & Technical Specification

> **Product:** FloatChat — A natural language interface for ARGO oceanographic float data
> **Version:** 2.0
> **Status:** In Development — Features 1-10, 13, 14, and 15 complete, including GDAC auto-sync under Feature 10; roadmap features 11-12 are planned

---

## Table of Contents

1. [Data Ingestion Pipeline](#1-data-ingestion-pipeline)
2. [Ocean Data Database](#2-ocean-data-database)
3. [Metadata Search Engine](#3-metadata-search-engine)
4. [Natural Language Query Engine](#4-natural-language-query-engine)
5. [Conversational Chat Interface](#5-conversational-chat-interface)
6. [Data Visualization Dashboard](#6-data-visualization-dashboard)
7. [Geospatial Exploration](#7-geospatial-exploration)
8. [Data Export System](#8-data-export-system)
9. [Guided Query Assistant](#9-guided-query-assistant)
10. [Dataset Management](#10-dataset-management)
11. [API Layer](#11-api-layer)
12. [System Monitoring](#12-system-monitoring)
13. [Authentication & User Management](#13-authentication--user-management)
14. [RAG Pipeline](#14-rag-pipeline)
15. [Anomaly Detection](#15-anomaly-detection)

---

## Build Status

| Feature | Status |
|---|---|
| 1 — Data Ingestion Pipeline | ✅ Complete |
| 2 — Ocean Data Database | ✅ Complete |
| 3 — Metadata Search Engine | ✅ Complete |
| 4 — Natural Language Query Engine | ✅ Complete |
| 5 — Conversational Chat Interface | ✅ Complete |
| 6 — Data Visualization Dashboard | ✅ Complete |
| 7 — Geospatial Exploration | ✅ Complete |
| 13 — Authentication & User Management | ✅ Complete |
| 8 — Data Export System | ✅ Complete |
| 14 — RAG Pipeline | ✅ Complete |
| 15 — Anomaly Detection | ✅ Complete |
| 9 — Guided Query Assistant | ✅ Complete |
| 10 — Dataset Management | ✅ Complete |
| 10.6 — GDAC Auto-Sync | ✅ Complete |
| 11 — API Layer | ⏳ Planned |
| 12 — System Monitoring | ⏳ Planned |

---

## 1. Data Ingestion Pipeline

**Status: ✅ Complete**

### Overview
The ingestion pipeline is the entry point for all ARGO float data into the FloatChat platform. It handles raw NetCDF files, validates structure, normalizes variables, and persists the data for downstream querying and analysis.

### Tech Stack
| Component | Technology |
|---|---|
| File parsing | `xarray` (chosen over `netCDF4`) |
| Data transformation | `pandas`, `numpy` |
| Pipeline orchestration | Celery + Redis (Airflow/Prefect deferred to v2) |
| Job queue | Celery + Redis |
| Storage target | PostgreSQL + PostGIS |
| File staging | MinIO (dev), AWS S3 (prod) |
| Metadata extraction | Custom Python parsers |

### Capabilities

#### 1.1 Upload NetCDF Files
- Accept `.nc` and `.nc4` file uploads via the admin UI or API endpoint
- Support bulk uploads (zip archives containing multiple NetCDF files)
- Validate file format and ARGO compliance before processing begins
- Store raw files in MinIO/S3 with unique identifiers
- Track upload status per file (pending → processing → complete / failed)

#### 1.2 Parse Oceanographic Variables
- Extract core ARGO variables: `PRES` (pressure), `TEMP` (temperature), `PSAL` (salinity), `DOXY` (dissolved oxygen), `CHLA` (chlorophyll-a)
- Parse float metadata: `PLATFORM_NUMBER`, `CYCLE_NUMBER`, `JULD` (Julian date), `LATITUDE`, `LONGITUDE`
- Handle BGC (Biogeochemical) float variables: `NITRATE`, `PH_IN_SITU_TOTAL`, `BBP700`, `DOWNWELLING_IRRADIANCE`
- Support both core ARGO and Argo BGC data modes (real-time `R`, adjusted `A`, delayed `D`)
- Extract quality control flags (`_QC` suffix variables) and store alongside raw values

#### 1.3 Clean and Normalize Data
- Apply QC flag filtering — only retain data flagged as good (QC = 1) or probably good (QC = 2) by default; store all with QC label
- Convert Julian dates (`JULD`) to ISO 8601 timestamps
- Handle fill values and NaN representations from ARGO standard (`99999.0`, `FillValue` attributes)
- Normalize pressure depths to consistent float precision
- Detect and flag **static threshold outliers** at ingestion time: temperature > 40°C, salinity < 0 PSU
- Note: static threshold flagging catches physically impossible values only. Contextual oceanographic anomaly detection (unusual-but-valid readings) is handled by Feature 15.

#### 1.4 Store Structured Data
- Insert cleaned float profiles into relational database tables
- Upsert logic: if a float/cycle combination already exists, update rather than duplicate
- Link each profile to its parent dataset/float via foreign keys
- Store profile-level data (one row per depth measurement) and float-level metadata (one row per float)

#### 1.5 Generate Dataset Metadata
- Auto-generate metadata on ingestion: date range, float IDs, variable list, spatial bounding box, profile count
- Store metadata in a dedicated `datasets` table for fast discovery
- Generate human-readable dataset summaries using an LLM call post-ingestion
- Post-ingestion hook triggers Feature 3 embedding generation via Celery task

### Key Outputs
- Structured `profiles` and `measurements` tables in PostgreSQL
- Dataset summary records in `datasets` table
- Float location index (lat/lon per cycle) in `float_positions` table
- Ingestion event logs in `ingestion_jobs` table
- `mv_float_latest_position` materialized view refreshed after each ingestion

### Tasks for Developers
- [x] Build `ingest_netcdf.py` — core parsing script using `xarray`
- [x] Implement QC flag filtering logic with configurable thresholds
- [x] Build file upload endpoint (`POST /api/datasets/upload`)
- [x] Implement upsert logic for float/cycle deduplication
- [x] Write unit tests for each variable parser
- [x] Set up MinIO bucket with folder structure by dataset ID
- [x] Build ingestion job status tracker

---

## 2. Ocean Data Database

**Status: ✅ Complete**

### Overview
The central storage layer for all oceanographic data, optimized for time-range filtering, spatial proximity, depth slicing, and multi-variable profile retrieval.

### Tech Stack
| Component | Technology |
|---|---|
| Primary database | PostgreSQL 15+ |
| Geospatial extension | PostGIS 3.x |
| Vector extension | pgvector |
| ORM | SQLAlchemy (Python) |
| Migrations | Alembic |
| Query optimization | GiST, BRIN, composite indexes, HNSW |
| Connection pooling | PgBouncer |
| Caching layer | Redis |

### Schema Design

#### Core Tables

**`floats`** — one row per ARGO float
```
float_id (PK), platform_number, wmo_id, float_type (core/BGC),
deployment_date, deployment_lat, deployment_lon, country, program
```

**`profiles`** — one row per float cycle
```
profile_id (PK), float_id (FK), cycle_number, juld_timestamp,
latitude, longitude, geom (GEOGRAPHY POINT 4326), data_mode, profile_url
```

**`measurements`** — one row per depth level within a profile
```
measurement_id (PK), profile_id (FK), pressure, depth_m, temperature,
salinity, dissolved_oxygen, chlorophyll, nitrate, ph, bbp700,
downwelling_irradiance, temp_qc, psal_qc, doxy_qc, chla_qc,
nitrate_qc, ph_qc
```

**`datasets`** — one row per ingested dataset
```
dataset_id (PK), name, source_url, ingestion_date, date_range_start,
date_range_end, bbox (PostGIS POLYGON), float_count, profile_count,
variable_list (JSONB), summary_text, is_active, dataset_version,
ingestion_timestamp
```

**`ocean_regions`** — 15 named ocean basin polygons
```
region_id (PK), name, geom (GEOGRAPHY POLYGON)
```
Regions: Indian Ocean, Pacific Ocean (North), Pacific Ocean (South), Atlantic Ocean (North), Atlantic Ocean (South), Southern Ocean, Arctic Ocean, Arabian Sea, Bay of Bengal, Caribbean Sea, Mediterranean Sea, Red Sea, Persian Gulf, Gulf of Mexico, Laccadive Sea

### Materialized Views
- **`mv_float_latest_position`** — latest position per float: `platform_number`, `float_id`, `cycle_number`, `timestamp`, `latitude`, `longitude`, `geom`
- **`mv_dataset_stats`** — aggregated dataset statistics

### Features

#### 2.1 PostgreSQL Storage
- All data stored in normalized relational tables
- JSONB columns for flexible metadata and variable availability per float
- Partitioning on `profiles` table by year for performance at scale

#### 2.2 PostGIS Geospatial Indexing
- `geom` column on `profiles` table (type: `GEOGRAPHY(POINT, 4326)`)
- GiST index on `geom` for fast spatial queries
- 15 pre-defined ocean basin polygons in `ocean_regions` reference table
- Named region lookup: "Arabian Sea" → polygon → float query via `ST_Within`

#### 2.3 Optimized Queries for Ocean Profiles
- Composite indexes on `(latitude, longitude)`, `(juld_timestamp)`, `(float_id, cycle_number)`
- BRIN index on `juld_timestamp` for time-range scans
- Partial indexes for common filter combinations (e.g., BGC floats only)
- HNSW indexes on embedding columns (pgvector)

#### 2.4 Dataset Versioning
- Each ingestion tagged with `dataset_version` and `ingestion_timestamp`
- Old versions retained with `is_active` flag for rollback
- Diff log stored in `dataset_versions` table

### Tasks for Developers
- [x] Write full Alembic migration for all tables
- [x] Enable PostGIS and pgvector extensions
- [x] Create GiST index on `profiles.geom`
- [x] Load 15 ocean basin reference polygons
- [x] Configure Redis cache
- [x] Write query performance benchmarks
- [x] Build `dal.py` data access layer with reusable filter functions

---

## 3. Metadata Search Engine

**Status: ✅ Complete**

### Overview
Allows researchers to discover what data is available before running queries. Indexes dataset summaries, float characteristics, and temporal/spatial attributes for natural language discovery.

### Tech Stack
| Component | Technology |
|---|---|
| Search index | pgvector (chosen over Elasticsearch/OpenSearch) |
| Embedding model | `text-embedding-3-small` (OpenAI) — 1536 dimensions |
| Vector store | pgvector with HNSW indexes |
| Backend | FastAPI (Python) |
| Indexing trigger | Post-ingestion Celery task |
| Fuzzy matching | `pg_trgm` PostgreSQL extension |

### Features

#### 3.1 Semantic Search
- Embed dataset summaries and float descriptions using `text-embedding-3-small`
- Store embeddings in pgvector (`dataset_embeddings`, `float_embeddings` tables) with HNSW indexes
- At query time, embed the user's query and find closest matches via cosine similarity
- Hybrid scoring: cosine similarity + recency boost + region match boost
- Return ranked list of matching datasets with relevance scores

#### 3.2 Dataset Summaries
- Each dataset has a plain-English summary auto-generated at ingestion time
- Summaries indexed and searchable via pgvector
- Summaries also power Feature 5's load-time example query suggestions (cached in Redis)

#### 3.3 Float Discovery
- Search for individual floats by WMO ID, deployment region, float type, or variable availability
- Return float profile: active date range, last known position, measured variables

#### 3.4 Region-Based Lookup
- Named region search resolves to polygon via `ocean_regions` table
- Fuzzy matching via `pg_trgm`: "Bengal Bay" → "Bay of Bengal"
- `resolve_region_name(name, db)` function reused by Feature 7's basin-floats endpoint

### Geography Lookup
- Curated `geography_lookup.json` with 50+ Indian Ocean and global locations
- Used by Feature 4 (NL query geography resolver) and Feature 7 (map search bar)
- Covers: city names, island names, ocean sub-regions, research stations

### Tasks for Developers
- [x] Enable pgvector extension and create HNSW indexes
- [x] Build post-ingestion hook to generate and store embeddings
- [x] Implement `search_datasets(query: str)` endpoint
- [x] Build `resolve_region_name()` with fuzzy matching
- [x] Build relevance scoring logic
- [x] Create `geography_lookup.json`

---

## 4. Natural Language Query Engine

**Status: ✅ Complete**

### Overview
The core intelligence layer of FloatChat. Converts plain English questions into valid SQL, executes against the ocean database, and returns structured results via SSE streaming.

### Tech Stack
| Component | Technology |
|---|---|
| LLM providers | DeepSeek (default), Qwen QwQ, Gemma, OpenAI |
| LLM client | openai Python library (OpenAI-compatible API for all providers) |
| NL→SQL framework | Custom prompt pipeline (no LangChain) |
| SQL validation | `sqlglot` (AST-based: syntax, read-only, table whitelist, PostGIS cast check) |
| Query execution | SQLAlchemy + PostgreSQL (read-only DB user) |
| Context management | Redis (last 10 turns stored, last 3 included in prompt) |
| Safety layer | Table whitelist, row limit enforcement, statement timeout |

### Features

#### 4.1 Convert Natural Language to SQL
- Custom system prompt: full schema description, column descriptions, 20+ oceanographic few-shot examples
- Multi-provider support: caller specifies provider, falls back to DeepSeek default
- Geography resolver using `geography_lookup.json` — resolves place names to lat/lon before prompt construction
- Maps common phrases to correct SQL patterns:
  - "near Sri Lanka" → `ST_DWithin(geom, ST_MakePoint(80.7, 7.8)::geography, 200000)`
  - "last year" → `juld_timestamp >= NOW() - INTERVAL '1 year'`
  - "deep profiles" → `WHERE pressure > 1500`
  - "BGC floats" → `WHERE f.float_type = 'BGC'`

#### 4.2 Query Interpretation
- SSE event `interpreting` sends a brief query-intent summary + generated SQL to the client before execution
- User can send confirmation or cancellation before execution runs

#### 4.3 Context Understanding
- Redis session context: last 10 turns stored, last 3 included in prompt
- Pronoun and relative reference resolution across turns

#### 4.4 Query Validation
- sqlglot AST inspection: syntax errors, non-SELECT statements, non-whitelisted tables, uncasted PostGIS calls
- Row limit: default 10,000, max 100,000
- Statement timeout: 30 seconds
- Confirmation mode: queries estimated > 50,000 rows require explicit user confirmation before execution
- Retry loop: up to 3 attempts with validation error feedback injected into prompt

#### 4.5 SSE Event Sequence
```
thinking → interpreting → executing → results → suggestions → done
                                   ↘ awaiting_confirmation (large queries)
                                   ↘ error (on failure)
```

#### 4.6 Benchmark Endpoint
- `POST /api/v1/query/benchmark` runs a single NL query through all three providers simultaneously
- Returns SQL, latency, and row count per provider for comparison

### Example Flow
```
User input:    "show temperature near Sri Lanka in 2023"
               ↓
Geography:     "Sri Lanka" → lat 7.8, lon 80.7
               ↓
LLM generates: SELECT p.juld_timestamp, p.latitude, p.longitude,
                      m.pressure, m.temperature
               FROM profiles p
               JOIN measurements m ON p.profile_id = m.profile_id
               WHERE ST_DWithin(p.geom, ST_MakePoint(80.7, 7.8)::geography, 300000)
                 AND p.juld_timestamp BETWEEN '2023-01-01' AND '2023-12-31'
                 AND m.temp_qc IN (1, 2)
               ORDER BY p.juld_timestamp;
               ↓
Validation:    SQL parsed ✓, read-only ✓, row limit ✓
               ↓
Execution:     Returns 1,240 rows
               ↓
Response:      Table + chart + "Found 1,240 temperature profiles near Sri Lanka in 2023"
```

### Tasks for Developers
- [x] Write system prompt with full schema and 20+ few-shot examples
- [x] Build `nl_to_sql(query, context, provider)` function
- [x] Integrate `sqlglot` AST validation
- [x] Implement retry loop (max 3 attempts)
- [x] Create read-only PostgreSQL user
- [x] Build `execute_sql(sql)` with row limit and timeout
- [x] Store conversation context in Redis
- [x] Build geography resolver using `geography_lookup.json`
- [x] Build multi-provider support with benchmark endpoint
- [x] Write test suite with 50+ NL query examples

---

## 5. Conversational Chat Interface

**Status: ✅ Complete**

### Overview
The primary researcher interface. A chat UI supporting follow-up questions, inline result display, and SSE-streamed responses.

### Tech Stack
| Component | Technology |
|---|---|
| Frontend framework | Next.js 14 (App Router) |
| UI components | Tailwind CSS + shadcn/ui |
| Real-time updates | SSE via fetch + ReadableStream (not WebSocket) |
| State management | Zustand (not Redux) |
| Backend | FastAPI (Python) |
| Session management | Browser UUID → JWT after Auth feature |
| Message persistence | PostgreSQL (`chat_sessions`, `chat_messages` tables) |
| Markdown | react-markdown + remark-gfm + rehype-highlight + rehype-sanitize |

### Features

#### 5.1 Chat UI
- Two-panel layout: 280px sidebar + main chat panel
- User messages right-aligned, assistant messages left-aligned
- Chat thread max width 720px, centered in main panel
- SSE streaming with animated loading states per event type
- Inline result display: tables, charts, and maps within the conversation thread
- Collapsible SQL display (collapsed by default, labeled "View SQL")

#### 5.2 Follow-Up Questions
- 2–3 suggested follow-up chips per assistant response
- Generated via separate LLM call at temperature 0.7 after results event
- Never blocks the results event

#### 5.3 Context Memory
- Session-scoped memory in Redis (last 10 turns, last 3 in prompt)
- Named sessions stored in `chat_sessions` table
- Sidebar shows session history with rename and delete actions

#### 5.4 Suggestions on Load
- 4–6 example queries generated from Feature 3's dataset summaries
- Cached in Redis with TTL 3600 seconds
- Shown as cards on empty chat state

#### 5.5 Error Guidance
- Error messages mapped from `error_type` values from Feature 4
- Empty result guidance based on query context
- Reformulation suggestions displayed inline

### SSE Event Sequence
```
thinking → interpreting → executing → results → suggestions → done
```
Plus: `error`, `awaiting_confirmation`

### Components
- `SessionSidebar` — session list, new conversation, rename/delete, Dashboard link, Map link
- `ChatThread` — scrollable message area with infinite scroll upward
- `ChatMessage` — renders user/assistant messages with tables/charts/maps
- `ChatInput` — textarea, Enter submit, Shift+Enter newline, auto-resize to 6 lines
- `ResultTable` — inline data table, sortable columns, 100 row display with truncation badge
- `SuggestedFollowUps` — 2–3 clickable chips
- `SuggestionsPanel` — 4–6 example query cards on empty state
- `LoadingMessage` — animated states for thinking/interpreting/executing
- `VisualizationPanel` — renders appropriate chart/map per result shape (Feature 6)

### Deep Link Support
- `/chat?prefill={encoded_query}` pre-fills and auto-submits a query from the map interface
- Added in Feature 7 integration

### Tasks for Developers
- [x] Scaffold Next.js app with chat layout
- [x] Build all 9 chat components
- [x] Implement SSE connection with ReadableStream
- [x] Build session management CRUD
- [x] Build follow-up suggestion generation
- [x] Build error state components
- [x] Implement markdown renderer
- [x] Build session history sidebar

---

## 6. Data Visualization Dashboard

**Status: ✅ Complete**

### Overview
Interactive oceanographic charts and maps rendered inline in the chat and in a standalone dashboard view.

### Tech Stack
| Component | Technology |
|---|---|
| Charting library | Plotly.js + react-plotly.js (not Recharts) |
| Ocean-specific plots | Custom React components on top of Plotly |
| Map rendering | Leaflet.js + react-leaflet (not Mapbox GL JS) |
| Map clustering | react-leaflet-cluster |
| Map draw tool | leaflet-draw + react-leaflet-draw |
| Color scales | cmocean implemented as custom Plotly color arrays in `lib/colorscales.ts` |
| Dashboard layout | react-grid-layout (Responsive, 3 columns) |
| SSR handling | All visualization components dynamically imported with `{ ssr: false }` |

### Chart Types

#### 6.1 Ocean Profile Plots (`OceanProfileChart`)
- Vertical profile: X = variable value, Y = pressure/depth (always inverted — `autorange: 'reversed'`)
- Dual X-axis for multi-variable (temperature + salinity overlay)
- Color-coded by platform_number for multi-float; thermal colorscale for single float
- scattergl trace type used for datasets > 10,000 points

#### 6.2 T-S Diagram (`TSdiagram`)
- Scatter: X = salinity, Y = temperature, colored by pressure using deep colorscale
- showDensityContours prop exists but defaults to false (deferred to v2)

#### 6.3 Salinity Overlay (`SalinityOverlayChart`)
- Default chart for results with pressure + temperature + salinity
- Dual X-axes: temperature bottom (red), salinity top (blue), inverted Y-axis
- "View as T-S Diagram" toggle button swaps to TSdiagram

#### 6.4 Time Series (`TimeSeriesChart`)
- Line chart: X = juld_timestamp, Y = variable, one trace per platform_number
- maxPressure prop for depth filtering

### Map Views

#### 6.5 Float Trajectories (`FloatTrajectoryMap`)
- Polyline per float with blue→red temporal gradient via N-1 segmented Polylines
- Downsampled to 200 points for trajectories > 500 points
- OSM attribution required (legal)

#### 6.6 Float Positions (`FloatPositionMap`)
- react-leaflet-cluster for clustering at low zoom
- Color-coded by variable using cmocean colorscales
- Custom HTML colorbar
- OSM attribution required

#### 6.7 Region Selection (`RegionSelector`)
- Rectangle and polygon drawing via leaflet-draw
- Emits GeoJSONPolygon via onRegionSelected callback
- Reused by Feature 7's ExplorationMap for polygon/rectangle drawing

### Shape Detection
- `detectResultShape(columns, rows)` — pure function, try/catch wrapper returns `unknown` on error
- Priority order: `float_trajectory` > `salinity_overlay` > `float_positions` > `vertical_profile` > `time_series` > `unknown`
- `salinity_overlay` is default for pressure + temperature + salinity results (TSdiagram reachable via toggle)

### Colorscales (`lib/colorscales.ts`)
- THERMAL (temperature), HALINE (salinity), DEEP (depth/pressure), DENSE, OXY (oxygen), MATTER
- COLORSCALE_FOR_VARIABLE mapping
- DEFAULT_MAP_CENTER: [20.0, 60.0], DEFAULT_MAP_ZOOM: 4
- Only file allowed to define colorscale arrays

### Row Data Storage
- `resultRows: Record<string, ChartRow[]>` in Zustand store
- Populated from SSE `results` event during streaming
- Keyed by `message_id` for access by VisualizationPanel and Dashboard

### Tasks for Developers
- [x] Build OceanProfileChart, TSdiagram, TimeSeriesChart, SalinityOverlayChart
- [x] Build FloatTrajectoryMap, FloatPositionMap, RegionSelector
- [x] Build VisualizationPanel with automatic shape detection
- [x] Implement chart export (PNG/SVG)
- [x] Build /dashboard route with react-grid-layout
- [x] Implement cmocean colorscales
- [x] Add Dashboard nav link to SessionSidebar

---

## 7. Geospatial Exploration

**Status: 🔄 In Progress**

### Overview
Map-first discovery of oceanographic data. Full-screen map at `/map` with nearest float queries, radius drawing, basin filtering, and deep links to chat.

### Tech Stack
| Component | Technology |
|---|---|
| Map library | Leaflet.js + react-leaflet (not Mapbox GL JS) |
| Map clustering | react-leaflet-cluster |
| Map draw tool | leaflet-draw + react-leaflet-draw |
| Geospatial utils | @turf/turf (frontend calculations) |
| Geocoding | Feature 4's `geography_lookup.json` (no external API) |
| Ocean basin polygons | `ocean_regions` table via `/api/v1/map/basin-polygons` endpoint |
| Backend | FastAPI spatial query endpoints |

### Key Decisions Made
- **No Mapbox** — Leaflet.js used throughout for consistency and no API key requirement
- **No external geocoding API** — geography lookup JSON only (Hard Rule)
- **No URL-based map state in v1** — map always starts at default view
- **ExplorationMap built fresh** — not reusing FloatPositionMap (different interaction requirements)
- **Circle draw tool separate from RegionSelector** — RegionSelector handles polygon/rectangle; circle handled directly in ExplorationMap via leaflet-draw circle handler
- **15 basin regions shown always** — BasinFilterPanel shows all 15 regardless of data availability
- **Deep link auto-submits** — `/chat?prefill=...` auto-submits the query rather than just pre-filling

### Features

#### 7.1 Full-Screen Map (`ExplorationMap`)
- Two-column layout: 240px left panel + full-screen map
- All active float positions on mount from Redis-cached `/api/v1/map/active-floats`
- Core floats: `--color-ocean-primary`, BGC floats: `--color-coral`
- All colors read from CSS variables at runtime — never hardcoded
- Map click → nearest floats query → NearestFloatsPanel
- Float marker click → FloatDetailPanel
- OSM tiles with attribution (legal requirement)

#### 7.2 Nearest Floats (`NearestFloatsPanel`)
- Triggered by map click
- Up to 10 float cards with distance labels
- "Query these floats in chat" deep link

#### 7.3 Radius Queries (`RadiusQueryPanel`)
- Circle draw tool via leaflet-draw circle handler
- Adjustable radius slider (50km–2000km), debounced 300ms
- Profile count and float count preview
- "Query in Chat" deep link

#### 7.4 Ocean Basin Filtering (`BasinFilterPanel`)
- 15 named regions in two groups (7 major, 8 sub-regions)
- Polygon overlays from `/api/v1/map/basin-polygons` endpoint
- Active basin polygon filled at 30% opacity
- Always shows all 15 regions; float count loads after query

#### 7.5 Search Bar (`SearchBar`)
- Priority: coordinate pair → DMS notation → basin name → geography lookup → "not found"
- No external geocoding API

#### 7.6 Float Detail Panel (`FloatDetailPanel`)
- Full float metadata + mini OceanProfileChart (200px, no export buttons)
- "Open in Chat" and "View trajectory" actions

#### 7.7 Deep Link System
- Pre-filled query formats per FR-20 in feature7_prd.md
- Auto-submits via `submitQuery()` on mount when `prefill` param present

### Backend Endpoints (`/api/v1/map/`)
- `GET /active-floats` — all float positions, Redis-cached 5 minutes
- `GET /nearest-floats` — ST_DWithin + ST_Distance, joins `floats` table for `float_type`
- `POST /radius-query` — metadata only, no measurement rows
- `GET /floats/{platform_number}` — full metadata + last 5 profiles for mini chart
- `GET /basin-floats` — uses `resolve_region_name` + direct ST_Within query
- `GET /basin-polygons` — all 15 region geometries as GeoJSON FeatureCollection, Redis-cached 1 hour

### Tasks for Developers
- [x] Build 6 backend map endpoints
- [ ] Build ExplorationMap component
- [ ] Build NearestFloatsPanel, FloatDetailPanel, RadiusQueryPanel
- [ ] Build BasinFilterPanel, SearchBar, MapToolbar
- [ ] Build mapQueries.ts API client
- [ ] Add Map nav link to SessionSidebar
- [ ] Wire prefill param in chat page
- [ ] Write backend and frontend tests

---

## 8. Data Export System

**Status: ✅ Complete**

### Overview
Export query results in CSV, NetCDF, and JSON formats. Async export via Celery for large files.

### Tech Stack
| Component | Technology |
|---|---|
| CSV generation | `pandas` (`to_csv`) |
| NetCDF export | `xarray` |
| JSON export | FastAPI `JSONResponse` |
| File delivery | Presigned MinIO/S3 URL or direct stream |
| Async generation | Celery task for exports > 50MB |
| Progress tracking | Redis task status |

### Export Formats

#### 8.1 CSV
- Flat table, one row per measurement, UTF-8
- Columns: `profile_id`, `float_id`, `timestamp`, `latitude`, `longitude`, `pressure`, `temperature`, `salinity`, `oxygen`, `qc_flags`

#### 8.2 NetCDF
- ARGO-compliant reconstruction using xarray
- Preserves original variable names, units, QC flag conventions
- Global attributes: source dataset, query parameters, export timestamp

#### 8.3 JSON
- Structured envelope with query metadata, profile count, and profiles array

#### 8.4 Export Types
- Raw profiles: all measurements at all depth levels
- Filtered datasets: only variables and depth range matching the query
- Query results: exactly what was returned in chat, one-click export

### Tasks for Developers
- [x] Build export functions: CSV, NetCDF, JSON
- [x] Build `POST /api/v1/export` endpoint
- [x] Implement async Celery export for large files
- [x] Build download progress indicator in chat UI
- [x] Add Export button to every query result panel

---

## 9. Guided Query Assistant

**Status: ✅ Complete**

### Overview
Interactive query help for new users and returning users. Provides a guided template gallery, Fuse.js-powered autocomplete, and a clarification flow for underspecified free-text queries while preserving existing prefill workflows.

### Tech Stack
| Component | Technology |
|---|---|
| Autocomplete | React + Fuse.js |
| Clarification logic | LLM with structured output (same multi-provider setup as Feature 4) |
| Query templates | JSON-defined template library (30+ templates) |
| UI | SuggestedQueryGallery + AutocompleteInput + ClarificationWidget |
| Backend APIs | `GET /api/v1/chat/query-history`, `POST /api/v1/clarification/detect` |

### Features

#### 9.1 Suggested Queries
- Empty-state gallery with category tabs and 35 static templates in `frontend/lib/queryTemplates.json`
- Optional `For You` tab for authenticated users with at least 5 history entries from `query_history`
- "Recently Added" badge computed from recent dataset summaries (`/api/v1/search/datasets/summaries`) with silent fallback on API failure

#### 9.2 Autocomplete
- Sources: template library + auth-scoped query history (`GET /api/v1/chat/query-history`) + ocean terms dictionary
- Fuse.js fuzzy matching with source-priority merge (history > templates > terms), match highlighting, and keyboard navigation

#### 9.3 Clarification Prompts
- Server-side clarification detection via `POST /api/v1/clarification/detect` using the same provider stack as Feature 4
- Fail-open behavior on invalid model output, exceptions, or timeouts; query proceeds normally
- Chip-based refinement widget supports assembled query submission, skip, and dismiss
- Clarification is bypassed for template clicks, autocomplete selections, and prefill-driven submissions

### Tasks for Developers
- [x] Build query template library JSON (30+ templates)
- [x] Build SuggestedQueryGallery component
- [x] Build typeahead autocomplete with Fuse.js
- [x] Implement clarification detection
- [x] Build ClarificationWidget component
- [x] Integrate guided flow with prefill-safe bypass behavior

---

## 10. Dataset Management

**Status: ✅ Complete**

### Overview
Admin interface for uploading datasets, monitoring ingestion, managing metadata, and retiring data. Admin role is required for all endpoints and UI routes.

### Tech Stack
| Component | Technology |
|---|---|
| Admin UI | React (same Next.js app, `/admin` route) |
| Auth | RBAC — admin role required (Feature 13) |
| Backend | FastAPI admin endpoints |
| Job tracking | Celery + Redis + `ingestion_jobs` table |
| Storage | MinIO (dev) / S3 (prod) |

### Features

#### 10.1 Upload Datasets
- Drag-and-drop upload, single `.nc` files and zip archives
- Upload progress bar
- Auto-trigger of ingestion pipeline on successful upload
- Email/Slack notification on completion/failure

#### 10.2 Track Ingestion Status
- Dashboard: all ingestion jobs with status, duration, profiles ingested, errors
- Real-time status updates via SSE
- Retry failed jobs with one click
- Error log viewer

#### 10.3 Manage Dataset Metadata
- Edit name, description, tags
- Regenerate LLM summary (manual trigger)
- View statistics: float count, profile count, date range, variable list
- Mark as public or internal
- Supports soft delete restore path from the same detail flow

#### 10.4 Remove Outdated Datasets
- Soft delete: marks inactive, hides from search, preserves data
- Hard delete: async task removes profiles, measurements, anomalies, and raw files
- Confirmation dialog with impact summary
- Audit log in `admin_audit_log` table

#### 10.5 Search/Query Enforcement + Notifications
- Researcher-facing dataset discovery and summary endpoints exclude `deleted_at IS NOT NULL` datasets
- NL query schema guidance updated so generated SQL treats `deleted_at IS NULL` as active datasets
- Shared notification module (`app/notifications`) is active for ingestion outcomes and anomaly stub forwarding

#### 10.6 GDAC Auto-Sync (Automated External Data Intake)
- Nightly scheduled GDAC sync task runs at 01:00 UTC via Celery beat (`run-gdac-sync-nightly`)
- Admin trigger endpoint (`POST /api/v1/admin/gdac-sync/trigger`) launches manual sync with global cooldown window
- Run history endpoints (`GET /api/v1/admin/gdac-sync/runs`, `GET /api/v1/admin/gdac-sync/runs/{run_id}`) expose status, counts, mirror used, and error details
- Sync state checkpointing (`gdac_sync_state`) tracks last index date and completion timestamp
- Download and notification failures are non-fatal; successful downloads continue ingest dispatch through existing ingestion pipeline (`source='gdac_sync'`)

### Tasks for Developers
- [x] Build admin dashboard page (admin role protected)
- [x] Build DatasetUploadPanel
- [x] Build IngestionJobsTable with SSE status updates
- [x] Build DatasetDetailPage with metadata editor
- [x] Implement soft and hard delete endpoints
- [x] Build audit log table and UI
- [x] Set up email/Slack notifications
- [x] Add GDAC sync run/state schema and ORM models
- [x] Add Celery GDAC sync task wrapper + nightly beat schedule
- [x] Add admin GDAC trigger and run-history APIs
- [x] Add admin GDAC dashboard panel and `/admin/gdac-sync` run history page
- [x] Add GDAC backend test coverage (index, downloader, sync orchestrator)

---



## 11. API Layer

**Status: ⏳ Planned — build after Dataset Management (Feature 10)**

### Overview
Public RESTful API exposing FloatChat capabilities to external research tools and scripts. The FastAPI infrastructure and all endpoints already exist and are running — this feature adds API key authentication, rate limiting, and formal OpenAPI documentation on top of what is already live. No new endpoints need to be built from scratch.

**Important:** Feature 10 introduced `is_public` on the `datasets` table. The API layer must respect this flag — external API consumers (authenticated by API key, not JWT) must only receive data from datasets marked `is_public = true`. This is the primary new data-access constraint introduced by this feature.

### Tech Stack
| Component | Technology |
|---|---|
| Framework | FastAPI (Python) — already in use |
| Auth | API key (`X-API-Key` header) for external consumers + existing JWT for internal/browser use |
| Rate limiting | `slowapi` (FastAPI middleware) |
| Docs | Auto-generated OpenAPI/Swagger at `/docs` |
| Versioning | `/api/v1/` — already in place |
| CORS | Already configured |

### What Already Exists (no changes needed)
All of the following endpoints are fully built and functional. This feature documents and gates them — it does not rebuild them:
- `POST /api/v1/query` — NL query, full pipeline
- `GET /api/v1/datasets/search` — semantic search
- `GET /api/v1/profiles/{profile_id}/chart-data` — visualization data
- `POST /api/v1/export` — export job trigger
- `GET /api/v1/floats/{wmo_id}` — float info
- `GET /api/v1/map/*` — all geospatial endpoints (Feature 7)
- `GET /api/v1/anomalies` — anomaly feed (Feature 15)

### What This Feature Adds
#### 11.1 API Key Authentication
- New `api_keys` table: `key_id`, `key_hash`, `user_id` FK, `name` (label for the key), `is_active`, `created_at`, `last_used_at`, `rate_limit_override` (nullable — allows per-key rate limit customisation)
- `POST /api/v1/auth/api-keys` — create API key (JWT-authenticated, returns plaintext key once only)
- `GET /api/v1/auth/api-keys` — list user's API keys (shows name, created_at, last_used_at, never plaintext key)
- `DELETE /api/v1/auth/api-keys/{key_id}` — revoke API key
- `X-API-Key` header accepted on all public endpoints as an alternative to Bearer JWT
- API key requests are scoped to `is_public = true` datasets only — they cannot access internal datasets regardless of the requesting user's role

#### 11.2 Rate Limiting
- `slowapi` middleware applied globally
- Default: 100 requests/minute per API key
- Default: 300 requests/minute per authenticated JWT user (higher limit for browser sessions)
- Per-key override via `rate_limit_override` column in `api_keys` table
- Rate limit headers returned on every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- 429 response with `Retry-After` header when limit exceeded

#### 11.3 OpenAPI Documentation
- All existing endpoints annotated with full OpenAPI descriptions: summary, description, request/response schemas, error codes
- `is_public` dataset filtering documented explicitly
- API key authentication documented in the security scheme
- `/docs` (Swagger UI) and `/redoc` both enabled
- Changelog section in docs showing endpoint history

#### 11.4 Integration Test Suite
- End-to-end tests using API key auth (not JWT) against all documented endpoints
- Tests for rate limit enforcement (mock clock)
- Tests for `is_public` dataset scoping — API key requests must not return internal datasets
- Tests for API key creation, listing, and revocation

### New Tables
- **`api_keys`** — `key_id` (UUID PK), `key_hash` (SHA-256 of the plaintext key, stored only as hash), `user_id` (FK → users), `name` (VARCHAR 100), `is_active` (BOOLEAN default true), `created_at`, `last_used_at` (TIMESTAMPTZ nullable, updated on each use), `rate_limit_override` (INTEGER nullable)

### Migration
- `009_api_layer.py` — `down_revision = "008"`

### Dependencies
- Feature 10 must be complete — `is_public` column on `datasets` must exist before API key scoping can be enforced
- Feature 13 (Auth) must be complete — API key creation endpoints require JWT auth
- `slowapi` — new pip dependency

### Tasks for Developers
- [ ] Create migration 009: `api_keys` table
- [ ] Implement API key generation (secure random, stored as SHA-256 hash)
- [ ] Build `X-API-Key` auth middleware — resolves key, scopes to public datasets
- [ ] Add rate limiting via `slowapi` with per-key overrides
- [ ] Write OpenAPI annotations for all existing endpoints
- [ ] Build integration test suite using API key auth
- [ ] Write API usage documentation (developer guide, authentication guide, rate limit guide)

---

## 12. System Monitoring

**Status: ⏳ Planned — build after API Layer (Feature 11)**

### Overview
Operational reliability infrastructure for production deployment: structured logging pipeline, error tracking, performance metrics, and alerting. Note: `structlog` is already in use throughout the codebase and produces structured JSON logs — this feature routes those logs to a destination, adds error tracking (Sentry), adds metrics (Prometheus + Grafana), and wires up alerting. The ingestion monitoring dashboard is an extension of Feature 10's admin panel, not a separate UI.

### Prerequisites Already in Place
- `structlog` configured and used across all backend modules — logs already emit structured JSON
- Slack webhook infrastructure built in Feature 10's notification module — alerting reuses this
- Feature 10's admin panel — ingestion monitoring dashboard extends it rather than building separately
- Feature 15's anomaly detection — anomaly scan job health is a key monitoring signal already producing structlog output

### Tech Stack
| Component | Technology |
|---|---|
| Logging | `structlog` (already in use) → stdout → Loki (self-hosted) or CloudWatch (AWS) |
| Error tracking | Sentry (Python SDK + Next.js SDK) |
| Metrics | `prometheus-fastapi-instrumentator` + Grafana |
| Uptime monitoring | UptimeRobot or Healthchecks.io |
| Alerting | Slack webhook (reuses Feature 10's `app/notifications/slack.py`) |
| Tracing | OpenTelemetry (optional, lower priority) |

### Features

#### 12.1 Logging Pipeline
- Structlog is already emitting structured JSON — this feature routes it to a destination
- Log destination configured via `LOG_SINK` env var: `stdout` (dev), `loki` (self-hosted), `cloudwatch` (AWS)
- Log fields already in use: `timestamp`, `endpoint`, `method`, `status_code`, `latency_ms`, `user_id`, `session_id`
- Confirm all NL query log fields are present: `nl_query`, `generated_sql`, `provider`, `execution_time_ms`, `row_count` — add any missing fields to the pipeline logging
- Confirm all ingestion log fields are present: `file_name`, `records_parsed`, `qc_flags_filtered`, `error_count` — add any missing fields to ingestion tasks
- Log retention policy configurable via env var (default: 30 days)

#### 12.2 Error Tracking (Sentry)
- Sentry Python SDK on FastAPI backend: captures unhandled exceptions, slow requests, and DB query errors
- Sentry Next.js SDK on frontend: captures unhandled React errors and failed API calls
- Custom tags on every Sentry event: `query_type`, `dataset_id`, `float_id`, `provider` where available
- Alert rules: new error type → immediate Slack notification; error rate spike (>10x baseline in 5 minutes) → Slack notification
- `SENTRY_DSN_BACKEND` and `SENTRY_DSN_FRONTEND` env vars — Sentry is disabled when these are absent (dev)

#### 12.3 Performance Metrics
- `prometheus-fastapi-instrumentator` auto-instruments all FastAPI endpoints
- Additional custom metrics:
  - LLM call latency per provider (histogram)
  - DB query time per endpoint (histogram)
  - Redis cache hit rate (counter)
  - Celery task duration per task name (histogram)
  - Anomaly scan duration (gauge, from Feature 15's nightly task)
- Prometheus scrape endpoint: `GET /metrics` (unauthenticated, not proxied to public)
- Grafana dashboard with panels: request latency p50/p95/p99 per endpoint, LLM latency per provider, DB query time, Redis cache hit rate, active Celery tasks, ingestion job success rate
- Alert: p95 latency > 5s on `POST /api/v1/query` → Slack notification

#### 12.4 Ingestion Monitoring Dashboard (Extension of Feature 10 Admin Panel)
- New tab or section in the Feature 10 admin panel (not a separate UI)
- Per-job tracking already exists in Feature 10's ingestion jobs table — this adds aggregate views:
  - Daily summary: profiles ingested, new floats discovered, failed files, ingestion duration
  - 7-day trend chart of ingestion volume
  - Failed job rate over time
- Slack alert on any ingestion failure (already triggered by Feature 10's notification module — confirm this is working and add a daily digest if not)
- GDAC auto-sync job metrics are available via the `source='gdac_sync'` ingestion job stream and can be surfaced in this monitoring section

#### 12.5 Uptime Monitoring
- Healthcheck endpoint: `GET /api/v1/health` — returns `{ "status": "ok", "db": "ok", "redis": "ok", "celery": "ok" }` with individual component checks
- External uptime monitor (UptimeRobot or Healthchecks.io) pings `/api/v1/health` every 60 seconds
- Alert to Slack if health check fails for 3 consecutive checks

### New Endpoints
- `GET /api/v1/health` — public health check (no auth required)
- `GET /metrics` — Prometheus scrape endpoint (no auth, bind to internal network only in production)

### Dependencies
- Feature 10 complete — notification module (`app/notifications/slack.py`) reused for alerting; admin panel extended for ingestion monitoring dashboard
- Feature 11 complete — `/metrics` endpoint must not be exposed through the API key rate limiter
- `prometheus-fastapi-instrumentator` — new pip dependency
- `sentry-sdk[fastapi]` — new pip dependency
- `@sentry/nextjs` — new npm dependency

### Tasks for Developers
- [ ] Configure Sentry DSN for backend and frontend — disabled gracefully when DSN absent
- [ ] Audit and fill gaps in structlog fields (NL query fields, ingestion fields)
- [ ] Install and configure `prometheus-fastapi-instrumentator`
- [ ] Add custom Prometheus metrics (LLM latency, DB time, Redis hit rate, Celery duration, anomaly scan duration)
- [ ] Build Grafana dashboard with all metric panels
- [ ] Build `GET /api/v1/health` endpoint with component checks
- [ ] Set up external uptime monitor
- [ ] Extend Feature 10 admin panel with ingestion monitoring aggregate views
- [ ] Configure Slack alerting rules (Sentry + Prometheus + uptime)
- [ ] Write alert runbook documenting each alert and its remediation steps

---

## 13. Authentication & User Management

**Status: ✅ Complete — built before Features 8, 14, 15, 9, 10**

### Overview
JWT-based authentication with RBAC. Enables multi-tenant session isolation, protects all chat and query endpoints. Built as a prerequisite for Feature 14 (RAG Pipeline), Feature 15 (Anomaly Detection), Feature 9 (Guided Query Assistant), and Feature 10 (Dataset Management).

### Tech Stack
| Component | Technology |
|---|---|
| Token generation | python-jose (JWT) |
| Password hashing | passlib + bcrypt |
| Token storage | httpOnly cookies (refresh token) + memory (access token) |
| RBAC | `researcher` role (default), `admin` role |
| Frontend | Next.js App Router middleware for route protection |

### What Was Built

#### 13.1 User Registration & Login ✅
- `POST /api/v1/auth/signup` — name, email, password; returns JWT
- `POST /api/v1/auth/login` — email, password; returns JWT
- `POST /api/v1/auth/logout` — invalidates refresh token
- `GET /api/v1/auth/me` — returns current user profile
- `POST /api/v1/auth/forgot-password` — sends reset email

#### 13.2 Route Protection ✅
- JWT middleware on all `/api/v1/chat/*`, `/api/v1/query/*`, `/api/v1/map/*`, `/api/v1/export/*` endpoints
- Admin role required for `/api/v1/admin/*` endpoints (enforced at router level via `get_current_admin_user`)
- Frontend: unauthenticated users redirect to `/login`

#### 13.3 Session Migration ✅
- Anonymous browser-UUID sessions linked to user account on first login
- `chat_sessions.user_identifier` becomes FK to `users.user_id`

#### 13.4 UI ✅
- `/login` and `/signup` pages
- User profile in sidebar footer: initials avatar, name, logout button
- Theme toggle in sidebar footer

### Tables Built
- **`users`** — `user_id`, `email`, `hashed_password`, `name`, `role`, `created_at`, `is_active`
- **`password_reset_tokens`** — `token_id`, `user_id`, `token_hash`, `expires_at`, `used`

### Migration
- `005_auth.py` — `down_revision = "004"` ✅

### Auth Dependencies Available for Other Features
The following are importable and used throughout the codebase:
- `get_current_user` — returns authenticated `User`, raises 401 if not authenticated
- `get_current_admin_user` — returns authenticated `User` with `role = "admin"`, raises 403 for non-admin

### Notes for Features 11 and 12
- Feature 11 (API Layer) extends auth by adding API key support as an alternative to JWT. The `get_current_user` dependency will be updated to also accept `X-API-Key` headers.
- Feature 12 (Monitoring) uses the `user_id` already present on all structlog output for per-user query tracing in Sentry and Grafana.


## 14. RAG Pipeline

**Status: ✅ Complete**

### Overview
Retrieval-Augmented Generation layer that improves Feature 4 SQL accuracy by injecting user-specific successful query examples as dynamic few-shot context. The implementation is additive (static prompt remains), tenant-isolated, and fail-safe (falls back silently to static-only behavior on any retrieval failure).

### Tech Stack
| Component | Technology |
|---|---|
| Vector store | pgvector (already in use from Feature 3) |
| Embedding model | `text-embedding-3-small` (already in use) |
| Retrieval | pgvector cosine similarity search |
| Storage | `query_history` table (new) |
| Config controls | `ENABLE_RAG_RETRIEVAL`, `RAG_RETRIEVAL_LIMIT`, `RAG_SIMILARITY_THRESHOLD`, `RAG_DEDUP_WINDOW_HOURS` |
| Integration point | `app/query/pipeline.py` (additive changes only) |

### Features

#### 14.1 Query History Storage
- After successful chat query execution with `row_count > 0`, embed the NL query text and store in `query_history`
- Fields: `nl_query`, `generated_sql`, `embedding (vector 1536)`, `row_count`, `user_id`, `session_id`, `provider`, `model`, `created_at`
- Soft deduplication prevents identical `nl_query` + `user_id` inserts inside a configurable window (`RAG_DEDUP_WINDOW_HOURS`, default 24)
- Called from the chat SSE flow as a non-blocking background task with an independent write session

#### 14.2 Dynamic Few-Shot Retrieval
- At the start of `nl_to_sql()`, retrieve top-k semantically similar past successful queries (`RAG_RETRIEVAL_LIMIT`, default 5)
- Filter retrieved examples by cosine distance threshold (`RAG_SIMILARITY_THRESHOLD`, default 0.4) before prompt injection
- Inject retrieved examples as dynamic context alongside static examples; static examples are never removed
- Falls back to static-only prompt on cold start, disabled flag, missing user/db context, or retrieval errors
- Benchmark endpoint intentionally remains static-only (no RAG retrieval)

#### 14.3 Tenant Isolation
- Retrieval SQL is strictly filtered by `user_id` at the database layer (no Python-side post-filtering)
- No cross-user retrieval is allowed; query history is private per authenticated user boundary
- Config flag: `ENABLE_RAG_RETRIEVAL` gates retrieval globally and preserves static-only operation when disabled

### New Tables
- **`query_history`** — `query_id`, `nl_query`, `generated_sql`, `embedding (vector 1536)`, `row_count`, `user_id`, `session_id`, `provider`, `model`, `created_at`
- HNSW index on `embedding` column

### New Module
- `app/query/rag.py` — `store_successful_query()`, `retrieve_similar_queries()`, `build_rag_context()`

### Migration
- `006_rag_pipeline.py` — `down_revision = "005"`

### Tasks for Developers
- [x] Create query_history table and HNSW index migration
- [x] Build rag.py module with store, retrieve, and context-build functions
- [x] Add retrieve call at start of nl_to_sql() in pipeline.py
- [x] Add store call after successful execution in chat router
- [x] Add RAG config settings (`ENABLE_RAG_RETRIEVAL`, limit, threshold, dedup window)
- [x] Add test coverage for retrieval fallback, benchmark static-only behavior, and non-blocking store scheduling

---

## 15. Anomaly Detection

**Status: ✅ Complete**

### Overview
Nightly automated scanning of newly ingested profiles for contextually unusual oceanographic readings. Distinct from ingestion-time QC flagging (Feature 1) which catches physically impossible values — anomaly detection catches valid-but-unusual readings using contextual comparison. Anomaly investigation flow benefits from RAG being live.

### Tech Stack
| Component | Technology |
|---|---|
| Scheduler | Celery beat (nightly at 02:00 UTC) |
| Detection | Custom Python detectors (no ML model — statistical comparison) |
| Storage | `anomalies` + `anomaly_baselines` tables |
| Notifications | Slack webhook / email (same infrastructure as Feature 10) |
| Frontend | Anomaly feed in sidebar, detail panel, map overlay |

### Features

#### 15.1 Detection Strategies
Four detectors run nightly on profiles ingested in the last 24 hours:

**Spatial Baseline Detector**
Compares a float's reading against all other floats within 200km in the same calendar month across all years. Flags if deviation > 2 standard deviations from the regional mean.

**Float Self-Comparison Detector**
Compares a float's current profile against its own last 10 profiles. Flags sustained shifts > 1.5 standard deviations. Catches instrument drift and real oceanographic changes at a float level.

**Cluster Pattern Detector**
Detects when 3+ floats within 500km show anomalous readings of the same variable within a 7-day window. Catches regional events: upwelling anomalies, cyclone mixing, freshwater intrusions.

**Seasonal Baseline Detector**
Compares against pre-computed climatological monthly averages per region stored in `anomaly_baselines`. Catches values outside expected seasonal range.

#### 15.2 Anomaly Storage
- Severity: `low`, `medium`, `high` based on deviation magnitude
- Fields: `float_id`, `profile_id`, `anomaly_type`, `severity`, `variable`, `baseline_value`, `observed_value`, `deviation_percent`, `description`, `detected_at`, `region`, `is_reviewed`, `reviewed_by`, `reviewed_at`

#### 15.3 Frontend
- Bell icon in SessionSidebar with unreviewed anomaly count badge
- Anomaly detail panel: flagged profile vs baseline chart, metadata, "Investigate in Chat" deep link
- Anomaly overlay on Feature 7's ExplorationMap: flagged float markers with warning indicator
- `PATCH /api/v1/anomalies/{id}/review` to mark as reviewed
- Dedicated anomalies page at `/anomalies` with filterable feed + detail view
- Map toolbar overlay toggle (off by default)

#### 15.4 Relationship to Feature 1
- Feature 1 flags physically impossible values at ingestion (temperature > 40°C, salinity < 0 PSU)
- Feature 15 flags contextually unusual values that are physically valid but statistically anomalous
- They are complementary and non-overlapping

### New Tables
- **`anomalies`** — all fields listed in §15.2 above
- **`anomaly_baselines`** — pre-computed monthly regional averages per variable for seasonal comparison

### New API Endpoints
- `GET /api/v1/anomalies` — list recent anomalies with filters
- `GET /api/v1/anomalies/{anomaly_id}` — full detail
- `PATCH /api/v1/anomalies/{anomaly_id}/review` — mark reviewed
- `POST /api/v1/anomalies/baselines/compute` — admin baseline recomputation trigger

### Migration
- `007_anomaly_detection.py` — `down_revision = "006"`

### Tasks for Developers
- [x] Create anomalies and anomaly_baselines tables migration
- [x] Build app/anomaly/ module with four detector classes
- [x] Build Celery beat scheduler task (nightly 02:00 UTC)
- [x] Compute and store anomaly_baselines via CLI and admin trigger
- [x] Build anomaly API endpoints
- [x] Build anomaly feed in SessionSidebar and `/anomalies` page
- [x] Build anomaly detail panel and chart
- [x] Add anomaly overlay toggle and markers to ExplorationMap
- [x] Write detector/task/API automated tests

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER LAYER                               │
│  Chat Interface  │  Visualization  │  Geospatial Map  │  Auth   │
└─────────────────────────────────────────────────────────────────┘
                                │
┌─────────────────────────────────────────────────────────────────┐
│                     INTELLIGENCE LAYER                          │
│  NL Query Engine  │  RAG Pipeline  │  Anomaly Detection         │
│  Metadata Search  │  Guided Assistant  │  Follow-up Generator   │
└─────────────────────────────────────────────────────────────────┘
                                │
┌─────────────────────────────────────────────────────────────────┐
│                      API LAYER (FastAPI)                        │
│  /query  │  /chat  │  /map  │  /search  │  /export  │  /admin   │
│  /auth   │  /anomalies  │  /floats  │  /datasets                │
└─────────────────────────────────────────────────────────────────┘
                                │
┌─────────────────────────────────────────────────────────────────┐
│                        DATA LAYER                               │
│  PostgreSQL + PostGIS  │  pgvector  │  Redis Cache  │  MinIO    │
└─────────────────────────────────────────────────────────────────┘
                                │
┌─────────────────────────────────────────────────────────────────┐
│                    INGESTION PIPELINE                           │
│  NetCDF Parser (xarray)  │  QC Filter  │  Celery + Redis        │
│  Threshold Outlier Flagging  │  LLM Metadata Generator          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack Summary

| Layer | Technology | Notes |
|---|---|---|
| Frontend | Next.js 14 (App Router), React, Tailwind CSS, shadcn/ui | |
| State management | Zustand | Redux not used |
| Charting | Plotly.js + react-plotly.js | Recharts not used |
| Color scales | cmocean as custom Plotly arrays in lib/colorscales.ts | |
| Maps | Leaflet.js + react-leaflet | Mapbox GL JS not used |
| Map clustering | react-leaflet-cluster | |
| Map draw | leaflet-draw + react-leaflet-draw | |
| Geospatial utils | @turf/turf | |
| Dashboard grid | react-grid-layout | |
| Real-time | SSE via fetch + ReadableStream | WebSocket not used |
| Markdown | react-markdown + remark-gfm + rehype-highlight | |
| Autocomplete | Fuse.js | |
| Fonts | Fraunces, DM Sans, JetBrains Mono (Google Fonts) | |
| Backend API | FastAPI (Python 3.11+) | |
| ORM | SQLAlchemy | |
| Migrations | Alembic | |
| Auth | python-jose + passlib/bcrypt | No third-party auth provider |
| Rate limiting | slowapi | |
| Logging | structlog | |
| SQL validation | sqlglot (AST-based) | |
| LLM providers | DeepSeek (default), Qwen QwQ, Gemma, OpenAI | Custom pipeline, no LangChain |
| Embeddings | OpenAI text-embedding-3-small (1536d) | |
| Vector store | pgvector (HNSW indexes) | Qdrant not used |
| NL→SQL framework | Custom prompt pipeline | LangChain not used |
| Database | PostgreSQL 15 + PostGIS 3 + pgvector | |
| Caching | Redis | |
| Task queue | Celery + Redis | Airflow/Prefect deferred to v2 |
| Object storage | MinIO (dev) / AWS S3 (prod) | |
| Monitoring | Sentry, Prometheus, Grafana, structlog | |
| ORM/Migrations | SQLAlchemy + Alembic | |
| Containerisation | Docker + Docker Compose (dev) | ECS/K8s for prod |

---

*Updated for FloatChat v2.0 — reflects all decisions made through Features 1–7 build, plus new features 13 (Auth), 14 (RAG Pipeline), and 15 (Anomaly Detection).*