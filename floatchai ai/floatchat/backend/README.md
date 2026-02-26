# FloatChat Backend

## What is FloatChat?

FloatChat is an AI-powered conversational interface that enables users to explore ARGO oceanographic datasets using natural language. The system converts complex NetCDF datasets into structured, queryable data and provides search, analytics, and visualization through a chat interface.

**Target users:** Ocean researchers needing fast analysis and data export, climate analysts needing insights without coding, and students needing intuitive learning tools.

**Scale:** 4,000+ active ARGO floats, millions of ocean profiles, global ocean coverage.

---

## Feature 1: Data Ingestion Pipeline

> _"The Data Ingestion Pipeline is the foundational prerequisite for every other FloatChat feature. Without it, there is no data to query."_
> — Feature 1 PRD §1.1

The ingestion pipeline accepts ARGO NetCDF files (`.nc`, `.nc4`) or ZIP archives via a REST API, validates them, stages to object storage, parses all oceanographic variables, cleans/normalizes the data, writes to PostgreSQL + PostGIS using idempotent upserts, and generates dataset metadata with an optional LLM summary — all asynchronously via Celery.

### High-Level Architecture

```
    ARGO NetCDF files
          │
          ▼
    REST API (FastAPI)  ──→  returns job_id within 2s
          │
          ▼
    Celery Worker (Redis broker)
          │
          ├─ 1. Stage raw file to S3/MinIO
          ├─ 2. Validate NetCDF structure
          ├─ 3. Parse profiles & measurements
          ├─ 4. Clean & flag outliers
          ├─ 5. Upsert to PostgreSQL + PostGIS
          ├─ 6. Compute dataset metadata
          ├─ 7. Generate LLM summary (GPT-4o)
          └─ 8. Mark job succeeded
          │
          ▼
    PostgreSQL + PostGIS (queryable data)
```

### Success Criteria

From the PRD:

| Criterion | Target |
|---|---|
| Parse success rate on valid ARGO files | ≥ 99.5% |
| Ingestion throughput | ≥ 500 profiles/minute per worker |
| Duplicate profile handling | Zero duplicate `(platform_number, cycle_number)` pairs |
| QC flag accuracy | 100% match against ARGO QC standards |
| Julian date conversion accuracy | ±0 seconds tolerance |
| Failed file detection | 100% of malformed files flagged and logged |
| End-to-end latency (upload → queryable) | < 5 minutes for a 100 MB file |

---

## Feature 2: Ocean Data Database

> _"Feature 2 transforms the raw ingested data into a high-performance, spatially-indexed ocean database optimised for the AI query layer."_
> — Feature 2 PRD §1.1

Building on the ingestion pipeline, Feature 2 adds **connection pooling**, **spatial indexing**, **materialized views**, a **Redis query-result cache**, and a **Data Access Layer (DAL)** that downstream features use exclusively to read data.

### What Was Built

| Component | Description |
|-----------|-------------|
| **PgBouncer** | Connection pooler in front of PostgreSQL (port 5433). All application queries route through PgBouncer; only Alembic migrations connect directly to port 5432. |
| **Migration 002** | ALTERs `profile_id` and `measurement_id` columns to `BIGINT`; creates `ocean_regions` and `dataset_versions` tables; adds GiST, BRIN, B-tree, and partial indexes; creates two materialized views; provisions a `floatchat_readonly` database user. |
| **Ocean Regions** | `ocean_regions` table with `GEOGRAPHY(MULTIPOLYGON, 4326)` geometries for basin-level spatial queries (Atlantic, Pacific, Indian, etc.). Seeded from Natural Earth 1:10m polygons. |
| **Dataset Versions** | `dataset_versions` table for tracking version history of ingested datasets. |
| **Materialized Views** | `mv_float_latest_position` (latest position per float) and `mv_dataset_stats` (per-dataset aggregates). Refreshed after each ingestion run. |
| **Redis Cache** | Query-result caching with configurable TTL (default 5 min) and max-rows guard. Cache keys are MD5 hashes of SQL + params. |
| **Data Access Layer** | 10 query functions + 1 MV refresh function in `app/db/dal.py`. All return plain dicts. No other module writes raw SQL. |
| **Readonly Engine** | Separate SQLAlchemy engine connecting as `floatchat_readonly` via PgBouncer for read-only query workloads. |

### Architecture

```
    Application
        │
        ▼
    PgBouncer (port 5433)  ──→  PostgreSQL 15 + PostGIS (port 5432)
        │                              │
        │                         ocean_regions
        │                         dataset_versions
        │                         mv_float_latest_position
        │                         mv_dataset_stats
        │                         GiST / BRIN / B-tree indexes
        ▼
    Redis Cache ← DAL functions ← query results (plain dicts)
```

### DAL Function Reference

All functions live in `app/db/dal.py`. Each accepts a SQLAlchemy `Session` as `db` and returns plain Python dicts.

| Function | Description |
|----------|-------------|
| `get_profiles_by_radius(lat, lon, radius_m, *, db, start_date?, end_date?)` | Profiles within a radius (metres) of a point, optional date filter |
| `get_profiles_by_basin(basin_name, *, db)` | Profiles inside a named ocean region polygon |
| `get_measurements_by_profile(profile_id, *, db, min_pressure?, max_pressure?)` | Measurements for a profile, optional pressure range filter |
| `get_float_latest_positions(*, db)` | Latest position per float from the materialized view |
| `get_active_datasets(*, db)` | All datasets where `is_active = True` |
| `get_dataset_by_id(dataset_id, *, db)` | Single dataset by ID (raises `ValueError` if not found) |
| `search_floats_by_type(float_type, *, db)` | Floats filtered by type (`core`, `BGC`, `deep`) |
| `get_profiles_with_variable(variable_name, *, db, limit?)` | Profiles that have non-NULL values for a given BGC variable |
| `invalidate_query_cache(redis_client)` | Deletes all `query_cache:*` keys from Redis |
| `refresh_materialized_views(*, db)` | Refreshes both materialized views (called after ingestion) |

---

## Feature 3: Metadata Search Engine

> _"The Metadata Search Engine enables semantic similarity search over datasets and floats, fuzzy region discovery, and dataset summaries — all without requiring SQL."_
> — Feature 3 PRD §1.1

Building on the ingestion pipeline and ocean database, Feature 3 adds **vector embeddings** (OpenAI `text-embedding-3-small`), **pgvector HNSW indexes**, **semantic search** with hybrid scoring, **fuzzy region matching** via `pg_trgm`, and **float discovery** functions — exposed through 6 REST API endpoints.

### What Was Built

| Component | Description |
|-----------|-------------|
| **pgvector Extension** | Custom `Dockerfile.postgres` extending `postgis/postgis:15-3.4` with pgvector. HNSW indexes (m=16, ef_construction=64) on both embedding tables. |
| **Migration 003** | Creates `dataset_embeddings` and `float_embeddings` tables with `vector(1536)` columns, HNSW indexes using `vector_cosine_ops`. |
| **Embeddings Module** | Centralized OpenAI API caller with batch support (`EMBEDDING_BATCH_SIZE=100`). Text builders for datasets and floats. The ONLY module that calls the embedding API (Hard Rule #18). |
| **Indexer Module** | Builds embedding texts from DB records, pre-resolves region names via spatial queries, persists embeddings with `INSERT ... ON CONFLICT DO UPDATE`. Handles failures by setting `status='embedding_failed'`. |
| **Search Module** | Semantic similarity search using pgvector `<=>` cosine distance. Hybrid scoring with recency boost (+0.05) and region match boost (+0.10). 3× candidate retrieval with threshold filtering. |
| **Discovery Module** | Fuzzy region name resolution via `pg_trgm` `similarity()`. Float discovery by region (spatial) and by variable. Rich dataset summaries and lightweight summary cards. |
| **Celery Task** | `index_dataset_task` with auto-retry for transient OpenAI errors. Refreshes both materialized views after indexing. Fire-and-forget trigger from ingestion pipeline. |
| **API Router** | 6 endpoints at `/api/v1/search/` — semantic search, float discovery, dataset summaries, and admin reindex. |

### Architecture

```
    Ingestion Pipeline (Feature 1)
          │
          │  ── job succeeded ──▶  index_dataset_task.delay()
          │                              │
          ▼                              ▼
    PostgreSQL + PostGIS          Celery Worker (search queue)
          │                              │
          │                         ┌────┴────┐
          │                         │ Indexer  │── build texts ──▶ Embeddings Module
          │                         │         │                        │
          │                         │         │◀── vectors ────── OpenAI API
          │                         │         │                   (text-embedding-3-small)
          │                         └────┬────┘
          │                              │
          │                    dataset_embeddings
          │                    float_embeddings
          │                    (pgvector HNSW indexes)
          │                              │
          ▼                              ▼
    Search API ◀─── cosine distance (<=>)  ──── query embedding
       │
       ├─  GET /datasets          (semantic search)
       ├─  GET /floats            (semantic search)
       ├─  GET /floats/by-region  (spatial discovery)
       ├─  GET /datasets/{id}/summary
       ├─  GET /datasets/summaries
       └─  POST /reindex/{id}     (admin only)
```

### Search API Endpoints

All search endpoints are mounted at `/api/v1/search/`. GET endpoints are public; POST endpoints require admin JWT.

#### `GET /api/v1/search/datasets`

Semantic search over dataset embeddings.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `q` | string | required | Natural language search query |
| `limit` | int | 10 | Max results (capped at 50) |
| `variable` | string | — | Filter by variable name |
| `float_type` | string | — | Filter by float type |
| `date_from` | ISO date | — | Filter datasets overlapping this date |
| `date_to` | ISO date | — | Filter datasets overlapping this date |
| `region_name` | string | — | Boost results matching this region |

**Response 200:**
```json
[
  {
    "dataset_id": 1,
    "name": "Argo Indian Ocean 2025",
    "summary_text": "Temperature and salinity profiles...",
    "score": 0.8723,
    "date_range_start": "2025-01-01T00:00:00",
    "date_range_end": "2025-06-30T00:00:00",
    "float_count": 42,
    "variable_list": {"temperature": true, "salinity": true}
  }
]
```

#### `GET /api/v1/search/floats`

Semantic search over float embeddings.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `q` | string | required | Natural language search query |
| `limit` | int | 10 | Max results (capped at 50) |
| `float_type` | string | — | Filter by float type |
| `region_name` | string | — | Filter by deployment region |

#### `GET /api/v1/search/floats/by-region`

Discover floats whose latest position is within a named ocean region.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `region_name` | string | required | Region name (fuzzy-matched via pg_trgm) |
| `float_type` | string | — | Optional filter: `core`, `BGC`, `deep` |

#### `GET /api/v1/search/datasets/{dataset_id}/summary`

Rich summary for a single active dataset including bbox as GeoJSON.

#### `GET /api/v1/search/datasets/summaries`

Lightweight summary cards for all active datasets. Summary text truncated to 300 chars.

#### `POST /api/v1/search/reindex/{dataset_id}`

**Requires admin JWT.** Re-embeds the dataset and all its floats, then refreshes materialized views.

---

## Quick Start

### Prerequisites

- **Docker** (PostgreSQL + PostGIS, PgBouncer, Redis, MinIO)
- **Python 3.11+**

### 1. Start infrastructure

```bash
cd floatchat
docker-compose up -d
```

| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL 15 + PostGIS | 5432 | Primary database (direct access for migrations only) |
| PgBouncer | 5433 | Connection pooler — all app queries go here |
| Redis 7 | 6379 | Celery broker, result backend & query cache |
| MinIO | 9000 (API), 9001 (Console) | S3-compatible object storage |

### 2. Install Python dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your database, Redis, S3, and optional OpenAI credentials
```

### 4. Run database migrations

```bash
alembic upgrade head
```

This runs all three migrations:
- **001** — Feature 1 schema (floats, profiles, measurements, datasets, float_positions, ingestion_jobs)
- **002** — Feature 2 schema (BIGINT columns, ocean_regions, dataset_versions, indexes, materialized views, readonly user)
- **003** — Feature 3 schema (pgvector extension, dataset_embeddings, float_embeddings, HNSW indexes)

### 5. Seed ocean regions

```bash
python scripts/seed_ocean_regions.py
```

Loads Natural Earth 1:10m ocean basin polygons into the `ocean_regions` table. Required for `get_profiles_by_basin()` queries.

### 6. Start the API server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 7. Start the Celery worker

```bash
celery -A celery_worker.celery worker --loglevel=info --pool=solo
```

### 8. (Optional) Start Celery beat for periodic stale-job retry

```bash
celery -A celery_worker.celery beat --loglevel=info
```

---

## API Endpoints

All endpoints require admin JWT authentication via `Authorization: Bearer <token>`.

### `POST /api/v1/datasets/upload`

Upload a `.nc`, `.nc4`, or `.zip` file (max 2 GB). Returns `202 Accepted` immediately with a `job_id`. All processing is async via Celery.

```
Content-Type: multipart/form-data
Form fields:
  file          (required) — .nc, .nc4, or .zip
  dataset_name  (optional) — human-readable name
```

**Response 202:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "dataset_id": 1,
  "status": "pending",
  "message": "File received. Ingestion started."
}
```

**Error responses:**
| Status | Condition |
|--------|-----------|
| 400 | Unsupported file type |
| 413 | File exceeds 2 GB limit |
| 503 | S3 staging failure |

### `GET /api/v1/datasets/jobs/{job_id}`

Poll ingestion job status.

**Response 200:**
```json
{
  "job_id": "...",
  "status": "running",
  "progress_pct": 45,
  "profiles_ingested": 220,
  "profiles_total": 490,
  "errors": [],
  "dataset_id": 12,
  "started_at": "2024-01-15T10:30:00Z",
  "completed_at": null
}
```

### `GET /api/v1/datasets/jobs`

Paginated job listing with optional status filter.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status_filter` | string | — | `pending`, `running`, `succeeded`, or `failed` |
| `limit` | int | 20 | Max results (capped at 100) |
| `offset` | int | 0 | Pagination offset |

### `POST /api/v1/datasets/jobs/{job_id}/retry`

Retry a failed job. Returns 400 if job status is not `failed`. Resets progress and re-dispatches the Celery task.

### `GET /health`

No authentication required. Returns `{"status": "ok"}`.

---

## Pipeline Modules

### Parser (`app/ingestion/parser.py`)

Opens NetCDF files with `xarray.open_dataset(decode_cf=False, mask_and_scale=False)` — no auto-decoding. Iterates over the `N_PROF` dimension to extract all profiles.

**Core ARGO variables extracted:**

| ARGO Variable | DB Column | Notes |
|---|---|---|
| `PLATFORM_NUMBER` | `platform_number` | Byte string → decoded + stripped |
| `CYCLE_NUMBER` | `cycle_number` | Integer |
| `JULD` | `timestamp` | Days since 1950-01-01 → Python datetime |
| `LATITUDE` / `LONGITUDE` | `latitude` / `longitude` | Validated: lat ±90, lon ±180 |
| `DATA_MODE` | `data_mode` | `R`, `A`, or `D` |
| `PRES` / `TEMP` / `PSAL` | Per-depth measurements | With QC flag columns |

**BGC variables (optional, NULL if absent):** `DOXY`, `CHLA`, `NITRATE`, `PH_IN_SITU_TOTAL`, `BBP700`, `DOWNWELLING_IRRADIANCE`

**Key conventions handled:**
- Fill values read from each variable's `_FillValue` attribute (never hardcoded as `99999.0`)
- QC flags: byte → char → int (e.g., `b'1'` → `'1'` → `1`)
- `JULD` fill value → `timestamp = None`, `timestamp_missing = True`
- Invalid coordinates → `position_invalid = True`

### Cleaner (`app/ingestion/cleaner.py`)

Flags outliers without removing data. Measurements outside scientific bounds get `is_outlier = True`:

| Variable | Valid Range |
|----------|-------------|
| Temperature | -2.5°C to 40°C |
| Salinity | 0 to 42 PSU |
| Pressure | 0 to 12,000 dbar |
| Dissolved oxygen | 0 to 600 µmol/kg |

Also validates `data_mode` — invalid values default to `R`.

### Writer (`app/ingestion/writer.py`)

All writes are idempotent:
- **Floats:** `INSERT ... ON CONFLICT DO NOTHING`
- **Profiles:** `INSERT ... ON CONFLICT (platform_number, cycle_number) DO UPDATE`
- **Measurements:** Delete existing for profile, then `bulk_insert_mappings` in batches of `DB_INSERT_BATCH_SIZE`
- **PostGIS geometry:** Computed from lat/lon via `shapely` + `geoalchemy2` for valid positions
- **Float positions:** Upserted after each profile for the map spatial index

**Transaction rule:** Writer never calls `commit()` — only `flush()`. The Celery task manages the single transaction boundary.

### Metadata (`app/ingestion/metadata.py`)

After all profiles are written, computes dataset statistics:
- `date_range_start` / `date_range_end` from profile timestamps
- `float_count`, `profile_count`
- `variable_list` (JSONB)
- `bbox` via PostGIS `ST_ConvexHull(ST_Collect(geom))`

**LLM summary:** If `OPENAI_API_KEY` is set, calls GPT-4o for a 2–3 sentence dataset summary. On any failure, falls back to a template string. LLM errors never fail the ingestion job.

### Celery Tasks (`app/ingestion/tasks.py`)

**`ingest_file_task(job_id, file_path, dataset_id)`** — 8-step pipeline with progress tracking:

| Step | Progress | Action |
|------|----------|--------|
| 1 | 0% | Set job to `running` |
| 2 | 5% | Upload raw file to S3 (abort on failure) |
| 3 | 10% | Validate NetCDF structure |
| 4 | 20% | Parse all profiles |
| 5 | 40% | Clean & normalize |
| 6 | 80% | DB transaction: upsert all profiles + measurements |
| 7 | 90% | Compute metadata + LLM summary |
| 8 | 100% | Set job to `succeeded` |

**`ingest_zip_task`** — Extracts ZIP, validates each `.nc`/`.nc4`, dispatches `ingest_file_task` per file. Invalid files are logged but don't fail the batch.

**Retry:** `autoretry_for=(ConnectionError, OSError)`, `max_retries=3`, exponential backoff. Validation/parse errors are permanent failures (no retry).

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+psycopg2://...localhost:5433/...` | PostgreSQL via PgBouncer (all app queries) |
| `DATABASE_URL_DIRECT` | `postgresql+psycopg2://...localhost:5432/...` | Direct PostgreSQL (Alembic migrations only) |
| `READONLY_DATABASE_URL` | `postgresql+psycopg2://floatchat_readonly:...@localhost:5433/...` | Readonly user via PgBouncer (query layer) |
| `READONLY_DB_PASSWORD` | `floatchat_readonly` | Password for the `floatchat_readonly` DB user |
| `DB_POOL_SIZE` | `10` | SQLAlchemy connection pool size |
| `DB_MAX_OVERFLOW` | `20` | Max overflow connections beyond pool size |
| `DB_POOL_RECYCLE` | `3600` | Seconds before a pooled connection is recycled |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/1` | Celery result store |
| `REDIS_CACHE_TTL_SECONDS` | `300` | Query cache TTL (seconds) |
| `REDIS_CACHE_MAX_ROWS` | `10000` | Max rows to cache (larger results skip cache) |
| `S3_ENDPOINT_URL` | — | MinIO/S3 endpoint (set for local dev) |
| `S3_ACCESS_KEY` | `minioadmin` | S3 access key |
| `S3_SECRET_KEY` | `minioadmin` | S3 secret key |
| `S3_BUCKET_NAME` | `floatchat-raw-uploads` | Upload staging bucket |
| `S3_REGION` | `us-east-1` | S3 region |
| `OPENAI_API_KEY` | — | Optional: enables LLM summary generation |
| `LLM_MODEL` | `gpt-4o` | LLM model for dataset summaries |
| `LLM_TIMEOUT_SECONDS` | `30` | LLM request timeout |
| `MAX_UPLOAD_SIZE_BYTES` | `2147483648` | Max upload size (2 GB) |
| `DB_INSERT_BATCH_SIZE` | `1000` | Measurement insert batch size |
| `SECRET_KEY` | `dev-secret-...` | JWT signing key (**change in production**) |
| `SENTRY_DSN` | — | Optional: Sentry error tracking |
| `DEBUG` | `False` | Enables `/docs` Swagger UI |
| `LOG_LEVEL` | `INFO` | structlog level |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model name |
| `EMBEDDING_DIMENSIONS` | `1536` | Embedding vector dimensions |
| `EMBEDDING_BATCH_SIZE` | `100` | Max texts per embedding API call |
| `SEARCH_SIMILARITY_THRESHOLD` | `0.3` | Min cosine similarity to include in results |
| `SEARCH_DEFAULT_LIMIT` | `10` | Default search result limit |
| `SEARCH_MAX_LIMIT` | `50` | Maximum allowed search result limit |
| `RECENCY_BOOST_DAYS` | `90` | Datasets ingested within this many days get a score boost |
| `RECENCY_BOOST_VALUE` | `0.05` | Score boost for recent datasets |
| `REGION_MATCH_BOOST_VALUE` | `0.10` | Score boost when region filter matches bbox |
| `FUZZY_MATCH_THRESHOLD` | `0.4` | pg_trgm similarity threshold for region name matching |

---

## Database Schema

10 tables + 2 materialized views created via Alembic migrations (`001_initial_schema.py` + `002_ocean_database.py` + `003_metadata_search.py`). PostGIS, pgcrypto, pgvector, and pg_trgm extensions enabled.

### `floats`
One record per unique ARGO float, keyed by `platform_number`.

| Column | Type | Notes |
|--------|------|-------|
| `float_id` | `SERIAL PK` | |
| `platform_number` | `VARCHAR(20) UNIQUE NOT NULL` | |
| `wmo_id` | `VARCHAR(20)` | |
| `float_type` | `VARCHAR(10)` | `core`, `BGC`, or `deep` |
| `deployment_date` | `TIMESTAMPTZ` | |
| `deployment_lat` / `deployment_lon` | `DOUBLE PRECISION` | |
| `country`, `program` | `VARCHAR` | |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Auto-set |

### `datasets`
One record per ingested file or batch.

| Column | Type | Notes |
|--------|------|-------|
| `dataset_id` | `SERIAL PK` | |
| `name`, `source_filename` | `VARCHAR` | |
| `raw_file_path` | `VARCHAR(1000)` | S3 key |
| `date_range_start` / `date_range_end` | `TIMESTAMPTZ` | Computed post-ingestion |
| `bbox` | `GEOGRAPHY(POLYGON, 4326)` | Convex hull of profiles |
| `float_count`, `profile_count` | `INTEGER` | |
| `variable_list` | `JSONB` | e.g., `["TEMP","PSAL","DOXY"]` |
| `summary_text` | `TEXT` | LLM-generated or fallback |
| `is_active` | `BOOLEAN` | Default `TRUE` |
| `dataset_version` | `INTEGER` | Default `1` |

### `profiles`
One record per float cycle. Unique on `(platform_number, cycle_number)`.

| Column | Type | Notes |
|--------|------|-------|
| `profile_id` | `BIGSERIAL PK` | Upgraded to BIGINT in migration 002 |
| `float_id` | `FK → floats` | |
| `platform_number` | `VARCHAR(20)` | |
| `cycle_number` | `INTEGER` | |
| `juld_raw` | `DOUBLE PRECISION` | Raw Julian days |
| `timestamp` | `TIMESTAMPTZ` | Converted from JULD |
| `timestamp_missing` | `BOOLEAN` | Fill value in JULD |
| `latitude` / `longitude` | `DOUBLE PRECISION` | |
| `position_invalid` | `BOOLEAN` | Out-of-range coords |
| `geom` | `GEOGRAPHY(POINT, 4326)` | GiST indexed |
| `data_mode` | `CHAR(1)` | `R`, `A`, or `D` |
| `dataset_id` | `FK → datasets` | |

**Indexes:** GiST on `geom`, BRIN on `timestamp`, B-tree on `float_id`.

### `measurements`
One record per depth level within a profile.

| Column | Type |
|--------|------|
| `measurement_id` | `BIGSERIAL PK` |
| `profile_id` | `FK → profiles (ON DELETE CASCADE)` BIGINT |
| `pressure`, `temperature`, `salinity` | `REAL` |
| `dissolved_oxygen`, `chlorophyll`, `nitrate`, `ph`, `bbp700`, `downwelling_irradiance` | `REAL` (BGC, nullable) |
| `pres_qc`, `temp_qc`, `psal_qc`, `doxy_qc`, `chla_qc`, `nitrate_qc`, `ph_qc` | `SMALLINT` |
| `is_outlier` | `BOOLEAN` |

**Indexes:** B-tree on `profile_id` and `pressure`.

### `float_positions`
Lightweight spatial index for map queries. One record per `(platform_number, cycle_number)`.

| Column | Type |
|--------|------|
| `position_id` | `SERIAL PK` |
| `platform_number`, `cycle_number` | Unique together |
| `timestamp` | `TIMESTAMPTZ` |
| `latitude` / `longitude` | `DOUBLE PRECISION` |
| `geom` | `GEOGRAPHY(POINT, 4326)` — GiST indexed |

### `ingestion_jobs`
Tracks every ingestion job through `pending → running → succeeded / failed`.

| Column | Type | Notes |
|--------|------|-------|
| `job_id` | `UUID PK` | Auto-generated via `gen_random_uuid()` |
| `dataset_id` | `FK → datasets` | |
| `original_filename` | `VARCHAR(500)` | |
| `raw_file_path` | `VARCHAR(1000)` | S3 key |
| `status` | `VARCHAR(20)` | `pending`, `running`, `succeeded`, `failed` |
| `progress_pct` | `INTEGER` | 0–100 |
| `profiles_total` / `profiles_ingested` | `INTEGER` | |
| `error_log` | `TEXT` | Full traceback on failure |
| `errors` | `JSONB` | Per-file error array for ZIP ingestion |

### `ocean_regions` _(Feature 2)_
Named ocean basin polygons for spatial containment queries.

| Column | Type | Notes |
|--------|------|-------|
| `region_id` | `SERIAL PK` | |
| `name` | `VARCHAR(100) UNIQUE NOT NULL` | e.g., `North Atlantic Ocean` |
| `geom` | `GEOGRAPHY(MULTIPOLYGON, 4326)` | GiST indexed |
| `created_at` | `TIMESTAMPTZ` | Auto-set |

### `dataset_versions` _(Feature 2)_
Version history for datasets.

| Column | Type | Notes |
|--------|------|-------|
| `version_id` | `SERIAL PK` | |
| `dataset_id` | `FK → datasets` | |
| `version_number` | `INTEGER NOT NULL` | Monotonically increasing per dataset |
| `created_by` | `VARCHAR(100)` | |
| `notes` | `TEXT` | Optional description of changes |
| `created_at` | `TIMESTAMPTZ` | Auto-set |

**Unique constraint:** `(dataset_id, version_number)`

### Materialized Views _(Feature 2)_

| View | Description | Refresh |
|------|-------------|---------|
| `mv_float_latest_position` | Latest position per float (platform_number, lat, lon, timestamp) | After each ingestion run + after indexing |
| `mv_dataset_stats` | Per-dataset aggregates (profile count, date range, float count) | After each ingestion run + after indexing |

Both are queried directly by the DAL — never recomputed inline.

### `dataset_embeddings` _(Feature 3)_
One row per dataset, upserted on each indexing run.

| Column | Type | Notes |
|--------|------|-------|
| `embedding_id` | `SERIAL PK` | |
| `dataset_id` | `FK → datasets UNIQUE` | One embedding per dataset |
| `embedding_text` | `TEXT NOT NULL` | Combined summary + descriptor |
| `embedding` | `vector(1536) NOT NULL` | OpenAI text-embedding-3-small |
| `status` | `VARCHAR(20)` | `indexed` or `embedding_failed` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Auto-set |

**Index:** HNSW on `embedding` with `vector_cosine_ops` (m=16, ef_construction=64).

### `float_embeddings` _(Feature 3)_
One row per float, upserted on each indexing run.

| Column | Type | Notes |
|--------|------|-------|
| `embedding_id` | `SERIAL PK` | |
| `float_id` | `FK → floats UNIQUE` | One embedding per float |
| `embedding_text` | `TEXT NOT NULL` | Float type + region + variables |
| `embedding` | `vector(1536) NOT NULL` | OpenAI text-embedding-3-small |
| `status` | `VARCHAR(20)` | `indexed` or `embedding_failed` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Auto-set |

**Index:** HNSW on `embedding` with `vector_cosine_ops` (m=16, ef_construction=64).

---

## Error Handling

From the PRD §8:

| Error Type | Handling |
|---|---|
| File too large (>2 GB) | Reject at upload, HTTP 413 |
| Invalid file type | Reject at upload, HTTP 400 |
| NetCDF cannot be opened | Mark job `failed`, store error |
| Missing required ARGO variable | Mark file `failed`, store variable name |
| Invalid coordinates | Mark profile `position_invalid = True`, continue |
| Fill value in required field | Store as `NULL`, continue |
| DB connection failure | Retry 3× with exponential backoff; fail if exhausted |
| S3 upload failure | Abort job immediately |
| LLM summary generation fails | Use fallback template, do not fail job |
| Duplicate profile (upsert) | Update existing record |

---

## Project Structure

```
backend/
├── alembic/                    # Database migrations
│   └── versions/
│       ├── 001_initial_schema.py
│       ├── 002_ocean_database.py     # Feature 2: BIGINT, ocean_regions, MVs, indexes
│       └── 003_metadata_search.py    # Feature 3: pgvector, embedding tables, HNSW indexes
├── app/
│   ├── main.py                 # FastAPI app, structlog, Sentry, /health
│   ├── config.py               # pydantic-settings (36 env vars)
│   ├── celery_app.py           # Celery configuration (ingestion + search tasks)
│   ├── api/
│   │   ├── auth.py             # JWT validation (admin role required)
│   │   └── v1/
│   │       ├── ingestion.py    # Upload + job management (4 endpoints)
│   │       └── search.py       # Feature 3: Search + discovery (6 endpoints)
│   ├── cache/                  # Feature 2
│   │   └── redis_cache.py      # Query result cache (get/set/invalidate)
│   ├── db/
│   │   ├── models.py           # SQLAlchemy 2.x ORM (10 tables + 2 MV table objects)
│   │   ├── session.py          # Engine, SessionLocal, get_db(), readonly engine, get_readonly_db()
│   │   └── dal.py              # Feature 2: Data Access Layer (10 query functions)
│   ├── ingestion/
│   │   ├── parser.py           # NetCDF → structured dicts
│   │   ├── cleaner.py          # Outlier flagging & normalization
│   │   ├── writer.py           # Idempotent DB upserts
│   │   ├── metadata.py         # Dataset stats + LLM summary
│   │   └── tasks.py            # Celery task definitions (+ search indexing trigger)
│   ├── search/                 # Feature 3: Metadata Search Engine
│   │   ├── embeddings.py       # OpenAI embedding API caller + text builders
│   │   ├── indexer.py          # DB → embedding text → upsert to embedding tables
│   │   ├── search.py           # Semantic search with hybrid scoring
│   │   ├── discovery.py        # Fuzzy region matching + float discovery + summaries
│   │   └── tasks.py            # Celery task: index_dataset_task
│   └── storage/
│       └── s3.py               # S3/MinIO upload, download, presign
├── pgbouncer/                  # Feature 2
│   ├── pgbouncer.ini           # PgBouncer configuration
│   └── userlist.txt            # PgBouncer auth file
├── scripts/                    # Feature 2
│   ├── seed_ocean_regions.py   # Seed ocean basin polygons
│   ├── create_readonly_user.sql # SQL for floatchat_readonly user
│   └── data/
│       └── ocean_regions.geojson
├── celery_worker.py            # Celery worker entry point
├── tests/
│   ├── conftest.py             # Test fixture registration
│   ├── conftest_feature2.py    # PostgreSQL + Redis fixtures for Feature 2
│   ├── fixtures/
│   │   ├── generate_fixtures.py
│   │   ├── core_single_profile.nc
│   │   ├── bgc_multi_profile.nc
│   │   └── malformed_missing_psal.nc
│   ├── test_parser.py          # 22 unit tests
│   ├── test_cleaner.py         # 23 unit tests
│   ├── test_writer.py          # 25 unit tests
│   ├── test_api.py             # 17 API tests
│   ├── test_integration.py     # 15 pipeline integration tests
│   ├── test_schema.py          # 30 schema tests (Feature 2, requires Docker)
│   ├── test_dal.py             # 21 DAL tests (Feature 2, requires Docker)
│   ├── test_cache.py           # 11 cache tests (Feature 2, requires Redis)
│   ├── test_embeddings.py      # 18 tests (Feature 3: text builders, batching, indexer)
│   ├── test_search.py          # 12 tests (Feature 3: scoring, filtering, limits)
│   └── test_discovery.py       # 18 tests (Feature 3: fuzzy match, discovery, summaries)
├── requirements.txt
└── alembic.ini
```

---

## Tech Stack

| Purpose | Library |
|---|---|
| Web framework | FastAPI |
| ASGI server | uvicorn |
| ORM | SQLAlchemy 2.x |
| DB driver | psycopg2-binary |
| Connection pooler | PgBouncer (edoburu/pgbouncer) |
| Migrations | Alembic |
| PostGIS ORM | GeoAlchemy2 |
| Geometry | Shapely |
| Vector embeddings | pgvector (PostgreSQL extension) |
| Embedding API | openai (text-embedding-3-small) |
| Vector ORM | pgvector.sqlalchemy |
| Task queue | Celery |
| Broker / Cache | Redis (redis-py) |
| NetCDF parsing | xarray + netCDF4 |
| Numerics | NumPy |
| Object storage | boto3 (S3/MinIO) |
| Structured logging | structlog |
| Error tracking | sentry-sdk |
| Config | pydantic-settings |
| LLM summaries | openai (GPT-4o) |
| Auth | python-jose (JWT) |
| Testing | pytest + httpx |

---

## Running Tests

### Feature 1 Tests (no Docker required)

```bash
# All Feature 1 tests (102 tests)
pytest tests/test_parser.py tests/test_cleaner.py tests/test_writer.py tests/test_api.py tests/test_integration.py -v

# Unit tests only (70 tests)
pytest tests/test_parser.py tests/test_cleaner.py tests/test_writer.py -v

# API + integration tests (32 tests)
pytest tests/test_api.py tests/test_integration.py -v
```

Feature 1 tests run against SQLite in-memory — no Docker required. PostGIS types (`GEOGRAPHY`, `JSONB`) are compiled to SQLite equivalents via `conftest.py` hooks.

### Feature 2 Tests (Docker required)

```bash
# All Feature 2 tests (62 tests)
pytest tests/test_schema.py tests/test_dal.py tests/test_cache.py -v
```

| Test File | Count | Requires |
|-----------|-------|----------|
| `test_schema.py` | 30 | PostgreSQL + PostGIS (Docker) |
| `test_dal.py` | 21 | PostgreSQL + PostGIS (Docker) |
| `test_cache.py` | 11 | Redis |

**Important:** Feature 2 schema and DAL tests require Docker to be running (`docker-compose up -d`). When Docker is not available, these tests **skip gracefully** with `PostgreSQL not available: connection refused` — they do not fail. Cache tests require Redis.

### Feature 3 Tests (no Docker required)

```bash
# All Feature 3 tests (48 tests)
pytest tests/test_embeddings.py tests/test_search.py tests/test_discovery.py -v
```

| Test File | Count | Covers |
|-----------|-------|--------|
| `test_embeddings.py` | 18 | Text builders, batch API calls, indexer failure handling |
| `test_search.py` | 12 | Score sorting, threshold filtering, recency boost, limits |
| `test_discovery.py` | 18 | Fuzzy region matching, float discovery, dataset summaries |

Feature 3 tests use **mocks** for OpenAI API calls and database access — no Docker or API keys required.

### Full Suite

```bash
# All tests (212 tests: 102 Feature 1 + 62 Feature 2 + 48 Feature 3)
pytest tests/ -v
```

When Docker is running: **212 passed, 0 failed**. When Docker is off: **161 passed, 58 skipped** (PG-dependent tests skip).

---

## Non-Functional Requirements

From the PRD §5:

| Category | Requirement |
|----------|-------------|
| **Performance** | 100 MB file ingested in < 5 minutes; batch inserts via `bulk_insert_mappings` (never single-row loops); horizontal scaling via multiple Celery workers |
| **Reliability** | Idempotent ingestion; single transaction per file (rollback on any failure); raw files staged to S3 before parsing |
| **Observability** | Structured JSON logs at every pipeline stage (`upload_received`, `validation_passed`, `parsing_started`, `db_write_complete`, etc.) with `job_id`; errors sent to Sentry |
| **Security** | Admin JWT required on all ingestion endpoints; S3 bucket not publicly accessible; files served only via presigned URLs |

---

## Hard Rules

These invariants are enforced across the codebase:

1. **Upload endpoint never blocks.** Returns `job_id` within 2 seconds. All processing is async via Celery.
2. **Never insert measurements in a single-row loop.** Always `bulk_insert_mappings` in batches.
3. **Never hardcode `99999.0` as the only fill value.** Always read `_FillValue` from each NetCDF variable's attributes.
4. **Never open NetCDF with xarray's auto-decoding.** Always `decode_cf=False, mask_and_scale=False`.
5. **Never cast QC flag bytes directly to int.** Decode byte → char → int.
6. **Never let LLM failures fail an ingestion job.** All LLM calls wrapped in try/except with fallback.
7. **Never write partial data.** Single transaction per file; rollback everything on failure.
8. **Ingestion must be idempotent.** Same file twice → identical DB state, not duplicates.
9. **Always stage to S3 before parsing.** If S3 upload fails, abort the job.
10. **Never expose ingestion endpoints without authentication.** All routes require admin JWT.

### Feature 2 Hard Rules

11. **Always use `GEOGRAPHY` type, never `GEOMETRY`.** All spatial columns use `GEOGRAPHY(type, 4326)`.
12. **Never write raw SQL outside `dal.py`.** All queries go through the Data Access Layer.
13. **Never connect directly to PostgreSQL port 5432 from the application.** Always through PgBouncer (port 5433). Only Alembic migrations use `DATABASE_URL_DIRECT`.
14. **The NL Query Engine must always use `get_readonly_db()`.** Never `get_db()`.
15. **Never cache query results larger than `REDIS_CACHE_MAX_ROWS`.** Large results skip the cache.
16. **Always use `pool_pre_ping=True` on SQLAlchemy engines.** Stale connections must never cause failures.
17. **Materialized views must be queried directly — never recomputed inline.** Use `refresh_materialized_views()` after ingestion.

### Feature 3 Hard Rules

18. **`embeddings.py` is the only file that calls the OpenAI embedding API.** No other module creates embeddings.
19. **Never embed texts one at a time in a loop.** Always batch via `embed_texts()` (Hard Rule #2 for embeddings).
20. **Embedding failures must never crash the pipeline.** Set `status='embedding_failed'` and continue.
21. **Always use the `<=>` cosine distance operator for vector search.** Never `<->` (L2) or `<#>` (inner product).
22. **Never return search results below `SEARCH_SIMILARITY_THRESHOLD`.** Empty list is a valid response.
23. **Never use HNSW with `op.create_index()`.** HNSW indexes require raw SQL via `op.execute()`.
24. **`resolve_region_name()` is the sole entry point for region name resolution.** No other function may query `ocean_regions` by name directly.
25. **Never expose the reindex endpoint without admin authentication.** All write endpoints require admin JWT.
26. **Never log embedding vectors.** Only log metadata (text count, tokens, time).

---

## Release Plan

| Phase | Scope | Status |
|-------|-------|--------|
| Phase 1 | Data ingestion & database | ✅ Complete |
| Phase 2 | Ocean data database & query infrastructure | ✅ Complete |
| Phase 3 | Metadata search engine | ✅ Complete |
| Phase 4 | AI query layer | Planned |
| Phase 5 | Chat UI & visualizations | Planned |
| Phase 6 | Public prototype | Planned |
