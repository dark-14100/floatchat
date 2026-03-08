# FloatChat

**AI-powered natural language interface for ARGO oceanographic float data.**

FloatChat lets researchers, climate analysts, and students explore ARGO ocean datasets by asking questions in plain English. Type a question — get results, charts, and maps in seconds — no SQL, no scripts, no domain expertise required.

> 4,000+ active floats · Millions of ocean profiles · Global ocean coverage

---

## Table of Contents

- [What It Does](#what-it-does)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Features](#features)
- [API Reference](#api-reference)
- [Database Schema](#database-schema)
- [Environment Variables](#environment-variables)
- [Running Tests](#running-tests)
- [Project Structure](#project-structure)
- [Tech Stack](#tech-stack)

---

## What It Does

| User types | FloatChat does |
|---|---|
| "Show temperature profiles near Sri Lanka in 2023" | Generates SQL, queries the database, renders a depth profile chart |
| "How many BGC floats are in the Arabian Sea?" | Resolves the region, counts matching floats, returns the answer |
| "Export this as NetCDF" | Packages the result as an ARGO-compliant NetCDF file for download |
| Clicks a float on the map | Shows float metadata, mini profile chart, and deep-links to chat |

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+
- Node.js 18+

### 1. Start infrastructure

```bash
docker-compose up -d
```

| Service | Port | Purpose |
|---|---|---|
| PostgreSQL 15 + PostGIS | 5432 | Primary database (migrations only) |
| PgBouncer | 5433 | Connection pooler — all app queries |
| Redis 7 | 6379 | Celery broker, result backend, query cache |
| MinIO | 9000 / 9001 | Object storage (raw files + exports) |

### 2. Install backend dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env — minimum required: DATABASE_URL, REDIS_URL, JWT_SECRET_KEY (32+ chars)
```

### 4. Run migrations

```bash
alembic upgrade head
```

### 5. Seed ocean regions

```bash
python scripts/seed_ocean_regions.py
```

Required for basin-level spatial queries (Arabian Sea, Bay of Bengal, etc.).

### 6. Start the backend

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 7. Start the Celery worker

```bash
celery -A celery_worker.celery worker --loglevel=info --pool=solo
```

### 8. Start the frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Frontend: `http://localhost:3000` · Backend API: `http://localhost:8000` · API docs: `http://localhost:8000/docs`

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER LAYER                               │
│   Chat Interface  │  Visualization  │  Geospatial Map  │  Auth  │
└─────────────────────────────────────────────────────────────────┘
                                │
┌─────────────────────────────────────────────────────────────────┐
│                     INTELLIGENCE LAYER                          │
│   NL Query Engine  │  Metadata Search  │  Follow-up Generator   │
└─────────────────────────────────────────────────────────────────┘
                                │
┌─────────────────────────────────────────────────────────────────┐
│                      API LAYER (FastAPI)                        │
│   /auth  │  /query  │  /chat  │  /map  │  /search  │  /export   │
└─────────────────────────────────────────────────────────────────┘
                                │
┌─────────────────────────────────────────────────────────────────┐
│                        DATA LAYER                               │
│   PostgreSQL + PostGIS  │  pgvector  │  Redis  │  MinIO         │
└─────────────────────────────────────────────────────────────────┘
                                │
┌─────────────────────────────────────────────────────────────────┐
│                    INGESTION PIPELINE                           │
│   NetCDF Parser (xarray)  │  QC Filter  │  Celery + Redis       │
└─────────────────────────────────────────────────────────────────┘
```

**Request flow for a chat query:**

```
User question
    → Geography resolution (place name → bounding box)
    → Conversation context (Redis, last 10 turns)
    → NL-to-SQL pipeline (LLM → SQL → validate → retry up to 3×)
    → Row estimation (EXPLAIN JSON) → confirmation if >50K rows
    → SQL execution (read-only connection)
    → Result interpretation (separate LLM call)
    → SSE stream to frontend: thinking → interpreting → executing → results → suggestions → done
```

---

## Features

### Feature 1 — Data Ingestion Pipeline ✅

Accepts ARGO NetCDF files (`.nc`, `.nc4`) or ZIP archives. Validates structure, parses all oceanographic variables, cleans and normalises data, writes to PostgreSQL with idempotent upserts, and generates LLM dataset summaries — entirely asynchronous via Celery.

**Upload endpoint:** `POST /api/v1/datasets/upload` — returns `job_id` within 2 seconds.

**Variables ingested:** `PRES`, `TEMP`, `PSAL`, `DOXY`, `CHLA`, `NITRATE`, `PH_IN_SITU_TOTAL`, `BBP700`, `DOWNWELLING_IRRADIANCE` plus all `_QC` flags.

**Performance targets:** ≥500 profiles/minute per worker · end-to-end latency <5 minutes for a 100 MB file.

---

### Feature 2 — Ocean Data Database ✅

High-performance spatial database optimised for oceanographic queries: time-range filtering, spatial proximity, depth slicing, and multi-variable profile retrieval.

**Key components:**

| Component | Purpose |
|---|---|
| PgBouncer (port 5433) | Connection pooler — all application queries route here |
| GiST index on `profiles.geom` | Fast `ST_DWithin` / `ST_Within` spatial queries |
| BRIN index on `profiles.timestamp` | Efficient time-range scans |
| `ocean_regions` table | 15 named basin polygons (Natural Earth 1:10m) |
| `mv_float_latest_position` | Latest position per float, refreshed after ingestion |
| `mv_dataset_stats` | Per-dataset aggregates |
| `floatchat_readonly` DB user | Read-only connection for the NL query engine |
| Data Access Layer (`dal.py`) | 10 query functions — only file that writes raw SQL |

---

### Feature 3 — Metadata Search Engine ✅

Semantic search over datasets and floats using OpenAI `text-embedding-3-small` (1536 dimensions) stored in pgvector with HNSW indexes. Fuzzy region name matching via `pg_trgm`.

**Endpoints at `/api/v1/search/`:**

| Endpoint | Description |
|---|---|
| `GET /datasets` | Semantic search with hybrid scoring (cosine + recency + region boost) |
| `GET /floats` | Semantic float discovery |
| `GET /floats/by-region` | Floats in a named region (spatial containment) |
| `GET /datasets/{id}/summary` | Rich dataset summary with bbox GeoJSON |
| `GET /datasets/summaries` | Lightweight cards for all active datasets |
| `POST /reindex/{dataset_id}` | Re-embed a dataset (admin only) |

---

### Feature 4 — Natural Language Query Engine ✅

Converts plain English questions into validated, read-only PostgreSQL queries. Supports four LLM providers via an OpenAI-compatible API.

**Supported providers:**

| Provider | Default Model | Key Setting |
|---|---|---|
| DeepSeek (default) | `deepseek-reasoner` | `DEEPSEEK_API_KEY` |
| Qwen | `qwq-32b` | `QWEN_API_KEY` |
| Gemma | `gemma3` | `GEMMA_API_KEY` |
| OpenAI | `gpt-4o` | `OPENAI_API_KEY` |

**SQL validation pipeline:** Every generated query passes three mandatory checks before execution — syntax (sqlglot AST), read-only enforcement (AST walk for write nodes), and table whitelist. If validation fails, the error is injected back into the prompt and retried up to 3 times. After 3 failures the query is never executed.

**Geography resolution:** 50 ocean region names resolved to bounding boxes via `data/geography_lookup.json` before prompt construction.

---

### Feature 5 — Conversational Chat Interface ✅

SSE-streamed chat with session memory, follow-up suggestions, and inline result display.

**SSE event sequence:** `thinking → interpreting → executing → results → suggestions → done`

**Chat endpoints at `/api/v1/chat/`:**

| Method | Path | Description |
|---|---|---|
| POST | `/sessions` | Create a new session |
| GET | `/sessions` | List user's sessions |
| GET | `/query-history` | Recent successful NL queries for autocomplete/personalization |
| GET | `/sessions/{id}` | Session details |
| PATCH | `/sessions/{id}` | Rename session |
| DELETE | `/sessions/{id}` | Soft delete |
| GET | `/sessions/{id}/messages` | Paginated message history |
| POST | `/sessions/{id}/query` | SSE query stream |
| POST | `/sessions/{id}/query/confirm` | Confirm large query (>50K rows) |
| GET | `/suggestions` | Load-time example queries (Redis cached) |

---

### Feature 6 — Data Visualization Dashboard ✅

Interactive oceanographic charts rendered inline in the chat and in a standalone dashboard view at `/dashboard`.

**Chart types:**

| Component | Description |
|---|---|
| `OceanProfileChart` | Vertical profile with inverted Y-axis (deeper = lower) |
| `TSdiagram` | Temperature-Salinity scatter, colored by pressure |
| `SalinityOverlayChart` | Dual X-axes (temperature + salinity) with T-S toggle |
| `TimeSeriesChart` | Variable over time, one trace per float |
| `FloatPositionMap` | Clustered float positions with cmocean colorscales |
| `FloatTrajectoryMap` | Float path with blue→red temporal gradient |
| `RegionSelector` | Draw polygon/rectangle → emits GeoJSON for query filtering |

`VisualizationPanel` automatically selects the correct chart type using `detectResultShape()` based on the query result columns. All maps use Leaflet.js with OpenStreetMap tiles.

---

### Feature 7 — Geospatial Map Exploration ✅

Full-screen interactive map at `/map` for discovering floats spatially before querying.

**Map endpoints at `/api/v1/map/`:**

| Endpoint | Description |
|---|---|
| `GET /active-floats` | All float latest positions (Redis cached, 5 min TTL) |
| `GET /nearest-floats` | N nearest floats to a clicked point |
| `POST /radius-query` | Profile metadata within a drawn circle (50–2000 km) |
| `GET /floats/{platform_number}` | Float metadata + last 5 profiles |
| `GET /basin-floats` | Floats within a named ocean basin |
| `GET /basin-polygons` | All 15 basin geometries as GeoJSON (Redis cached, 1 hr TTL) |

**Deep link:** `/chat/[session_id]?prefill=...` auto-submits a query once, enabling one-click map-to-chat workflows.

---

### Feature 8 — Data Export System ✅

One-click export of any chat query result. Small exports stream directly; large exports queue as a Celery task and deliver a presigned MinIO URL.

**Export endpoint:** `POST /api/v1/export`

| Format | Library | Description |
|---|---|---|
| CSV | pandas | Flat table, one row per measurement, UTF-8, `#` comment header with query metadata |
| NetCDF | xarray | ARGO-compliant NetCDF4 Classic with correct variable names (`TEMP`, `PSAL`, `PRES`, `DOXY`), units, and fill values |
| JSON | stdlib json | Structured envelope with `metadata` and `profiles` array |

**Routing:** Exports estimated under 50 MB stream synchronously. Exports above 50 MB are queued — poll `GET /api/v1/export/status/{task_id}` every 3 seconds. Hard cap at 500 MB (HTTP 413).

**Status poll response:**
```json
{
  "status": "complete",
  "download_url": "https://minio.../floatchat-exports/...",
  "expires_at": "2026-03-06T11:00:00Z"
}
```

---

### Feature 9 — Guided Query Assistant ✅

Interactive query guidance layer for faster first-query success and better query specificity, implemented additively on top of the existing chat flow.

**What is implemented:**

| Capability | Behavior |
|---|---|
| Suggested query gallery | Category tabs with static template cards (`queryTemplates.json`) shown only on chat empty state |
| Personalized tab | Optional `For You` tab generated from authenticated user's recent query history |
| Recently added badge | Template badge derived from recent dataset summaries (`/api/v1/search/datasets/summaries`) with silent fallback |
| Autocomplete | Fuse.js-powered multi-source typeahead (history + templates + ocean terms) with keyboard navigation |
| Clarification detection | Server-side detection endpoint with fail-open behavior and 3s frontend timeout fallback |
| Clarification widget | Chip-based refinement flow with skip/dismiss and assembled-query submission |
| Prefill safety | `prefill` deep-link flow bypasses gallery and clarification, preserving Feature 15 investigation flow |

**Feature 9 endpoints:**

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/chat/query-history` | Auth-scoped recent successful NL queries (max 200) for personalization/autocomplete |
| POST | `/api/v1/clarification/detect` | Server-side underspecified query detection with fail-open response on errors/timeouts |

**Frontend Feature 9 assets:**
- `frontend/components/chat/SuggestedQueryGallery.tsx`
- `frontend/components/chat/AutocompleteInput.tsx`
- `frontend/components/chat/ClarificationWidget.tsx`
- `frontend/lib/queryTemplates.json`
- `frontend/lib/oceanTerms.json`

---

### Feature 13 — Authentication & User Management ✅

JWT-based authentication with role-based access control.

**Token model:** Short-lived access token (15 min, in-memory on frontend) + httpOnly refresh cookie (`floatchat_refresh`, 7 days).

**Auth endpoints at `/api/v1/auth/`:**

| Method | Path | Description |
|---|---|---|
| POST | `/signup` | Create account, returns access token |
| POST | `/login` | Authenticate, returns access token + sets cookie |
| POST | `/logout` | Clears refresh cookie |
| GET | `/me` | Current user profile |
| POST | `/refresh` | Silent token refresh using cookie |
| POST | `/forgot-password` | Send reset link (always HTTP 200) |
| POST | `/reset-password` | Set new password with token |

**Route protection:**

| Access level | Endpoints |
|---|---|
| Public | `/health`, `GET /api/v1/search/*`, all `/api/v1/auth/*` |
| Authenticated user | `/api/v1/query/*`, `/api/v1/chat/*`, `/api/v1/map/*`, `/api/v1/export/*` |
| Admin only | `/api/v1/datasets/*`, `POST /api/v1/search/reindex/{id}` |

---

### Feature 14 — RAG Pipeline ✅

Retrieval-Augmented Generation improves NL-to-SQL quality by reusing each user's own successful query history as dynamic few-shot context.

**What is implemented:**

| Capability | Behavior |
|---|---|
| Query history storage | Successful chat queries (`row_count > 0`) are stored in `query_history` with embeddings |
| Retrieval in pipeline | `nl_to_sql()` retrieves similar user queries and prepends RAG context additively |
| Fallback safety | Any retrieval/store failure falls back to static behavior without breaking query execution |
| Tenant isolation | Retrieval is DB-filtered by `user_id`; no cross-user query history access |
| Benchmark behavior | `POST /api/v1/query/benchmark` remains static-only (no RAG retrieval) |

**Configuration flags:** `ENABLE_RAG_RETRIEVAL`, `RAG_RETRIEVAL_LIMIT`, `RAG_SIMILARITY_THRESHOLD`, `RAG_DEDUP_WINDOW_HOURS`

---

### Feature 15 — Anomaly Detection ✅

Nightly statistical anomaly detection surfaces contextually unusual readings that are physically valid but regionally or temporally unexpected.

**What is implemented:**

| Capability | Behavior |
|---|---|
| Nightly scan orchestration | Celery beat task `app.anomaly.tasks.run_anomaly_scan` scheduled at 02:00 UTC |
| Detector suite | Spatial baseline, float self-comparison, seasonal baseline, and cluster pattern detectors |
| Detection safety | Per-detector fault isolation and final task-level exception guard |
| Dedup logic | In-memory + persisted dedup on `(profile_id, anomaly_type, variable)` |
| Frontend workflows | Sidebar anomaly bell + badge, `/anomalies` feed/detail page, map anomaly overlay toggle |
| Review flow | `PATCH /api/v1/anomalies/{id}/review` updates review fields |
| Baseline management | CLI script and admin endpoint to compute/upsert monthly regional baselines |

**Configuration flags:**
`ANOMALY_SCAN_ENABLED`, `ANOMALY_SCAN_WINDOW_HOURS`, `ANOMALY_SPATIAL_RADIUS_KM`, `ANOMALY_SPATIAL_MIN_PROFILES`, `ANOMALY_SPATIAL_THRESHOLD_STD`, `ANOMALY_SELF_COMPARISON_HISTORY`, `ANOMALY_SELF_COMPARISON_MIN_PROFILES`, `ANOMALY_SELF_COMPARISON_THRESHOLD_STD`, `ANOMALY_CLUSTER_RADIUS_KM`, `ANOMALY_CLUSTER_MIN_FLOATS`, `ANOMALY_CLUSTER_WINDOW_DAYS`, `ANOMALY_SEASONAL_MIN_SAMPLES`, `ANOMALY_SEASONAL_THRESHOLD_STD`

---

## API Reference

Full interactive documentation at `http://localhost:8000/docs` (requires `DEBUG=True`).

### Authentication

All protected endpoints require:
```
Authorization: Bearer <access_token>
```

Access tokens expire after 15 minutes. The frontend silently refreshes them using the `floatchat_refresh` httpOnly cookie.

### Key Request/Response Examples

**Run a natural language query:**
```http
POST /api/v1/query
Content-Type: application/json
Authorization: Bearer <token>

{
  "query": "How many BGC floats are in the Arabian Sea?",
  "session_id": "optional-uuid",
  "provider": "deepseek"
}
```

```json
{
  "session_id": "a1b2c3...",
  "sql": "SELECT COUNT(*) FROM floats WHERE ...",
  "columns": ["count"],
  "rows": [{"count": 42}],
  "row_count": 1,
  "interpretation": "There are 42 BGC floats in the Arabian Sea.",
  "provider": "deepseek",
  "model": "deepseek-reasoner"
}
```

**Upload a dataset:**
```http
POST /api/v1/datasets/upload
Authorization: Bearer <admin_token>
Content-Type: multipart/form-data

file=<floats.nc>
dataset_name=ARGO Indian Ocean 2025
```

```json
{
  "job_id": "550e8400-...",
  "dataset_id": 1,
  "status": "pending",
  "message": "File received. Ingestion started."
}
```

**Export a query result:**
```http
POST /api/v1/export
Authorization: Bearer <token>
Content-Type: application/json

{
  "message_id": "uuid-of-chat-message",
  "format": "csv",
  "rows": [{"profile_id": 1, "temperature": 28.5, ...}]
}
```

---

## Database Schema

Created by Alembic migrations `001` through `007`. Requires PostgreSQL 15 with PostGIS, pgvector, pg_trgm, and pgcrypto extensions.

### Core Tables

**`floats`** — One row per ARGO float.
```
float_id (SERIAL PK) · platform_number (UNIQUE) · wmo_id · float_type
deployment_date · deployment_lat · deployment_lon · country · program
```

**`profiles`** — One row per float cycle. Unique on `(platform_number, cycle_number)`.
```
profile_id (BIGSERIAL PK) · float_id (FK) · platform_number · cycle_number
timestamp · latitude · longitude · geom (GEOGRAPHY POINT) · data_mode · dataset_id (FK)
```
Indexes: GiST on `geom` · BRIN on `timestamp` · B-tree on `float_id`

**`measurements`** — One row per depth level within a profile.
```
measurement_id (BIGSERIAL PK) · profile_id (FK CASCADE) · pressure · temperature · salinity
dissolved_oxygen · chlorophyll · nitrate · ph · bbp700 · downwelling_irradiance
pres_qc · temp_qc · psal_qc · doxy_qc · chla_qc · nitrate_qc · ph_qc · is_outlier
```

**`datasets`** — One row per ingested file.
```
dataset_id (SERIAL PK) · name · source_filename · raw_file_path · date_range_start · date_range_end
bbox (GEOGRAPHY POLYGON) · float_count · profile_count · variable_list (JSONB)
summary_text · is_active · dataset_version
```

**`float_positions`** — Lightweight spatial index. One row per `(platform_number, cycle_number)`.
```
position_id (SERIAL PK) · platform_number · cycle_number · timestamp
latitude · longitude · geom (GEOGRAPHY POINT, GiST indexed)
```

**`ingestion_jobs`** — Tracks pipeline execution.
```
job_id (UUID PK) · dataset_id (FK) · original_filename · raw_file_path
status · progress_pct · profiles_total · profiles_ingested · error_log · errors (JSONB)
```

**`ocean_regions`** — 15 named basin polygons.
```
region_id (SERIAL PK) · name (UNIQUE) · geom (GEOGRAPHY MULTIPOLYGON, GiST indexed)
```

### Search Tables

**`dataset_embeddings`** — One row per dataset, HNSW indexed.
```
embedding_id (SERIAL PK) · dataset_id (FK UNIQUE) · embedding_text · embedding (vector 1536) · status
```

**`float_embeddings`** — One row per float, HNSW indexed.
```
embedding_id (SERIAL PK) · float_id (FK UNIQUE) · embedding_text · embedding (vector 1536) · status
```

### Chat Tables

**`chat_sessions`**
```
session_id (UUID PK) · user_identifier · name · created_at · last_active_at · is_active · message_count
```

**`chat_messages`**
```
message_id (UUID PK) · session_id (FK) · role · content · nl_query · generated_sql
result_metadata (JSONB) · follow_up_suggestions (JSONB) · error (JSONB) · status · created_at
```

**`query_history`**
```
query_id (UUID PK) · nl_query · generated_sql · embedding (vector 1536) · row_count
user_id (FK CASCADE) · session_id (FK SET NULL) · provider · model · created_at
```
Indexes: HNSW on `embedding` (`vector_cosine_ops`) · B-tree on `user_id` · B-tree on `created_at`

### Anomaly Tables

**`anomalies`**
```
anomaly_id (UUID PK) · float_id (FK) · profile_id (FK) · anomaly_type · severity · variable
baseline_value · observed_value · deviation_percent · description · detected_at · region
is_reviewed · reviewed_by (FK SET NULL) · reviewed_at
```
Indexes: B-tree on `detected_at` · `float_id` · `severity` · composite (`is_reviewed`, `detected_at`)

**`anomaly_baselines`**
```
baseline_id (SERIAL PK) · region · variable · month · mean_value · std_dev · sample_count · computed_at
```
Constraints: unique (`region`, `variable`, `month`) · check (`month` between 1 and 12)

### Auth Tables

**`users`**
```
user_id (UUID PK) · email (UNIQUE) · hashed_password · name · role · created_at · is_active
```

**`password_reset_tokens`**
```
token_id (UUID PK) · user_id (FK CASCADE) · token_hash · expires_at · used
```

### Materialized Views

| View | Description | Refreshed |
|---|---|---|
| `mv_float_latest_position` | Latest position per float | After each ingestion run |
| `mv_dataset_stats` | Per-dataset aggregates | After each ingestion run |

---

## Environment Variables

### Required

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL via PgBouncer — `postgresql+psycopg2://...@localhost:5433/floatchat` |
| `READONLY_DATABASE_URL` | Read-only user via PgBouncer for query execution |
| `REDIS_URL` | Redis connection — `redis://localhost:6379/0` |
| `JWT_SECRET_KEY` | JWT signing key, minimum 32 characters |

### Database

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL_DIRECT` | — | Direct PostgreSQL (port 5432) — Alembic migrations only |
| `READONLY_DB_PASSWORD` | `floatchat_readonly` | Read-only user password |
| `DB_POOL_SIZE` | `10` | SQLAlchemy pool size |
| `DB_MAX_OVERFLOW` | `20` | Max overflow connections |

### Celery & Redis

| Variable | Default | Description |
|---|---|---|
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/1` | Celery result store |
| `REDIS_CACHE_TTL_SECONDS` | `300` | Query result cache TTL |
| `REDIS_CACHE_MAX_ROWS` | `10000` | Max rows to cache |

### Object Storage (MinIO / S3)

| Variable | Default | Description |
|---|---|---|
| `S3_ENDPOINT_URL` | — | Set for local MinIO: `http://localhost:9000` |
| `S3_ACCESS_KEY` | `minioadmin` | Access key |
| `S3_SECRET_KEY` | `minioadmin` | Secret key |
| `S3_BUCKET_NAME` | `floatchat-raw-uploads` | Upload staging bucket |
| `S3_REGION` | `us-east-1` | Region |

### LLM Providers

| Variable | Default | Description |
|---|---|---|
| `QUERY_LLM_PROVIDER` | `deepseek` | Default NL query provider |
| `QUERY_LLM_TEMPERATURE` | `0.0` | LLM temperature |
| `QUERY_MAX_RETRIES` | `3` | Max SQL validation retries |
| `QUERY_MAX_ROWS` | `1000` | Max rows returned per query |
| `QUERY_CONFIRMATION_THRESHOLD` | `50000` | Row estimate that triggers confirmation |
| `DEEPSEEK_API_KEY` | — | DeepSeek API key |
| `QWEN_API_KEY` | — | Qwen API key |
| `GEMMA_API_KEY` | — | Gemma API key |
| `OPENAI_API_KEY` | — | OpenAI API key (also used for embeddings and LLM summaries) |

### Authentication

| Variable | Default | Description |
|---|---|---|
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token lifetime |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime |
| `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES` | `60` | Reset token lifetime |
| `FRONTEND_URL` | `http://localhost:3000` | Used to build password reset links |

### Export

| Variable | Default | Description |
|---|---|---|
| `EXPORT_SYNC_SIZE_LIMIT_MB` | `50` | Exports above this size use async Celery path |
| `EXPORT_PRESIGNED_URL_EXPIRY_SECONDS` | `3600` | Presigned URL expiry (1 hour) |
| `EXPORT_TASK_STATUS_TTL_SECONDS` | `7200` | Redis task status key TTL (2 hours) |
| `EXPORT_BUCKET_NAME` | `floatchat-exports` | MinIO bucket for async exports |
| `EXPORT_MAX_SIZE_MB` | `500` | Hard cap — returns HTTP 413 above this |

### Search & Embeddings

| Variable | Default | Description |
|---|---|---|
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model |
| `EMBEDDING_DIMENSIONS` | `1536` | Vector dimensions |
| `SEARCH_SIMILARITY_THRESHOLD` | `0.3` | Min cosine similarity to include in results |
| `FUZZY_MATCH_THRESHOLD` | `0.4` | pg_trgm threshold for region name matching |

### RAG Retrieval (Feature 14)

| Variable | Default | Description |
|---|---|---|
| `ENABLE_RAG_RETRIEVAL` | `True` | Master switch for retrieval-augmented prompt context |
| `RAG_RETRIEVAL_LIMIT` | `5` | Max similar historical queries injected per request |
| `RAG_SIMILARITY_THRESHOLD` | `0.4` | Max cosine distance allowed for retrieved examples |
| `RAG_DEDUP_WINDOW_HOURS` | `24` | Soft dedup window for identical successful NL queries per user |

### Anomaly Detection (Feature 15)

| Variable | Default | Description |
|---|---|---|
| `ANOMALY_SCAN_ENABLED` | `True` | Master switch for nightly anomaly scan |
| `ANOMALY_SCAN_WINDOW_HOURS` | `24` | Recency window for scanned profiles |
| `ANOMALY_SPATIAL_RADIUS_KM` | `200` | Neighbor radius for spatial baseline |
| `ANOMALY_SPATIAL_MIN_PROFILES` | `10` | Min comparison profiles for spatial detector |
| `ANOMALY_SPATIAL_THRESHOLD_STD` | `2.0` | Spatial baseline z-score threshold |
| `ANOMALY_SELF_COMPARISON_HISTORY` | `10` | Historical profiles per float for self-comparison |
| `ANOMALY_SELF_COMPARISON_MIN_PROFILES` | `5` | Min historical profiles for self detector |
| `ANOMALY_SELF_COMPARISON_THRESHOLD_STD` | `1.5` | Self-comparison z-score threshold |
| `ANOMALY_CLUSTER_RADIUS_KM` | `500` | Spatial radius for cluster detector |
| `ANOMALY_CLUSTER_MIN_FLOATS` | `3` | Minimum anomalous floats for cluster detection |
| `ANOMALY_CLUSTER_WINDOW_DAYS` | `7` | Temporal window for cluster detection |
| `ANOMALY_SEASONAL_MIN_SAMPLES` | `30` | Minimum baseline sample count |
| `ANOMALY_SEASONAL_THRESHOLD_STD` | `2.0` | Seasonal baseline z-score threshold |

### Observability

| Variable | Default | Description |
|---|---|---|
| `SENTRY_DSN` | — | Sentry error tracking DSN |
| `LOG_LEVEL` | `INFO` | structlog log level |
| `DEBUG` | `False` | Enables `/docs` Swagger UI |

---

## Running Tests

### Backend

```bash
cd backend

# All tests
pytest tests/ -v

# By feature
pytest tests/test_parser.py tests/test_cleaner.py tests/test_writer.py tests/test_api.py -v      # Feature 1
pytest tests/test_schema.py tests/test_dal.py tests/test_cache.py -v                              # Feature 2 (Docker required)
pytest tests/test_embeddings.py tests/test_search.py tests/test_discovery.py -v                   # Feature 3
pytest tests/test_validator.py tests/test_executor.py tests/test_geography.py tests/test_pipeline_f4.py -v  # Feature 4
pytest tests/test_chat_api.py tests/test_suggestions.py -v                                        # Feature 5
pytest tests/test_map_api.py -v                                                                    # Feature 7
pytest tests/test_export_api.py -v                                                                 # Feature 8
pytest tests/test_auth_api.py -v                                                                   # Feature 13
pytest tests/test_rag.py -v                                                                        # Feature 14
pytest tests/test_anomaly_detectors.py tests/test_anomaly_tasks.py tests/test_anomaly_api.py -v   # Feature 15
pytest tests/test_clarification.py tests/test_query_history.py -v                                  # Feature 9
```

**Docker note:** Feature 2 tests (`test_schema.py`, `test_dal.py`) require Docker running. When Docker is unavailable they skip gracefully — they do not fail.

**Current backend test status (2026-03-08):** targeted Feature 9 suite `9 passed`; previous full-suite run `427 passed, 58 skipped`.

### Frontend

```bash
cd frontend

npx vitest run          # All tests
npx tsc --noEmit        # Type checking
npm run build           # Production build verification
```

---

## Project Structure

```
floatchat/
├── backend/
│   ├── alembic/
│   │   └── versions/
│   │       ├── 001_initial_schema.py       # floats, profiles, measurements, datasets
│   │       ├── 002_ocean_database.py       # ocean_regions, materialized views, indexes
│   │       ├── 003_metadata_search.py      # pgvector, embedding tables, HNSW indexes
│   │       ├── 004_chat_interface.py       # chat_sessions, chat_messages
│   │       ├── 005_auth.py                 # users, password_reset_tokens
│   │       ├── 006_rag_pipeline.py         # query_history, HNSW index, readonly grant
│   │       └── 007_anomaly_detection.py    # anomalies, anomaly_baselines, indexes
│   ├── app/
│   │   ├── main.py                         # FastAPI app entry point
│   │   ├── config.py                       # All environment settings (pydantic-settings)
│   │   ├── celery_app.py                   # Celery configuration and task registry
│   │   ├── api/v1/
│   │   │   ├── ingestion.py                # Dataset upload and job management
│   │   │   ├── search.py                   # Semantic search endpoints
│   │   │   ├── query.py                    # NL query and benchmark endpoints
│   │   │   ├── chat.py                     # Chat session and SSE stream endpoints
│   │   │   ├── clarification.py            # Clarification detection endpoint (Feature 9)
│   │   │   ├── map.py                      # Geospatial exploration endpoints
│   │   │   ├── export.py                   # Export trigger and status endpoints
│   │   │   ├── auth.py                     # Authentication endpoints
│   │   │   └── anomalies.py                # Anomaly feed/detail/review/baseline endpoints
│   │   ├── auth/
│   │   │   ├── jwt.py                      # Token generation and validation
│   │   │   ├── passwords.py                # bcrypt hashing
│   │   │   ├── dependencies.py             # get_current_user, get_current_admin_user
│   │   │   └── email.py                    # Password reset email (stdout in dev)
│   │   ├── anomaly/
│   │   │   ├── detectors.py                # Four statistical anomaly detectors
│   │   │   ├── baselines.py                # Seasonal baseline computation/upsert
│   │   │   └── tasks.py                    # Nightly anomaly scan task
│   │   ├── db/
│   │   │   ├── models.py                   # SQLAlchemy ORM models
│   │   │   ├── session.py                  # DB engines, get_db(), get_readonly_db()
│   │   │   └── dal.py                      # Data Access Layer — only file with raw SQL
│   │   ├── ingestion/
│   │   │   ├── parser.py                   # NetCDF → structured dicts
│   │   │   ├── cleaner.py                  # Outlier flagging and normalisation
│   │   │   ├── writer.py                   # Idempotent DB upserts
│   │   │   ├── metadata.py                 # Dataset stats and LLM summary
│   │   │   └── tasks.py                    # Celery ingestion tasks
│   │   ├── query/
│   │   │   ├── schema_prompt.py            # SCHEMA_PROMPT constant + ALLOWED_TABLES
│   │   │   ├── geography.py                # Place name → bounding box resolution
│   │   │   ├── context.py                  # Redis conversation history
│   │   │   ├── validator.py                # SQL validation (syntax, read-only, whitelist)
│   │   │   ├── executor.py                 # Safe SQL execution + row estimation
│   │   │   ├── pipeline.py                 # LLM orchestration + RAG retrieval integration
│   │   │   └── rag.py                      # Query-history store/retrieve/context helpers
│   │   ├── search/
│   │   │   ├── embeddings.py               # OpenAI embedding API — only caller
│   │   │   ├── indexer.py                  # DB record → embedding → pgvector upsert
│   │   │   ├── search.py                   # Cosine similarity search with hybrid scoring
│   │   │   ├── discovery.py                # Fuzzy region matching, float discovery
│   │   │   └── tasks.py                    # Celery indexing task
│   │   ├── export/
│   │   │   ├── csv_export.py               # CSV generation (pandas)
│   │   │   ├── netcdf_export.py            # NetCDF generation (xarray, ARGO-compliant)
│   │   │   ├── json_export.py              # JSON generation (stdlib)
│   │   │   ├── size_estimator.py           # Sync vs async routing decision
│   │   │   └── tasks.py                    # Celery async export task
│   │   ├── storage/
│   │   │   └── s3.py                       # MinIO/S3 upload, download, presign
│   │   └── cache/
│   │       └── redis_cache.py              # Query result cache
│   ├── data/
│   │   └── geography_lookup.json           # 50 ocean region bounding boxes
│   ├── scripts/
│   │   ├── seed_ocean_regions.py
│   │   ├── create_readonly_user.sql
│   │   └── compute_baselines.py            # Feature 15 baseline CLI
│   ├── tests/
│   ├── celery_worker.py
│   ├── requirements.txt
│   └── alembic.ini
└── frontend/
    ├── app/                                # Next.js App Router pages
    │   ├── chat/[session_id]/              # Main chat interface
    │   ├── dashboard/                      # Visualization dashboard
    │   ├── map/                            # Geospatial exploration
    │   ├── anomalies/                      # Anomaly feed and detail workspace
    │   ├── login/ signup/                  # Auth pages
    │   └── forgot-password/ reset-password/
    ├── components/
    │   ├── chat/                           # ChatMessage, AutocompleteInput, ClarificationWidget, SuggestedQueryGallery
    │   ├── visualization/                  # Chart and map components
    │   ├── map/                            # Geospatial map components
    │   ├── anomaly/                        # AnomalyFeedList, AnomalyDetailPanel, AnomalyComparisonChart
    │   ├── auth/                           # AuthCard, PasswordInput, PasswordStrength
    │   └── layout/                         # SessionSidebar, LayoutShell
    ├── lib/
    │   ├── api.ts                          # Auth-aware API client
    │   ├── queryTemplates.json             # Feature 9 template library
    │   ├── oceanTerms.json                 # Feature 9 autocomplete term dictionary
    │   ├── mapQueries.ts                   # Map endpoint client
    │   ├── exportQueries.ts                # Export endpoint client
    │   ├── anomalyQueries.ts               # Anomaly endpoint client
    │   ├── colorscales.ts                  # cmocean color arrays for Plotly
    │   └── detectResultShape.ts            # Chart type auto-selection
    ├── store/
    │   ├── chatStore.ts                    # Chat and result row state
    │   └── authStore.ts                    # Auth state (in-memory tokens only)
    ├── types/
    └── tests/
```

---

## Tech Stack

### Backend

| Purpose | Library |
|---|---|
| Web framework | FastAPI |
| ORM | SQLAlchemy 2.x |
| Migrations | Alembic |
| Connection pooler | PgBouncer |
| PostGIS ORM | GeoAlchemy2 |
| Vector store | pgvector |
| Task queue | Celery + Redis |
| NetCDF parsing | xarray + netCDF4 |
| Object storage | boto3 (MinIO / S3) |
| SQL validation | sqlglot |
| Auth | python-jose + passlib/bcrypt |
| Config | pydantic-settings |
| Logging | structlog |
| Error tracking | Sentry |
| Testing | pytest + httpx |

### Frontend

| Purpose | Library |
|---|---|
| Framework | Next.js 14 (App Router) |
| State | Zustand |
| Charts | Plotly.js + react-plotly.js |
| Maps | Leaflet.js + react-leaflet |
| Map clustering | react-leaflet-cluster |
| Map drawing | leaflet-draw |
| Geospatial | @turf/turf |
| Dashboard grid | react-grid-layout |
| UI components | Tailwind CSS + shadcn/ui |
| Markdown | react-markdown + remark-gfm |
| Autocomplete | Fuse.js |
| Testing | Vitest + React Testing Library |

### Infrastructure

| Purpose | Technology |
|---|---|
| Database | PostgreSQL 15 + PostGIS 3 + pgvector + pg_trgm |
| Cache / Broker | Redis 7 |
| Object storage | MinIO (dev) / AWS S3 (prod) |
| Containerisation | Docker + Docker Compose |

---

## Changelog

| Version | Features |
|---|---|
| v1.0 | Features 1–5: Ingestion, database, search, NL query, chat |
| v1.1 | Feature 6: Visualization dashboard |
| v1.2 | Feature 7: Geospatial map exploration |
| v1.3 | Feature 8: Data export (CSV, NetCDF, JSON) |
| v1.4 | Feature 13: Authentication and user management |
| v1.5 | Feature 14: RAG retrieval-augmented NL-to-SQL |
| v1.6 | Feature 15: Anomaly detection and review workflows |
| v1.7 | Feature 9: Guided query assistant (gallery, autocomplete, clarification) |