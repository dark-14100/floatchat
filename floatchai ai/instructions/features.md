# FloatChat — Complete Feature Breakdown & Technical Specification

> **Product:** FloatChat — A natural language interface for ARGO oceanographic float data  
> **Version:** 1.0  
> **Status:** Pre-Development Specification

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

---

## 1. Data Ingestion Pipeline

### Overview
The ingestion pipeline is the entry point for all ARGO float data into the FloatChat platform. It handles raw NetCDF files, validates structure, normalizes variables, and persists the data for downstream querying and analysis.

### Tech Stack
| Component | Technology |
|---|---|
| File parsing | Python `netCDF4` or `xarray` |
| Data transformation | `pandas`, `numpy` |
| Pipeline orchestration | Apache Airflow or Prefect |
| Job queue | Celery + Redis |
| Storage target | PostgreSQL + PostGIS |
| File staging | AWS S3 or local MinIO |
| Metadata extraction | Custom Python parsers |

### Capabilities

#### 1.1 Upload NetCDF Files
- Accept `.nc` and `.nc4` file uploads via the admin UI or API endpoint
- Support bulk uploads (zip archives containing multiple NetCDF files)
- Validate file format and ARGO compliance before processing begins
- Store raw files in an object store (S3/MinIO) with unique identifiers
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
- Detect and flag outliers (e.g., temperature > 40°C or salinity < 0 PSU) for review

#### 1.4 Store Structured Data
- Insert cleaned float profiles into relational database tables
- Upsert logic: if a float/cycle combination already exists, update rather than duplicate
- Link each profile to its parent dataset/float via foreign keys
- Store profile-level data (one row per depth measurement) and float-level metadata (one row per float)

#### 1.5 Generate Dataset Metadata
- Auto-generate metadata on ingestion: date range, float IDs, variable list, spatial bounding box, profile count
- Store metadata in a dedicated `datasets` table for fast discovery
- Generate human-readable dataset summaries using an LLM call post-ingestion

### Key Outputs
- Structured `profiles` and `measurements` tables in PostgreSQL
- Dataset summary records in `datasets` table
- Float location index (lat/lon per cycle) in `float_positions` table
- Ingestion event logs in `ingestion_jobs` table

### Tasks for Developers
- [ ] Build `ingest_netcdf.py` — core parsing script using `xarray`
- [ ] Implement QC flag filtering logic with configurable thresholds
- [ ] Create Airflow/Prefect DAG for pipeline orchestration
- [ ] Build file upload endpoint (`POST /api/datasets/upload`)
- [ ] Implement upsert logic for float/cycle deduplication
- [ ] Write unit tests for each variable parser
- [ ] Set up S3/MinIO bucket with folder structure by dataset ID
- [ ] Build ingestion job status tracker (polling or WebSocket updates)

---

## 2. Ocean Data Database

### Overview
The central storage layer for all oceanographic data, optimized for the kinds of queries FloatChat needs to perform: time-range filtering, spatial proximity, depth slicing, and multi-variable profile retrieval.

### Tech Stack
| Component | Technology |
|---|---|
| Primary database | PostgreSQL 15+ |
| Geospatial extension | PostGIS 3.x |
| ORM | SQLAlchemy (Python) |
| Migrations | Alembic |
| Query optimization | Indexes, BRIN, GiST |
| Connection pooling | PgBouncer |
| Caching layer | Redis (query result cache) |

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
latitude, longitude, geom (PostGIS POINT), data_mode, profile_url
```

**`measurements`** — one row per depth level within a profile
```
measurement_id (PK), profile_id (FK), pressure, depth_m, temperature, 
salinity, dissolved_oxygen, chlorophyll, nitrate, ph, 
temp_qc, psal_qc, doxy_qc (quality flags per variable)
```

**`datasets`** — one row per ingested dataset
```
dataset_id (PK), name, source_url, ingestion_date, date_range_start, 
date_range_end, bbox (PostGIS POLYGON), float_count, profile_count, 
variable_list (JSONB), summary_text
```

### Features

#### 2.1 PostgreSQL Storage
- All data stored in normalized relational tables
- JSONB columns for flexible metadata and variable availability per float
- Partitioning on `profiles` table by year for performance at scale

#### 2.2 PostGIS Geospatial Indexing
- `geom` column on `profiles` table (type: `GEOGRAPHY(POINT, 4326)`)
- GiST index on `geom` for fast spatial queries (`ST_DWithin`, `ST_Within`, `ST_Intersects`)
- Pre-defined ocean basin polygons stored in `ocean_regions` reference table
- Named region lookup: "Arabian Sea", "Bay of Bengal", "Indian Ocean" → polygon → float query

#### 2.3 Optimized Queries for Ocean Profiles
- Composite indexes on `(latitude, longitude)`, `(juld_timestamp)`, `(float_id, cycle_number)`
- BRIN index on `juld_timestamp` for time-range scans
- Partial indexes for common filter combinations (e.g., BGC floats only)
- Materialized views for frequently queried summaries (e.g., float position history)

#### 2.4 Dataset Versioning
- Each ingestion tagged with `dataset_version` and `ingestion_timestamp`
- Old versions retained with `is_active` flag for rollback
- Diff log stored in `dataset_versions` table

### Supported Filters
- **Time:** `WHERE juld_timestamp BETWEEN $1 AND $2`
- **Region:** `WHERE ST_DWithin(geom, ST_MakePoint($lon, $lat)::geography, $radius_meters)`
- **Depth:** `WHERE pressure BETWEEN $min AND $max`
- **Variable availability:** `WHERE doxy_qc IS NOT NULL` (float has O₂ data)
- **Ocean basin:** JOIN with `ocean_regions` polygon table

### Tasks for Developers
- [ ] Write full Alembic migration for all tables
- [ ] Enable PostGIS extension (`CREATE EXTENSION postgis`)
- [ ] Create GiST index on `profiles.geom`
- [ ] Load ocean basin reference polygons (use Natural Earth or IHO Sea Areas shapefile)
- [ ] Configure PgBouncer connection pool
- [ ] Set up Redis cache with 5-minute TTL for repeated NL queries
- [ ] Write query performance benchmarks for 10M+ measurement rows
- [ ] Build `db.py` data access layer with reusable filter functions

---

## 3. Metadata Search Engine

### Overview
Allows researchers to discover what data is available before running queries. The metadata search engine indexes dataset summaries, float characteristics, and temporal/spatial attributes so users can find relevant data through natural language or structured filters.

### Tech Stack
| Component | Technology |
|---|---|
| Search index | Elasticsearch 8.x or OpenSearch |
| Embedding model | `text-embedding-3-small` (OpenAI) or `sentence-transformers` |
| Vector store | pgvector (PostgreSQL extension) or Qdrant |
| Backend | FastAPI (Python) |
| Indexing trigger | Post-ingestion pipeline hook |

### Features

#### 3.1 Semantic Search
- Embed dataset summaries and float descriptions using a sentence embedding model
- Store embeddings in pgvector or Qdrant
- At query time, embed the user's natural language query and find closest matches via cosine similarity
- Return ranked list of matching datasets with relevance scores

#### 3.2 Dataset Summaries
- Each dataset has a plain-English summary auto-generated at ingestion time
- Summary includes: float count, region, date range, variables available, data quality overview
- Summaries are indexed and searchable
- Display in chat UI before user runs a detailed query

#### 3.3 Float Discovery
- Search for individual floats by WMO ID, deployment region, float type (core/BGC), or variable availability
- Return float profile: active date range, last known position, measured variables
- Link float records to their profile histories

#### 3.4 Region-Based Lookup
- Named region search: user types "Arabian Sea" → resolve to bounding polygon → return floats within
- Use a reference table of named ocean regions with polygon geometries
- Support fuzzy matching on region names ("Bay of Bengal" ≈ "Bengal Bay")

### Example Queries
- `floats near Arabian Sea` → semantic + spatial lookup
- `data from March 2023` → date filter on dataset index
- `BGC floats in Indian Ocean` → float type + region filter

### Tasks for Developers
- [ ] Set up Elasticsearch/OpenSearch cluster or pgvector extension
- [ ] Build post-ingestion hook to generate and store embeddings
- [ ] Implement `search_datasets(query: str)` endpoint
- [ ] Build region name → polygon resolver using reference table
- [ ] Write API endpoint: `GET /api/search?q=...`
- [ ] Build relevance scoring logic (combine semantic score + recency + region match)
- [ ] Add fuzzy matching for region names (using `fuzzywuzzy` or Elasticsearch fuzzy queries)

---

## 4. Natural Language Query Engine

### Overview
The core intelligence layer of FloatChat. Converts a researcher's plain English question into a valid SQL query, executes it against the ocean database, and returns structured results. This feature is what separates FloatChat from a basic data portal.

### Tech Stack
| Component | Technology |
|---|---|
| LLM | GPT-4o or Claude 3.5 Sonnet (via API) |
| NL→SQL framework | LangChain or custom prompt pipeline |
| SQL validation | `sqlglot` (Python SQL parser) |
| Query execution | SQLAlchemy + PostgreSQL |
| Context management | Redis (conversation history) |
| Safety layer | Query whitelist / read-only DB user |

### Features

#### 4.1 Convert Natural Language to SQL
- Accept a free-text user question as input
- Build a structured system prompt containing: database schema, table relationships, column descriptions, example query pairs (few-shot)
- Send to LLM with instruction to return only valid PostgreSQL SQL
- Parse and validate the returned SQL before execution
- Map common phrases to correct SQL patterns:
  - "near Sri Lanka" → `ST_DWithin(geom, ST_MakePoint(80.7, 7.8)::geography, 200000)`
  - "last year" → `juld_timestamp >= NOW() - INTERVAL '1 year'`
  - "deep profiles" → `WHERE pressure > 1500`

#### 4.2 Query Interpretation
- Before executing, generate a human-readable interpretation of what the query will do
- Display this as a "I'm going to query..." message in the chat
- Allow user to confirm or correct before execution

#### 4.3 Context Understanding
- Maintain conversation context across turns in Redis
- Support pronoun resolution: "show those same floats in March" → replace float filter from prior query
- Support relative references: "now show me the temperature" → reuse spatial/temporal filter from last query
- Store last 10 query turns per session

#### 4.4 Query Validation
- Parse generated SQL using `sqlglot` to detect syntax errors before execution
- Enforce read-only queries only (no `INSERT`, `UPDATE`, `DELETE`, `DROP`)
- Limit result set size (default: 10,000 rows, max: 100,000) to prevent overload
- Reject queries touching non-whitelisted tables
- If SQL is invalid, retry with LLM up to 3 times with error feedback in the prompt

### Example Flow
```
User input:    "show temperature near Sri Lanka in 2023"
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
- [ ] Write system prompt with full schema description and 15+ few-shot NL→SQL examples
- [ ] Build `nl_to_sql(query: str, context: list) → str` function
- [ ] Integrate `sqlglot` for pre-execution validation
- [ ] Implement retry loop with error feedback (max 3 attempts)
- [ ] Create read-only PostgreSQL user for query execution
- [ ] Build `execute_safe_query(sql: str) → DataFrame` function with row limit enforcement
- [ ] Store conversation context in Redis keyed by `session_id`
- [ ] Build geographic entity resolver (place names → lat/lon via geocoding API or curated lookup table)
- [ ] Write test suite with 50+ NL query examples and expected SQL patterns

---

## 5. Conversational Chat Interface

### Overview
The primary interface researchers use to interact with FloatChat. A chat UI that feels like asking a knowledgeable oceanography assistant — supporting follow-up questions, showing results inline, and guiding users to better queries.

### Tech Stack
| Component | Technology |
|---|---|
| Frontend framework | React (Next.js 14) |
| UI components | Tailwind CSS + shadcn/ui |
| Real-time updates | WebSocket (Socket.io) or SSE |
| State management | Zustand or Redux Toolkit |
| Backend (chat API) | FastAPI (Python) |
| Session management | JWT + Redis |
| Message persistence | PostgreSQL (`chat_sessions` table) |

### Features

#### 5.1 Chat UI
- Clean, minimal chat interface with user messages on right, assistant on left
- Message history scrolls up; latest message anchored at bottom
- Input box with submit button and keyboard shortcut (Enter to send)
- Loading indicator (typing animation) while query is being processed
- Inline display of results: tables, charts, and maps appear inside the conversation thread
- Markdown rendering for assistant responses

#### 5.2 Follow-Up Questions
- Each assistant response includes 2–3 suggested follow-up questions as clickable chips
- Example: after showing temperature profiles, suggest "Show salinity for the same region" or "Plot these as depth profiles"
- Follow-up questions are generated by the LLM based on the current result context

#### 5.3 Context Memory
- Session-scoped memory: each conversation remembers all prior queries and results
- User can start a new session to reset context
- Optional: named sessions so researchers can return to a previous investigation
- Conversation history stored in `chat_sessions` and `chat_messages` tables

#### 5.4 Suggestions on Load
- On first open, display 4–6 example queries to help new users get started
- Examples tailored to available datasets (e.g., "Show BGC floats in the Bay of Bengal")
- Rotated periodically or based on recently ingested data

#### 5.5 Error Guidance
- When a query fails or returns no results, provide a clear explanation
- Suggest reformulations: "No floats found within 50km. Try expanding the search radius."
- Distinguish between query errors (bad NL input), SQL errors (retry), and empty results (data not available)

### Example Flow
```
User:      "Show temperature profiles near the Maldives in January 2024"
System:    [spinner] → [table of results + depth chart] 
           "Found 87 temperature profiles within 300km of the Maldives (Jan 2024)"
           [Suggested: "Show salinity for the same region" | "Plot depth vs temperature" | "Export this data"]

User:      "Now show me salinity too"
System:    [understands context] → queries same region/time with salinity variable
```

### Tasks for Developers
- [ ] Scaffold Next.js app with chat layout (sidebar + chat window)
- [ ] Build `ChatMessage` component supporting text, tables, charts, and maps
- [ ] Implement WebSocket or SSE connection for streaming responses
- [ ] Build session management: create, store, retrieve chat history
- [ ] Build `SuggestedFollowUps` component with LLM-generated chips
- [ ] Build error state component with reformulation suggestions
- [ ] Implement markdown renderer (`react-markdown` + syntax highlighting)
- [ ] Build "New Conversation" and session history sidebar

---

## 6. Data Visualization Dashboard

### Overview
Researchers need to see oceanographic data visually — not just as raw numbers. The visualization layer renders interactive charts and plots directly inside the chat interface and in a dedicated dashboard view.

### Tech Stack
| Component | Technology |
|---|---|
| Charting library | Plotly.js or Recharts |
| Ocean-specific plots | Custom React components on top of Plotly |
| Map rendering | Leaflet.js or Mapbox GL JS |
| Color scales | cmocean (oceanography-standard colormaps) |
| Data format | JSON (from API) or in-memory DataFrame via pandas |
| Dashboard layout | React grid layout (`react-grid-layout`) |

### Chart Types

#### 6.1 Ocean Profile Plots
- Vertical profile: X-axis = variable value, Y-axis = pressure/depth (inverted — deeper = lower)
- Supports multiple variables on the same plot (dual X-axis for temperature and salinity)
- Color-coded by float ID when multiple floats are plotted together
- Interactive tooltips showing exact values at each depth

#### 6.2 Depth vs Temperature
- Standard T-S (Temperature-Salinity) diagram: scatter plot with temperature on X, salinity on Y, colored by depth
- Reveals water mass characteristics and mixing
- Interactive zoom and point hover

#### 6.3 Salinity Profiles
- Same format as temperature profiles
- Overlay option: show both temperature and salinity on the same depth axis

#### 6.4 Time Series
- Line chart of variable (e.g., surface temperature) over time for a selected float or region
- X-axis = date, Y-axis = variable value
- Filterable by depth level (e.g., "surface only" = pressure < 10 dbar)
- Multi-float overlays for comparison

### Map Views

#### 6.5 Float Trajectories
- Polyline on map tracing the path of one or more floats over time
- Color gradient from start (blue) to end (red) to show temporal progression
- Click on a point to show profile details for that cycle

#### 6.6 Float Positions
- Scatter map of all float positions matching a query
- Color-coded by variable value (e.g., surface temperature) using cmocean `thermal` colormap
- Clustered at low zoom levels

#### 6.7 Region Selection
- Draw-tool on map to define a custom bounding box or polygon
- Selected region feeds back into the query engine as a spatial filter

### Tasks for Developers
- [ ] Build reusable `OceanProfileChart` component (vertical profile)
- [ ] Build `TSdiagram` component (T-S scatter plot)
- [ ] Build `TimeSeries` component with multi-float support
- [ ] Build `FloatTrajectoryMap` component using Leaflet/Mapbox
- [ ] Build `FloatPositionMap` with cmocean color scales
- [ ] Build `RegionSelector` map draw tool that emits a GeoJSON polygon
- [ ] Implement chart export (PNG/SVG download button on each chart)
- [ ] Build `VisualizationPanel` that auto-selects chart type based on query result shape
- [ ] Add cmocean colorscales as custom Plotly colormaps

---

## 7. Geospatial Exploration

### Overview
Map-first discovery of oceanographic data. Researchers can explore float locations visually, select regions interactively, and trigger queries directly from the map.

### Tech Stack
| Component | Technology |
|---|---|
| Map library | Mapbox GL JS or Leaflet.js |
| Geospatial queries | PostGIS (backend), Turf.js (frontend) |
| Geocoding | OpenCage or Mapbox Geocoding API |
| Ocean basin polygons | IHO Sea Areas shapefile or custom GeoJSON |
| Backend | FastAPI spatial query endpoints |

### Features

#### 7.1 Nearest Floats
- Given a point (user click or typed location), return the N nearest active floats
- Uses `ST_DWithin` + `ST_Distance` in PostGIS
- Display results on map with distance labels

#### 7.2 Radius Queries
- User draws a circle on the map (click + drag radius)
- System queries all float profiles within that radius
- Radius displayed in km with adjustable slider
- Results feed directly into the chat as a new query result

#### 7.3 Ocean Basin Filtering
- Sidebar list of named ocean basins: Atlantic, Pacific, Indian, Arctic, Southern
- Sub-regions: Arabian Sea, Bay of Bengal, Caribbean, Mediterranean, etc.
- Click a basin → filter map to show only floats in that region
- Uses pre-loaded polygon geometries in `ocean_regions` table

#### 7.4 Coordinate-Based Search
- Input field accepting decimal lat/lon (e.g., `12.5, 80.2`) or degree notation
- Geocoding support: type "Chennai" → resolve to coordinates → show nearby floats
- Float detail panel opens on click: shows float ID, last profile date, available variables

### Tasks for Developers
- [ ] Set up Mapbox GL JS base map with ocean tile layer
- [ ] Build `NearestFloatsPanel` triggered by map click
- [ ] Build circle-draw tool with radius control; wire to `POST /api/query/spatial`
- [ ] Load and render ocean basin polygons as interactive GeoJSON layers
- [ ] Integrate geocoding API for place-name → coordinate resolution
- [ ] Build float detail popup component (shows metadata + mini profile chart)
- [ ] Implement deep link: map selection → pre-filled chat query

---

## 8. Data Export System

### Overview
Researchers frequently need to take data out of FloatChat for use in their own analysis tools (Python notebooks, MATLAB, QGIS). The export system delivers query results in standard scientific data formats.

### Tech Stack
| Component | Technology |
|---|---|
| CSV generation | Python `pandas` (`to_csv`) |
| NetCDF export | Python `netCDF4` or `xarray` |
| JSON export | Python `json` / FastAPI `JSONResponse` |
| File delivery | Presigned S3 URL or direct file stream |
| Async generation | Celery task for large exports |
| Progress tracking | Redis task status |

### Export Formats

#### 8.1 CSV
- Flat table with one row per measurement
- Columns: `profile_id`, `float_id`, `timestamp`, `latitude`, `longitude`, `pressure`, `temperature`, `salinity`, `oxygen`, `qc_flags`
- UTF-8 encoded, comma-separated
- Suitable for Excel, pandas, R

#### 8.2 NetCDF
- Reconstruct ARGO-compliant NetCDF from query results
- Preserve original variable names, units, and QC flag conventions
- Include global attributes: source dataset, query parameters, export timestamp
- Suitable for MATLAB, xarray, ocean modeling software

#### 8.3 JSON
- Structured JSON with metadata envelope:
  ```json
  {
    "query": "...",
    "generated_at": "...",
    "profile_count": 123,
    "profiles": [...]
  }
  ```
- Suitable for downstream API consumers and JavaScript apps

### Export Types

#### 8.4 Raw Profiles
- All measurements for selected profiles at all depth levels
- No aggregation; preserves full vertical resolution

#### 8.5 Filtered Datasets
- Only the variables and depth range matching the user's query
- Reduces file size for focused analysis

#### 8.6 Query Results
- Export exactly what was returned in the chat result
- One-click from any chat result view
- Adds query metadata as a comment or attribute in the file

### Tasks for Developers
- [ ] Build `export_csv(query_result: DataFrame) → bytes` function
- [ ] Build `export_netcdf(profiles: list) → bytes` function using `xarray`
- [ ] Build `export_json(query_result: dict) → str` function
- [ ] Build `POST /api/export` endpoint accepting format + filter params
- [ ] Implement async export for results >50MB (Celery task + presigned S3 URL)
- [ ] Build download progress indicator in chat UI
- [ ] Add "Export" button to every query result panel in the chat

---

## 9. Guided Query Assistant

### Overview
Not all users know what data is available or how to ask for it. The Guided Query Assistant acts as an interactive onboarding layer — helping new users discover the right query through suggestions, autocomplete, and clarifying questions.

### Tech Stack
| Component | Technology |
|---|---|
| Autocomplete | React + Fuse.js or custom trie |
| Clarification logic | LLM (GPT-4o / Claude) with structured output |
| Query templates | JSON-defined template library |
| UI | React typeahead input component |

### Features

#### 9.1 Suggested Queries
- Display a gallery of example queries on the home/empty state screen
- Categorized: "Explore Temperature", "Find BGC Floats", "Compare Regions"
- Personalized over time based on user's past queries (stored in session history)
- Refreshed based on newly ingested datasets

#### 9.2 Autocomplete
- As user types in the chat input, show matching query completions
- Completions sourced from: query templates, past successful queries, common oceanographic terms
- Highlight matched characters; select with Tab or arrow keys

#### 9.3 Clarification Prompts
- When a query is too vague, the assistant asks a targeted clarifying question rather than guessing
- Clarification logic:
  - "show ocean data" → "What variable are you interested in? Temperature, salinity, or dissolved oxygen?"
  - "floats in 2023" → "Which ocean region? (e.g., Indian Ocean, Bay of Bengal, Arabian Sea)"
  - "deep profiles" → "How deep? Below 500m, 1000m, or 2000m?"
- Clarifying questions presented as clickable option chips, not free text, for speed

### Example Flow
```
User:    "show ocean data"
System:  "What would you like to explore?"
         [Temperature] [Salinity] [Dissolved Oxygen] [Chlorophyll]
User:    clicks [Temperature]
System:  "Which region?"
         [Arabian Sea] [Bay of Bengal] [Indian Ocean] [Custom area]
User:    clicks [Arabian Sea]
System:  "What time period?"
         [Last 3 months] [Last year] [All available data] [Custom range]
→ Full query assembled and executed
```

### Tasks for Developers
- [ ] Build query template library (JSON file with 30+ templates)
- [ ] Build `SuggestedQueryGallery` component for empty state
- [ ] Build typeahead autocomplete component with Fuse.js fuzzy matching
- [ ] Implement clarification detection in NL query engine (detect underspecified queries)
- [ ] Build `ClarificationWidget` component with chip-based answer selection
- [ ] Log clarification flows to improve templates over time

---

## 10. Dataset Management

### Overview
Administrative functionality allowing data managers to upload new ARGO datasets, monitor ingestion status, manage metadata, and retire outdated datasets.

### Tech Stack
| Component | Technology |
|---|---|
| Admin UI | React (same Next.js app, admin route) |
| Auth | Role-based access control (RBAC) — admin role required |
| Backend | FastAPI admin endpoints |
| Job tracking | Celery + Redis + PostgreSQL (`ingestion_jobs` table) |
| Storage | S3/MinIO for raw files |

### Features

#### 10.1 Upload Datasets
- Admin UI with drag-and-drop file upload (single or bulk)
- Supported: individual `.nc` files, zip archives
- Upload progress bar with file size and estimated time
- Automatic trigger of ingestion pipeline on successful upload
- Email/Slack notification to admin on completion

#### 10.2 Track Ingestion Status
- Dashboard showing all ingestion jobs: pending, running, succeeded, failed
- Per-job detail: file name, start time, duration, profiles ingested, errors encountered
- Real-time status updates via WebSocket
- Retry failed jobs with one click
- Error log viewer for debugging parse failures

#### 10.3 Manage Dataset Metadata
- Edit dataset name, description, and tags post-ingestion
- Regenerate dataset summary using LLM (manual trigger)
- View dataset statistics: float count, profile count, date range, variable list
- Mark dataset as "public" or "internal"

#### 10.4 Remove Outdated Datasets
- Soft delete: mark dataset as inactive (hides from search, preserves data)
- Hard delete: remove all associated profiles, measurements, and raw files
- Confirmation dialog with impact summary before deletion
- Audit log of all delete operations

### Tasks for Developers
- [ ] Build admin dashboard page (protected route, admin role only)
- [ ] Build `DatasetUploadPanel` with drag-and-drop and progress tracking
- [ ] Build `IngestionJobsTable` with real-time status via WebSocket
- [ ] Build `DatasetDetailPage` with metadata editor
- [ ] Implement soft delete + hard delete API endpoints
- [ ] Build audit log table (`admin_audit_log`) and display in UI
- [ ] Set up email/Slack notifications on ingestion complete/failed (via SendGrid or webhook)

---

## 11. API Layer

### Overview
A RESTful API that exposes FloatChat's core capabilities to external tools — research workflows, other dashboards, and automated scripts. The API makes FloatChat a platform, not just a UI.

### Tech Stack
| Component | Technology |
|---|---|
| Framework | FastAPI (Python) |
| Auth | API key (header: `X-API-Key`) + JWT for session auth |
| Rate limiting | `slowapi` (FastAPI middleware) |
| Docs | Auto-generated OpenAPI/Swagger at `/docs` |
| Versioning | URL versioning: `/api/v1/...` |
| CORS | Enabled for configured origins |

### Endpoints

#### 11.1 Query Endpoint
```
POST /api/v1/query
Body: { "query": "show temperature near Sri Lanka in 2023", "session_id": "..." }
Response: { "sql": "...", "interpretation": "...", "results": [...], "chart_config": {...} }
```
Accepts a natural language query, runs the full NL→SQL→execute pipeline, returns structured results.

#### 11.2 Dataset Search
```
GET /api/v1/datasets/search?q=BGC+floats+Indian+Ocean
Response: { "datasets": [{ "id": "...", "name": "...", "summary": "...", "score": 0.87 }] }
```
Semantic + keyword search across dataset metadata.

#### 11.3 Visualization Data
```
GET /api/v1/profiles/{profile_id}/chart-data?variables=temperature,salinity
Response: { "depth": [...], "temperature": [...], "salinity": [...] }
```
Returns data formatted for direct use in frontend charting libraries.

#### 11.4 Export Endpoint
```
POST /api/v1/export
Body: { "query": "...", "format": "csv|netcdf|json", "filters": {...} }
Response: { "download_url": "https://...", "expires_at": "..." } 
```
Triggers an export job and returns a presigned download URL.

#### 11.5 Float Info
```
GET /api/v1/floats/{wmo_id}
Response: { "float_id": "...", "type": "BGC", "last_position": {...}, "variables": [...], "profile_count": 234 }
```

### Tasks for Developers
- [ ] Scaffold FastAPI app with versioned router (`/api/v1`)
- [ ] Implement API key authentication middleware
- [ ] Build all 5 core endpoint handlers
- [ ] Add rate limiting (100 req/min per API key default)
- [ ] Write OpenAPI descriptions for all endpoints and fields
- [ ] Build integration test suite for all endpoints
- [ ] Set up CORS policy for approved frontend origins
- [ ] Write API usage documentation (Postman collection or Markdown guide)

---

## 12. System Monitoring

### Overview
Operational reliability infrastructure to ensure FloatChat is healthy, performant, and debuggable. Covers logging, error tracking, performance metrics, and ingestion monitoring.

### Tech Stack
| Component | Technology |
|---|---|
| Logging | Python `structlog` → stdout → Loki or CloudWatch |
| Error tracking | Sentry (Python SDK + React SDK) |
| Metrics | Prometheus + Grafana |
| Uptime monitoring | UptimeRobot or Healthchecks.io |
| Alerting | PagerDuty or Slack webhook |
| Tracing | OpenTelemetry (optional, for distributed traces) |

### Features

#### 12.1 Logging
- Structured JSON logs for every API request: `timestamp`, `endpoint`, `method`, `status_code`, `latency_ms`, `user_id`, `session_id`
- Log every NL query with: raw input, generated SQL, execution time, row count returned
- Log ingestion events: file name, records parsed, QC flags filtered, errors
- Log levels: DEBUG (dev), INFO (staging/prod), ERROR always on
- Centralized log aggregation (Loki/CloudWatch) with search and tail functionality

#### 12.2 Error Tracking
- Sentry integration on both FastAPI backend and Next.js frontend
- Capture unhandled exceptions with full stack trace and request context
- Group similar errors; track error frequency and affected users
- Alert on new error types or error rate spikes
- Custom Sentry tags: `query_type`, `dataset_id`, `float_id` for searchable context

#### 12.3 Performance Metrics
- Track via Prometheus:
  - API request latency (p50, p95, p99) per endpoint
  - NL→SQL generation time (LLM call latency)
  - Database query execution time
  - Cache hit rate (Redis)
  - Active WebSocket connections
- Grafana dashboard with real-time charts for all above metrics
- Alert if p95 latency > 5s on `/api/v1/query`

#### 12.4 Ingestion Monitoring
- Track per ingestion job: start time, duration, records ingested, error count
- Alert on ingestion failure (Slack webhook notification)
- Daily summary report: total profiles ingested, new floats discovered, failed files
- Dashboard widget showing ingestion pipeline health (last run time, success/failure rate)

### Tasks for Developers
- [ ] Set up `structlog` with JSON formatter in FastAPI
- [ ] Configure Sentry DSN for both backend and frontend
- [ ] Install and configure Prometheus client in FastAPI (`prometheus-fastapi-instrumentator`)
- [ ] Build Grafana dashboard with core metrics panels
- [ ] Set up alerting rules in Grafana (latency, error rate, disk usage)
- [ ] Build ingestion monitoring dashboard in admin UI
- [ ] Set up Slack webhook for critical alerts (ingestion failures, p99 latency breach)
- [ ] Write runbook: how to respond to common alerts

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────┐
│                     USER LAYER                          │
│  Chat Interface  │  Visualization  │  Geospatial Map    │
└─────────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────────┐
│                  INTELLIGENCE LAYER                     │
│ NL Query Engine  │  Guided Assistant  │  Metadata Search│
└─────────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────────┐
│                   API LAYER (FastAPI)                   │
│  /query  │  /datasets  │  /export  │  /floats  │ /admin │
└─────────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────────┐
│                  DATA LAYER                             │
│  PostgreSQL + PostGIS  │  Redis Cache  │  S3/MinIO      │
└─────────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────────┐
│                INGESTION PIPELINE                       │
│  NetCDF Parser  │  QC Filter  │  Airflow Orchestration  │
└─────────────────────────────────────────────────────────┘
```

---

## Tech Stack Summary

| Layer | Technology |
|---|---|
| Frontend | Next.js 14, React, Tailwind CSS, shadcn/ui |
| Charting | Plotly.js, cmocean colormaps |
| Maps | Mapbox GL JS or Leaflet.js |
| Backend API | FastAPI (Python 3.11+) |
| NL→SQL | GPT-4o or Claude 3.5 Sonnet |
| Data parsing | xarray, netCDF4, pandas, numpy |
| Database | PostgreSQL 15 + PostGIS 3 |
| Search/Vectors | pgvector or Qdrant + OpenAI embeddings |
| Pipeline | Apache Airflow or Prefect |
| Task queue | Celery + Redis |
| Caching | Redis |
| Object storage | AWS S3 or MinIO |
| Monitoring | Sentry, Prometheus, Grafana, structlog |
| Auth | JWT + API keys + RBAC |
| ORM/Migrations | SQLAlchemy + Alembic |
| Deployment | Docker + Docker Compose (dev), ECS/K8s (prod) |

---

*Document generated for FloatChat v1.0 pre-development specification.*
