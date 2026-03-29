# FloatChat — Product Requirements Document

**Version:** 2.0
**Status:** In Development
**Last Updated:** Reflects all decisions made through Features 1–7

---

## Overview

FloatChat is an AI-powered conversational interface that enables researchers, climate analysts, and students to explore ARGO oceanographic float data using natural language. The system ingests raw NetCDF files, stores structured ocean data in a PostGIS-enabled PostgreSQL database, and provides natural language querying, semantic search, interactive visualization, geospatial exploration, and data export through a conversational chat interface.

FloatChat reduces ocean data exploration time from hours to seconds and enables non-technical users to access data that previously required domain knowledge and programming skills to interpret.

---

## 1. Purpose & Business Context

### Background
Oceanographic datasets from the ARGO float program are massive and complex. Data is stored in NetCDF files and requires domain expertise and programming skills to interpret. The ARGO program maintains 4,000+ active floats generating millions of ocean profiles with global coverage.

### Problem
Most potential users — climate analysts, students, policy researchers — cannot query or visualize ARGO data without writing code. Even simple questions require downloading datasets, writing scripts, and generating plots manually.

### Solution
FloatChat provides a conversational interface where a researcher types a plain English question and instantly receives structured results, visualizations, and the ability to export data in standard scientific formats.

### B2B SaaS Model
FloatChat is designed as a multi-tenant B2B SaaS platform for oceanographic research institutions, climate agencies, and academic organisations. Key commercial differentiators:

- **Tenant-isolated query learning** — each organisation's successful queries build their own RAG corpus. The system gets smarter the longer an organisation uses it, and switching to a competitor means starting from zero.
- **Usage tier differentiation** — Basic tier uses static prompt engineering. Pro tier uses RAG-enhanced dynamic retrieval with higher SQL accuracy.
- **Anomaly detection as a premium feature** — automated nightly scanning, alert feeds, and investigation workflows provide passive value even when researchers are not actively querying.
- **Feedback loop** — query rating and result correction data improves the system over time, creating a compounding accuracy advantage over static NL→SQL tools.

---

## 2. Product Vision

A conversational interface for ocean data that allows researchers to ask questions in plain English and instantly receive insights, visualizations, and exportable results — without writing a single line of code.

```
Natural Language → SQL Generation → Data Retrieval → Visualization → Export
```

---

## 3. User Personas

### Ocean Researcher
Needs fast multi-variable analysis, profile comparisons, and data export for publications. Values SQL accuracy and scientific correctness (inverted depth axes, correct QC filtering, cmocean colormaps).

### Climate Analyst
Needs regional trend analysis and time series without coding. Values clear error guidance, follow-up suggestions, and anomaly alerts for their region of interest.

### Student
Needs an intuitive entry point into oceanographic data. Values guided query suggestions, clarification prompts, and the ability to explore visually before asking specific questions.

### Data Manager (Admin)
Needs to upload new datasets, monitor ingestion status, manage metadata, and retire outdated data. Requires admin role enforcement and audit logging.

---

## 4. Product Scope

### In Scope (v1)
- NetCDF ingestion pipeline with QC filtering and threshold-based outlier flagging
- PostgreSQL + PostGIS ocean data storage with spatial indexing
- Semantic metadata search using pgvector and OpenAI embeddings
- Multi-provider NL→SQL query engine (DeepSeek, Qwen, Gemma, OpenAI)
- RAG pipeline for dynamic few-shot retrieval from successful query history
- Conversational chat interface with SSE streaming and session memory
- Oceanographic data visualizations (depth profiles, T-S diagrams, time series, maps)
- Geospatial exploration map with nearest float queries, radius queries, and basin filtering
- Data export in CSV, NetCDF, and JSON formats
- Guided query assistant with autocomplete and clarification chips
- Admin dataset management panel
- User authentication with JWT and RBAC
- Oceanographic anomaly detection with nightly scanning and alert feed
- Public API with API key authentication and rate limiting
- System monitoring with structured logging, Sentry, Prometheus, and Grafana

### Out of Scope (v1)
- Real-time float position streaming (WebSocket feed from ARGO network)
- Satellite dataset integration (SST, chlorophyll from satellite)
- 3D ocean section plots
- Animated float trajectory playback
- Offline/PWA mode
- Multi-language NL query support
- Collaborative shared sessions

### Future Roadmap (v2+)
- Real-time ARGO data sync (auto-ingest new floats as they surface)
- Collaborative sessions (shared conversation threads for research teams)
- Saved query library with parameterised templates
- Notebook integration (Open in Jupyter button)
- Scheduled reports (email weekly summaries for a region)
- Satellite dataset integration (Copernicus Marine Service)
- Citation generator for academic publications
- Mobile app (React Native)
- Institutional accounts with team workspaces
- Multi-language NL query support

---

## 5. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER LAYER                               │
│   Chat Interface  │  Visualization  │  Geospatial Map  │  Auth  │
└─────────────────────────────────────────────────────────────────┘
                                │
┌─────────────────────────────────────────────────────────────────┐
│                     INTELLIGENCE LAYER                          │
│  NL Query Engine  │  RAG Pipeline  │  Guided Assistant          │
│  Metadata Search  │  Anomaly Detection  │  Follow-up Generator  │
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
│  NetCDF Parser  │  QC Filter  │  Outlier Flagging               │
│  Celery + Redis  │  LLM Metadata Generator                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Functional Requirements

### 6.1 Data Ingestion
- Parse NetCDF files using `xarray`
- Extract core ARGO variables: pressure, temperature, salinity, dissolved oxygen, chlorophyll-a
- Extract BGC variables: nitrate, pH, bbp700, downwelling irradiance
- Apply QC flag filtering (retain QC 1 and 2 by default)
- Flag static threshold outliers at ingestion (temperature > 40°C, salinity < 0 PSU)
- Convert Julian dates to ISO 8601 timestamps
- Upsert logic for float/cycle deduplication
- Generate LLM dataset summaries post-ingestion
- Track ingestion jobs in `ingestion_jobs` table

### 6.2 Metadata Search
- Semantic search over dataset summaries using pgvector cosine similarity
- OpenAI `text-embedding-3-small` (1536 dimensions) for all embeddings
- HNSW indexes on embedding tables for fast retrieval
- Hybrid scoring: cosine similarity + recency boost + region match boost
- Fuzzy region name matching via `pg_trgm` (e.g., "Bengal Bay" → "Bay of Bengal")
- Post-ingestion automatic embedding generation via Celery task

### 6.3 Natural Language Query Engine
- Multi-provider LLM support: DeepSeek (default), Qwen, Gemma, OpenAI
- Custom prompt pipeline — no LangChain dependency
- Static schema prompt with full column descriptions and 20+ oceanographic few-shot examples
- SQL validation: syntax (sqlglot), read-only enforcement (AST inspection), table whitelist, PostGIS cast check
- Retry loop: up to 3 attempts with validation error feedback
- Row limit: default 10,000, max 100,000
- Statement timeout: 30 seconds
- Confirmation mode for estimated results > 50,000 rows
- Geography resolver using curated lookup file (50+ Indian Ocean locations)
- Redis session context: last 10 turns stored, last 3 included in prompt
- Benchmark endpoint comparing all three providers on a single query

### 6.4 RAG Pipeline
- Store every successful NL query with its embedding, generated SQL, row count, user ID, provider, and model in `query_history` table
- At query time, retrieve top 5 semantically similar past successful queries using pgvector
- Inject retrieved examples as dynamic few-shot context into the schema prompt
- Tenant-isolated: retrieval is scoped to the organisation's own query history
- Pro-tier feature: Basic tier uses static prompt only
- Feedback loop: successful execution triggers automatic storage

### 6.5 Conversational Chat Interface
- SSE streaming (not WebSocket) for real-time response delivery
- SSE event sequence: `thinking → interpreting → executing → results → suggestions → done`
- Session management via `chat_sessions` and `chat_messages` PostgreSQL tables
- Follow-up suggestion generation (2–3 suggestions per response) via separate LLM call
- Load-time example queries from Feature 3's dataset summaries, cached in Redis
- Inline result display: tables, charts, and maps within the conversation thread
- Markdown rendering via `react-markdown` + `remark-gfm` + `rehype-highlight`
- Zustand state management (not Redux)
- Anonymous sessions in v1 (browser UUID); migrated to authenticated sessions after Auth feature

### 6.6 Data Visualization
- Plotly.js for all charts (not Recharts or Chart.js)
- Leaflet.js for all maps (not Mapbox GL JS — no API key required)
- cmocean colorscales implemented as custom Plotly color arrays in `lib/colorscales.ts`
- Automatic chart type selection based on query result column shape (`detectResultShape`)
- Chart types: ocean profile (inverted Y-axis), T-S diagram, salinity overlay, time series
- Map types: float positions with clustering, float trajectories with temporal gradient
- Chart export: PNG (1200×800, scale 2) and SVG per chart
- Dashboard route at `/dashboard` using `react-grid-layout`
- All visualization components dynamically imported with `{ ssr: false }`

### 6.7 Geospatial Exploration
- Full-screen map at `/map` route using Leaflet.js
- All active float positions loaded on mount from Redis-cached endpoint
- Nearest floats query on map click (ST_DWithin + ST_Distance)
- Radius query tool with adjustable slider (50km–2000km)
- Ocean basin filter sidebar showing all 15 named regions from `ocean_regions` table
- Basin polygon overlays fetched from dedicated `/api/v1/map/basin-polygons` endpoint
- Place-name search using Feature 4's curated geography lookup (no external geocoding API)
- Float detail panel with mini profile chart and deep link to chat
- Deep link system: map selections generate pre-filled queries at `/chat?prefill=...`
- Geospatial calculations via `@turf/turf` on the frontend
- OpenStreetMap tiles with attribution (legal requirement)

### 6.8 Data Export
- CSV: flat table, one row per measurement, UTF-8
- NetCDF: ARGO-compliant reconstruction using xarray, preserving variable names and QC flags
- JSON: structured envelope with query metadata
- Async export via Celery for results > 50MB, returns presigned MinIO URL
- Export button on every query result panel in the chat interface

### 6.9 Authentication & User Management
- JWT-based authentication with refresh tokens stored in httpOnly cookies
- User registration, login, logout, and password reset
- RBAC: `researcher` role (default) and `admin` role
- Route protection on all `/api/v1/chat/*`, `/api/v1/query/*`, `/api/v1/map/*` endpoints
- `users` table and `password_reset_tokens` table
- Session migration: anonymous browser-UUID sessions linked to user account on first login
- User profile in sidebar footer with logout action
- No third-party auth provider in v1 (built directly with python-jose + passlib/bcrypt)

### 6.10 Anomaly Detection
- Nightly Celery beat task processing all profiles ingested in the last 24 hours
- Four detection strategies:
  - **Spatial baseline**: compare against all floats within 200km in same calendar month across all years; flag if > 2 standard deviations from mean
  - **Float self-comparison**: compare current profile against float's own last 10 profiles; flag sustained shifts > 1.5 standard deviations
  - **Cluster pattern**: detect when 3+ floats within 500km show anomalous readings of the same variable within a 7-day window
  - **Seasonal baseline**: compare against pre-computed climatological monthly averages per region
- `anomalies` table storing: float ID, profile ID, anomaly type, severity (low/medium/high), variable, baseline value, observed value, deviation percent
- `anomaly_baselines` table storing pre-computed monthly regional averages
- Anomaly feed in sidebar with unreviewed count badge
- Anomaly detail panel with "Investigate in Chat" deep link
- Anomaly overlay on geospatial map marking flagged float positions
- Distinct from ingestion-time QC flagging: detects contextually unusual values, not physically impossible ones

### 6.11 Guided Query Assistant
- Query template library (30+ templates in JSON)
- Autocomplete via Fuse.js fuzzy matching against templates and past successful queries
- Clarification detection: when query is underspecified, present targeted chip-based options
- Personalized suggestions based on user's query history
- Integrated within the chat input — not a separate page

### 6.12 Dataset Management (Admin)
- Protected route, admin role required
- Drag-and-drop file upload (single `.nc` files and zip archives)
- Real-time ingestion job status
- Dataset metadata editor (name, description, tags)
- LLM summary regeneration trigger
- Soft delete (marks inactive) and hard delete (removes all data and files)
- Audit log for all admin actions

### 6.13 Public API Layer
- API key authentication via `X-API-Key` header
- Rate limiting via `slowapi` (100 req/min per key default)
- Auto-generated OpenAPI documentation at `/docs`
- Versioned at `/api/v1/`
- Core endpoints: query, dataset search, visualization data, export, float info

### 6.14 System Monitoring
- Structured JSON logging via `structlog` on all API requests
- Sentry integration on both FastAPI backend and Next.js frontend
- Prometheus metrics: request latency (p50/p95/p99), LLM call latency, DB query time, cache hit rate
- Grafana dashboards for all core metrics
- Slack webhook alerts for ingestion failures and p99 latency breaches
- Ingestion monitoring dashboard in admin UI

---

## 7. Technical Stack

### Frontend
| Component | Technology |
|---|---|
| Framework | Next.js 14 (App Router) |
| UI components | Tailwind CSS + shadcn/ui |
| State management | Zustand |
| Charting | Plotly.js + react-plotly.js |
| Color scales | cmocean (custom Plotly arrays) |
| Maps | Leaflet.js + react-leaflet |
| Map clustering | react-leaflet-cluster |
| Map draw tool | leaflet-draw + react-leaflet-draw |
| Dashboard grid | react-grid-layout |
| Geospatial utils | @turf/turf |
| Real-time | SSE via fetch + ReadableStream |
| Markdown | react-markdown + remark-gfm + rehype-highlight |
| Autocomplete | Fuse.js |
| Fonts | Fraunces (display), DM Sans (body), JetBrains Mono (code) |

### Backend
| Component | Technology |
|---|---|
| Framework | FastAPI (Python 3.11+) |
| ORM | SQLAlchemy |
| Migrations | Alembic |
| Task queue | Celery + Redis |
| Auth | python-jose (JWT) + passlib/bcrypt |
| Rate limiting | slowapi |
| Logging | structlog |
| SQL validation | sqlglot |

### AI & Intelligence
| Component | Technology |
|---|---|
| LLM providers | DeepSeek (default), Qwen QwQ, Gemma, OpenAI |
| LLM client | openai Python library (OpenAI-compatible API for all providers) |
| Embeddings | OpenAI text-embedding-3-small (1536 dimensions) |
| Vector store | pgvector (PostgreSQL extension) |
| RAG retrieval | pgvector cosine similarity search |
| Prompt framework | Custom pipeline (no LangChain) |

### Data & Infrastructure
| Component | Technology |
|---|---|
| Database | PostgreSQL 15 + PostGIS 3 |
| Vector indexes | HNSW via pgvector |
| Caching | Redis |
| Object storage | MinIO (dev) / AWS S3 (prod) |
| Data parsing | xarray, netCDF4, pandas, numpy |
| Connection pooling | PgBouncer |
| Containerisation | Docker + Docker Compose (dev) |
| Monitoring | Sentry, Prometheus, Grafana |

---

## 8. Database Schema

### Core Tables
- **`floats`** — one row per ARGO float: `float_id`, `platform_number`, `wmo_id`, `float_type`, `deployment_date`, `deployment_lat`, `deployment_lon`, `country`, `program`
- **`profiles`** — one row per float cycle: `profile_id`, `float_id`, `cycle_number`, `juld_timestamp`, `latitude`, `longitude`, `geom (GEOGRAPHY POINT)`, `data_mode`
- **`measurements`** — one row per depth level: `measurement_id`, `profile_id`, `pressure`, `temperature`, `salinity`, `dissolved_oxygen`, `chlorophyll`, `nitrate`, `ph`, `bbp700`, `downwelling_irradiance`, plus QC flag columns
- **`datasets`** — one row per ingested dataset: `dataset_id`, `name`, `source_url`, `date_range_start`, `date_range_end`, `bbox`, `float_count`, `profile_count`, `variable_list (JSONB)`, `summary_text`, `is_active`
- **`ocean_regions`** — reference table of 15 named ocean basins with polygon geometries
- **`float_positions`** — float location index (lat/lon per cycle)
- **`ingestion_jobs`** — ingestion event log

### Search & Intelligence Tables
- **`dataset_embeddings`** — pgvector embeddings for dataset metadata (HNSW indexed)
- **`float_embeddings`** — pgvector embeddings for float descriptions (HNSW indexed)
- **`query_history`** — successful NL queries with embeddings for RAG retrieval: `query_id`, `nl_query`, `generated_sql`, `embedding (vector 1536)`, `row_count`, `user_id`, `session_id`, `provider`, `model`, `created_at`

### Chat Tables
- **`chat_sessions`** — one row per conversation: `session_id`, `user_identifier`, `name`, `created_at`, `last_active_at`, `is_active`, `message_count`
- **`chat_messages`** — one row per message: `message_id`, `session_id`, `role`, `content`, `nl_query`, `generated_sql`, `result_metadata (JSONB)`, `follow_up_suggestions (JSONB)`, `error (JSONB)`, `created_at`

### Auth Tables
- **`users`** — `user_id`, `email`, `hashed_password`, `name`, `role`, `created_at`, `is_active`
- **`password_reset_tokens`** — `token_id`, `user_id`, `token_hash`, `expires_at`, `used`

### Anomaly Tables
- **`anomalies`** — `anomaly_id`, `float_id`, `profile_id`, `anomaly_type`, `severity`, `variable`, `baseline_value`, `observed_value`, `deviation_percent`, `description`, `detected_at`, `region`, `is_reviewed`, `reviewed_by`
- **`anomaly_baselines`** — pre-computed monthly regional averages per variable for seasonal comparison

### Materialized Views
- **`mv_float_latest_position`** — latest position per float, refreshed after each ingestion
- **`mv_dataset_stats`** — aggregated dataset statistics

---

## 9. Design System

FloatChat uses an ocean-themed visual language with two modes.

### Light Mode — Tropical Coast
Warm sand base (`#F5F0E8`), foam white surfaces, ocean blue primary (`#1B7A9E`), sky blue accents. Subtle fixed SVG wave pattern at viewport bottom at low opacity. Soft sky gradient in the top corner.

### Dark Mode — Moonlit Shore
Deep midnight navy base (`#0B1220`), silver-blue moonlight accents, deep purple depth wash from bottom-left, faint moon glow radial gradient from top-center, dark wave silhouette at bottom.

### Typography
- **Display/Headings:** Fraunces (Google Fonts) — warm, slightly nautical serif
- **Body/UI:** DM Sans (Google Fonts) — clean, friendly, excellent small-size legibility
- **Code/SQL:** JetBrains Mono (Google Fonts)

### Key Principles
- All colors defined as CSS variables in `globals.css` and mapped in `tailwind.config.ts`
- Never hardcode hex values in component files
- Dark mode via Tailwind `class` strategy (not `media`)
- Background illustrations are subtle, fixed-position SVG vectors with `pointer-events: none`
- shadcn/ui components configured to use FloatChat's CSS variable token set

---

## 10. Non-Functional Requirements

| Requirement | Target |
|---|---|
| Simple query response time | < 3 seconds end-to-end |
| LLM generation latency | < 5 seconds |
| Map initial load (all floats) | < 3 seconds |
| Nearest floats query (p95) | < 500ms |
| Chart render (10,000 rows) | < 1 second |
| SSE first byte latency | < 500ms |
| Scalability | Millions of measurement rows supported |
| Row limit default | 10,000 (max 100,000) |
| Statement timeout | 30 seconds |
| Redis cache TTL (active floats) | 5 minutes |
| Redis cache TTL (suggestions) | 1 hour |
| Reliability | structlog + Sentry + retry logic on all LLM calls |
| Security | Read-only DB user for query execution, AST-based SQL validation, JWT auth, rate limiting |
| Browser support | Chrome 120+, Firefox 120+, Safari 17+, Edge 120+ |
| Mobile | Functional at 375px width |

---

## 11. Build Sequence

### Completed
- Feature 1 — Data Ingestion Pipeline ✅
- Feature 2 — Ocean Data Database ✅
- Feature 3 — Metadata Search Engine ✅
- Feature 4 — Natural Language Query Engine ✅
- Feature 5 — Conversational Chat Interface ✅
- Feature 6 — Data Visualization Dashboard ✅
- Feature 7 — Geospatial Exploration 🔄 (in progress)

### Planned
- Auth — User authentication and RBAC
- Feature 8 — Data Export System
- RAG Pipeline — Query history retrieval and dynamic few-shot injection
- Anomaly Detection — Nightly scanning, alert feed, investigation workflow
- Feature 9 — Guided Query Assistant
- Feature 10 — Dataset Management
- Feature 11 — API Layer
- Feature 12 — System Monitoring

---

## 12. Open Questions

- Which cloud provider for production deployment (AWS ECS vs Google Cloud Run)?
- What is the initial dataset size for the first production deployment?
- Should the anomaly detection baseline use ARGO climatology data (WOA18) as the seasonal reference, or compute baselines from the ingested data only?
- Should RAG retrieval be cross-tenant (anonymous shared learning) or strictly per-tenant? Cross-tenant improves cold-start accuracy but raises data isolation concerns.

---

## 13. Version History

| Version | Description |
|---|---|
| v1.0 | Initial PRD — high-level specification |
| v2.0 | Full update reflecting Features 1–7 build decisions, new features (Auth, RAG, Anomaly Detection), corrected tech stack, complete database schema, design system, and B2B SaaS context |