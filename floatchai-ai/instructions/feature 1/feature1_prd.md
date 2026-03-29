# FloatChat — Feature 1: Data Ingestion Pipeline
## Product Requirements Document (PRD)

**Feature Name:** Data Ingestion Pipeline  
**Version:** 1.0  
**Status:** Ready for Development  
**Owner:** Backend / Data Engineering  
**Depends On:** PostgreSQL database schema (must be migrated first), S3/MinIO bucket provisioned  

---

## 1. Purpose & Background

### 1.1 What Problem Does This Solve?
ARGO float data is distributed in raw NetCDF (`.nc`) files hosted on the ARGO GDAC (Global Data Assembly Centre). These files are scientifically rich but completely inaccessible to non-technical researchers without specialized tooling. Before any natural language querying, visualization, or analysis can happen in FloatChat, this raw data must be:

1. Ingested from file into a relational database
2. Parsed into consistent, queryable columns
3. Quality-controlled and normalized
4. Indexed for spatial and temporal lookup

The Data Ingestion Pipeline is the **foundational prerequisite** for every other FloatChat feature. Without it, there is no data to query.

### 1.2 Scope of This PRD
This document covers the complete ingestion pipeline from file upload to persisted, indexed database records. It does not cover:
- The chat interface (Feature 5)
- The query engine (Feature 4)
- The metadata search index (Feature 3) — though ingestion triggers its update

---

## 2. Goals & Success Criteria

### 2.1 Goals
- Parse and store ARGO NetCDF files reliably without data loss or silent corruption
- Support both Core Argo and BGC (Biogeochemical) float profiles
- Handle data quality flags correctly per ARGO data standards
- Be robust to malformed, partial, or duplicate files
- Provide real-time visibility into ingestion status for admins

### 2.2 Success Criteria (Acceptance Tests)
| Criterion | Target |
|---|---|
| Parse success rate on valid ARGO files | ≥ 99.5% |
| Ingestion throughput | ≥ 500 profiles/minute per worker |
| Duplicate profile handling | Zero duplicate `(float_id, cycle_number)` pairs in DB |
| QC flag accuracy | 100% match against ARGO QC standards |
| Julian date conversion accuracy | ±0 seconds tolerance |
| Failed file detection | 100% of malformed files flagged and logged |
| End-to-end latency (upload → queryable) | < 5 minutes for a 100MB file |

---

## 3. User Stories

### 3.1 Data Manager (Admin)
- **US-01:** As a data manager, I want to upload a `.nc` file or a `.zip` of `.nc` files through the admin UI, so that the data becomes available in FloatChat without writing any code.
- **US-02:** As a data manager, I want to see real-time status updates during ingestion (processing, % complete, errors), so that I know when data is ready to query.
- **US-03:** As a data manager, I want failed ingestion jobs to be clearly flagged with error details, so that I can diagnose and retry them.
- **US-04:** As a data manager, I want duplicate file uploads to be handled gracefully (upsert, not error), so that re-ingesting updated data is safe.

### 3.2 Developer / API Consumer
- **US-05:** As a developer, I want to trigger ingestion via a REST API call (`POST /api/datasets/upload`), so that I can automate data pipelines from external scripts.
- **US-06:** As a developer, I want ingestion job status available via a polling endpoint, so that I can programmatically wait for data to be ready.

### 3.3 Researcher (Indirect)
- **US-07:** As a researcher, I want all float profiles to be discoverable immediately after upload, so that my queries always reflect the latest available data.

---

## 4. Functional Requirements

### 4.1 File Upload

**FR-01 — Single File Upload**
- Accept HTTP multipart file uploads of `.nc` and `.nc4` files
- Maximum single file size: **2 GB**
- Reject files that do not have `.nc` or `.nc4` extension with HTTP 400 and message `"Unsupported file type. Only .nc and .nc4 files are accepted."`

**FR-02 — Bulk Upload via ZIP**
- Accept `.zip` archives containing any number of `.nc`/`.nc4` files
- Extract ZIP in a temporary staging directory
- Validate each contained file individually before ingestion
- If any individual file fails validation, mark that file as failed; continue processing the rest
- Report per-file success/failure in the job summary

**FR-03 — File Validation**
- Check that the file is a valid NetCDF file (attempt to open with `xarray`; catch `ValueError` / `OSError`)
- Check for presence of required ARGO variables: `PRES`, `TEMP`, `PSAL`, `JULD`, `LATITUDE`, `LONGITUDE`, `PLATFORM_NUMBER`, `CYCLE_NUMBER`
- Missing required variable → mark file as failed with reason `"Missing required ARGO variable: {VAR_NAME}"`
- Warn (do not fail) if BGC variables are absent — BGC data is optional

**FR-04 — File Staging**
- On successful validation, copy raw file to object store before any parsing begins
- Object store path: `raw-uploads/{dataset_id}/{original_filename}`
- Store object store key in `ingestion_jobs.raw_file_path` column
- If object store upload fails, abort the ingestion job and return HTTP 503

**FR-05 — Upload Status Tracking**
- Every upload creates an `ingestion_jobs` record immediately with status `"pending"`
- Return `job_id` to caller synchronously; all subsequent processing is asynchronous
- Expose status via `GET /api/datasets/jobs/{job_id}`

### 4.2 Parsing

**FR-06 — Core ARGO Variable Extraction**  
Extract the following from every profile:

| ARGO Variable | DB Column | Type | Notes |
|---|---|---|---|
| `PLATFORM_NUMBER` | `platform_number` | `VARCHAR(20)` | Strip trailing whitespace |
| `CYCLE_NUMBER` | `cycle_number` | `INTEGER` | |
| `JULD` | `juld_raw` → `timestamp` | `TIMESTAMPTZ` | Convert from Julian days since 1950-01-01 |
| `LATITUDE` | `latitude` | `DOUBLE PRECISION` | Validate range: -90 to 90 |
| `LONGITUDE` | `longitude` | `DOUBLE PRECISION` | Validate range: -180 to 180 |
| `DATA_MODE` | `data_mode` | `CHAR(1)` | Values: R, A, D |
| `PRES` | `pressure` (array) | `REAL[]` | Per-depth-level, stored in `measurements` |
| `TEMP` | `temperature` | `REAL[]` | Per-depth-level |
| `PSAL` | `salinity` | `REAL[]` | Per-depth-level |
| `TEMP_QC` | `temp_qc` | `CHAR[]` | One flag per depth level |
| `PSAL_QC` | `psal_qc` | `CHAR[]` | One flag per depth level |
| `PRES_QC` | `pres_qc` | `CHAR[]` | One flag per depth level |

**FR-07 — BGC Variable Extraction (optional)**  
If present, extract:

| ARGO Variable | DB Column |
|---|---|
| `DOXY` | `dissolved_oxygen` |
| `DOXY_QC` | `doxy_qc` |
| `CHLA` | `chlorophyll` |
| `CHLA_QC` | `chla_qc` |
| `NITRATE` | `nitrate` |
| `NITRATE_QC` | `nitrate_qc` |
| `PH_IN_SITU_TOTAL` | `ph` |
| `PH_IN_SITU_TOTAL_QC` | `ph_qc` |
| `BBP700` | `bbp700` |
| `DOWNWELLING_IRRADIANCE` | `downwelling_irradiance` |

If a BGC variable is absent, store `NULL` for that column — do not fail the profile.

**FR-08 — Profile-Level vs. Measurement-Level Storage**  
- One ARGO `.nc` file contains one float's worth of profiles across multiple cycles
- Each cycle = one row in `profiles` table
- Each depth level within a cycle = one row in `measurements` table
- `measurements.profile_id` is a foreign key to `profiles.profile_id`

**FR-09 — Multi-Profile File Handling**  
ARGO files come in two formats:
- **Single-profile files** (`prof` mode): one cycle per file — iterate over `N_PROF` dimension (typically 1)
- **Multi-profile files** (`traj` mode): many cycles per file — iterate over all `N_PROF` entries
- Both must be handled identically; the parser should loop over `N_PROF` regardless

### 4.3 Cleaning & Normalization

**FR-10 — Julian Date Conversion**  
- ARGO `JULD` is days since `1950-01-01 00:00:00 UTC`
- Formula: `timestamp = datetime(1950, 1, 1, tzinfo=timezone.utc) + timedelta(days=float(JULD))`
- If `JULD` equals the ARGO fill value (`99999.0`), store `NULL` for timestamp and flag profile as `timestamp_missing = True`

**FR-11 — Fill Value Handling**  
- ARGO fill values: `99999.0` (float), `99999` (int), `' '` (char/string)
- Replace all fill values with `NULL` / `None` before storage
- Read `_FillValue` attribute from each NetCDF variable to handle custom fill values
- Do not assume a fixed fill value — always read from the variable's metadata

**FR-12 — QC Flag Storage**  
- QC flags are `bytes` or `char` arrays in ARGO NetCDF (`b'1'`, `b'2'`, etc.)
- Convert to integer: `int(chr(flag_byte))` → store as `SMALLINT` in PostgreSQL
- QC flag meanings (store as reference data):
  - `0`: No QC performed
  - `1`: Good data ✓
  - `2`: Probably good data ✓
  - `3`: Probably bad data
  - `4`: Bad data
  - `9`: Missing value

**FR-13 — Outlier Detection**  
Flag (do not delete) measurements where:
- `temperature` < -2.5°C or > 40°C
- `salinity` < 0 PSU or > 42 PSU
- `pressure` < 0 dbar or > 12000 dbar
- `dissolved_oxygen` < 0 µmol/kg or > 600 µmol/kg

Store `is_outlier = True` on the measurement row. Include outlier count in ingestion job summary.

**FR-14 — Coordinate Validation**  
- If `LATITUDE` is outside [-90, 90] or `LONGITUDE` is outside [-180, 180], mark the profile as `position_invalid = True` and exclude from PostGIS geom column
- Log a warning per invalid position

### 4.4 Storage

**FR-15 — Upsert Logic**  
- Unique constraint on `profiles(platform_number, cycle_number)`
- On re-ingestion of same float/cycle: `UPDATE` existing record (do not create duplicate)
- Upsert strategy: PostgreSQL `INSERT ... ON CONFLICT (platform_number, cycle_number) DO UPDATE SET ...`
- Cascade: upsert on `profiles` must also upsert child `measurements` (delete old, insert new)

**FR-16 — Float Record Creation**  
- Before inserting profiles, ensure a record exists in `floats` table for `platform_number`
- If not found, create a new `floats` row with available metadata
- Upsert floats too (same platform may appear across multiple dataset files)

**FR-17 — PostGIS Geometry Population**  
- For each valid profile (position not invalid), compute:  
  `geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::GEOGRAPHY`
- Store in `profiles.geom` column
- This column is indexed with a GiST index and is the basis for all spatial queries

**FR-18 — Float Position Index**  
- After all profiles are inserted for a dataset, populate `float_positions` table:  
  one row per `(platform_number, cycle_number)` with `latitude`, `longitude`, `timestamp`, `geom`
- This table is a lightweight spatial index used by the map view and nearest-float queries

### 4.5 Dataset Metadata Generation

**FR-19 — Automatic Metadata Record**  
After all profiles for a file are ingested, create/update a record in `datasets`:
- `date_range_start`: MIN(`timestamp`) of all profiles in this ingestion job
- `date_range_end`: MAX(`timestamp`) of all profiles
- `bbox`: `ST_ConvexHull(ST_Collect(geom))` of all profile geometries
- `float_count`: COUNT(DISTINCT `platform_number`)
- `profile_count`: COUNT(`profile_id`)
- `variable_list`: JSONB list of variables found in the source file (e.g., `["TEMP","PSAL","DOXY"]`)

**FR-20 — LLM-Generated Summary**  
- After metadata record is created, trigger an async LLM call (GPT-4o or Claude API)
- Prompt: `"Summarize this oceanographic dataset in 2–3 sentences for a researcher. Include the region, time period, number of floats, and which variables are available. Dataset metadata: {json.dumps(metadata)}"`
- Store response in `datasets.summary_text`
- If LLM call fails (timeout, API error), store a fallback template string instead:  
  `"Dataset contains {profile_count} profiles from {float_count} floats, spanning {date_range_start} to {date_range_end}."`

### 4.6 Pipeline Orchestration

**FR-21 — Async Processing with Celery**  
- After receiving the upload, the API endpoint immediately enqueues a Celery task and returns `{job_id, status: "pending"}`
- Celery worker picks up the task from Redis queue and executes the full pipeline
- Job status transitions: `pending → running → succeeded / failed`
- All status changes written to `ingestion_jobs` table in real time

**FR-22 — Job Status Polling Endpoint**  
`GET /api/datasets/jobs/{job_id}` returns:
```json
{
  "job_id": "...",
  "status": "running",
  "progress_pct": 45,
  "profiles_ingested": 220,
  "profiles_total": 490,
  "errors": [],
  "started_at": "...",
  "completed_at": null
}
```

**FR-23 — Retry Logic**  
- Transient failures (DB connection loss, S3 timeout): auto-retry up to 3 times with exponential backoff (10s, 30s, 90s)
- Permanent failures (malformed file, validation error): mark job as `failed` immediately, do not retry
- On final failure, store full Python traceback in `ingestion_jobs.error_log`

---

## 5. Non-Functional Requirements

### 5.1 Performance
- The pipeline must ingest a 100MB ARGO NetCDF file (containing ~500 profiles) in under 5 minutes wall clock time
- Database inserts must use batch operations (`executemany` / SQLAlchemy `bulk_insert_mappings`) — never single-row inserts in a loop
- Batch size for DB inserts: 1,000 rows per commit
- The pipeline must support horizontal scaling: multiple Celery workers processing different files in parallel

### 5.2 Reliability
- The ingestion pipeline must be idempotent: running the same file twice must produce the same database state, not duplicate data
- All database operations must be wrapped in transactions: if any step fails, roll back the entire job (no partial ingestion)
- Raw files must be stored in object storage before any parsing begins, so that failed jobs can always be retried from the original file

### 5.3 Observability
- Every ingestion job must emit structured logs at each stage: `file_received`, `validation_passed`, `parsing_started`, `profiles_parsed`, `db_write_started`, `db_write_complete`, `metadata_generated`, `job_complete`
- Log format: JSON with fields `job_id`, `stage`, `timestamp`, `details`
- Errors must be sent to Sentry with `job_id` and `file_name` as tags

### 5.4 Security
- The upload endpoint must require admin authentication (JWT with `role: admin`)
- Uploaded files must be virus-scanned before staging (ClamAV or AWS Macie if on AWS)
- The S3/MinIO bucket must not be publicly accessible; files served only via presigned URLs

---

## 6. Database Schema

### 6.1 `floats` Table
```sql
CREATE TABLE floats (
    float_id        SERIAL PRIMARY KEY,
    platform_number VARCHAR(20) NOT NULL UNIQUE,
    wmo_id          VARCHAR(20),
    float_type      VARCHAR(10) CHECK (float_type IN ('core', 'BGC', 'deep')),
    deployment_date TIMESTAMPTZ,
    deployment_lat  DOUBLE PRECISION,
    deployment_lon  DOUBLE PRECISION,
    country         VARCHAR(100),
    program         VARCHAR(200),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### 6.2 `profiles` Table
```sql
CREATE TABLE profiles (
    profile_id       SERIAL PRIMARY KEY,
    float_id         INTEGER NOT NULL REFERENCES floats(float_id),
    platform_number  VARCHAR(20) NOT NULL,
    cycle_number     INTEGER NOT NULL,
    juld_raw         DOUBLE PRECISION,
    timestamp        TIMESTAMPTZ,
    timestamp_missing BOOLEAN DEFAULT FALSE,
    latitude         DOUBLE PRECISION,
    longitude        DOUBLE PRECISION,
    position_invalid BOOLEAN DEFAULT FALSE,
    geom             GEOGRAPHY(POINT, 4326),
    data_mode        CHAR(1) CHECK (data_mode IN ('R', 'A', 'D')),
    dataset_id       INTEGER REFERENCES datasets(dataset_id),
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (platform_number, cycle_number)
);

CREATE INDEX idx_profiles_geom ON profiles USING GIST (geom);
CREATE INDEX idx_profiles_timestamp ON profiles USING BRIN (timestamp);
CREATE INDEX idx_profiles_float_id ON profiles (float_id);
```

### 6.3 `measurements` Table
```sql
CREATE TABLE measurements (
    measurement_id          SERIAL PRIMARY KEY,
    profile_id              INTEGER NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    pressure                REAL,
    temperature             REAL,
    salinity                REAL,
    dissolved_oxygen        REAL,
    chlorophyll             REAL,
    nitrate                 REAL,
    ph                      REAL,
    bbp700                  REAL,
    downwelling_irradiance  REAL,
    pres_qc                 SMALLINT,
    temp_qc                 SMALLINT,
    psal_qc                 SMALLINT,
    doxy_qc                 SMALLINT,
    chla_qc                 SMALLINT,
    nitrate_qc              SMALLINT,
    ph_qc                   SMALLINT,
    is_outlier              BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_measurements_profile_id ON measurements (profile_id);
CREATE INDEX idx_measurements_pressure ON measurements (pressure);
```

### 6.4 `datasets` Table
```sql
CREATE TABLE datasets (
    dataset_id       SERIAL PRIMARY KEY,
    name             VARCHAR(255),
    source_filename  VARCHAR(500),
    raw_file_path    VARCHAR(1000),
    ingestion_date   TIMESTAMPTZ DEFAULT NOW(),
    date_range_start TIMESTAMPTZ,
    date_range_end   TIMESTAMPTZ,
    bbox             GEOGRAPHY(POLYGON, 4326),
    float_count      INTEGER,
    profile_count    INTEGER,
    variable_list    JSONB,
    summary_text     TEXT,
    is_active        BOOLEAN DEFAULT TRUE,
    dataset_version  INTEGER DEFAULT 1,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);
```

### 6.5 `float_positions` Table
```sql
CREATE TABLE float_positions (
    position_id     SERIAL PRIMARY KEY,
    platform_number VARCHAR(20) NOT NULL,
    cycle_number    INTEGER NOT NULL,
    timestamp       TIMESTAMPTZ,
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    geom            GEOGRAPHY(POINT, 4326),
    UNIQUE (platform_number, cycle_number)
);

CREATE INDEX idx_float_positions_geom ON float_positions USING GIST (geom);
```

### 6.6 `ingestion_jobs` Table
```sql
CREATE TABLE ingestion_jobs (
    job_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id       INTEGER REFERENCES datasets(dataset_id),
    original_filename VARCHAR(500),
    raw_file_path    VARCHAR(1000),
    status           VARCHAR(20) DEFAULT 'pending'
                     CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    progress_pct     INTEGER DEFAULT 0,
    profiles_total   INTEGER,
    profiles_ingested INTEGER DEFAULT 0,
    error_log        TEXT,
    errors           JSONB DEFAULT '[]',
    started_at       TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 7. API Endpoints

### 7.1 Upload Endpoint
```
POST /api/v1/datasets/upload
Auth: Bearer JWT (admin role required)
Content-Type: multipart/form-data

Form fields:
  file        (required) — .nc, .nc4, or .zip file
  dataset_name (optional) — human-readable name for this dataset

Response 202 Accepted:
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "File received. Ingestion started."
}

Response 400 Bad Request:
{ "error": "Unsupported file type. Only .nc, .nc4, and .zip files are accepted." }

Response 413 Payload Too Large:
{ "error": "File exceeds maximum size of 2GB." }
```

### 7.2 Job Status Endpoint
```
GET /api/v1/datasets/jobs/{job_id}
Auth: Bearer JWT (admin role required)

Response 200:
{
  "job_id": "...",
  "status": "running",          // pending | running | succeeded | failed
  "progress_pct": 45,
  "profiles_ingested": 220,
  "profiles_total": 490,
  "errors": [
    { "file": "abc.nc", "reason": "Missing PSAL variable" }
  ],
  "dataset_id": 12,
  "started_at": "2024-01-15T10:30:00Z",
  "completed_at": null
}
```

### 7.3 List Jobs Endpoint
```
GET /api/v1/datasets/jobs?status=failed&limit=20&offset=0
Auth: Bearer JWT (admin role required)

Response 200:
{
  "total": 3,
  "jobs": [ { ...job object... }, ... ]
}
```

### 7.4 Retry Job Endpoint
```
POST /api/v1/datasets/jobs/{job_id}/retry
Auth: Bearer JWT (admin role required)

Response 202:
{ "job_id": "...", "status": "pending", "message": "Job re-queued." }

Response 400 (if job not failed):
{ "error": "Only failed jobs can be retried." }
```

---

## 8. Error Handling

| Error Type | Handling |
|---|---|
| File too large (>2GB) | Reject at upload, HTTP 413 |
| Invalid file type | Reject at upload, HTTP 400 |
| NetCDF cannot be opened | Mark job as `failed`, store error |
| Missing required ARGO variable | Mark file as `failed`, store variable name |
| Invalid coordinates | Mark profile as `position_invalid`, continue |
| Fill value in required field | Store as NULL, continue |
| DB connection failure | Retry 3x with backoff; fail job if all retries exhausted |
| S3 upload failure | Abort job immediately, HTTP 503 |
| LLM summary generation fails | Use fallback template string, do not fail job |
| Duplicate profile (upsert) | Update existing, log as `updated_existing: true` |

---

## 9. Testing Requirements

### 9.1 Unit Tests
- `test_parse_core_variables()` — verify extraction of all 6 core variables from a sample `.nc` file
- `test_parse_bgc_variables()` — verify BGC variables extracted when present, NULL when absent
- `test_julian_date_conversion()` — spot-check known JULD → timestamp conversions
- `test_fill_value_handling()` — verify `99999.0` becomes `NULL`, not `0` or `99999`
- `test_qc_flag_conversion()` — verify bytes `b'1'` → integer `1`
- `test_outlier_detection()` — verify temperature `45.0°C` flagged as outlier
- `test_coordinate_validation()` — verify lat `95.0` flagged as invalid

### 9.2 Integration Tests
- `test_full_ingestion_single_file()` — upload a real ARGO `.nc` file, assert all DB rows created
- `test_upsert_on_duplicate()` — ingest same file twice, assert no duplicate rows
- `test_zip_ingestion_partial_failure()` — ZIP with one valid and one invalid file; assert valid file processed, invalid flagged
- `test_job_status_transitions()` — assert job moves through `pending → running → succeeded`
- `test_retry_failed_job()` — simulate failure, assert retry resets status and re-runs pipeline

### 9.3 Test Fixtures
- Include 3 sample ARGO NetCDF files in `tests/fixtures/`:
  - `core_single_profile.nc` — minimal core ARGO file, 1 profile
  - `bgc_multi_profile.nc` — BGC float, 10 profiles
  - `malformed_missing_psal.nc` — missing `PSAL` variable (used for failure testing)

---

## 10. Dependencies & Prerequisites

| Dependency | Reason | Must Be Ready Before |
|---|---|---|
| PostgreSQL 15 + PostGIS | Target database | Day 1 |
| Alembic migrations applied | Tables must exist | Day 1 |
| Redis instance running | Celery broker | Day 1 |
| S3/MinIO bucket provisioned | File staging | Day 1 |
| Celery worker process | Async job execution | Before testing |
| Admin auth JWT | Endpoint security | Before API testing |
| LLM API key (GPT-4o or Claude) | Metadata summary generation | Can stub for early testing |

---

## 11. Out of Scope for v1.0

- Automated ARGO GDAC sync (pulling new files from the ARGO FTP/HTTPS server automatically)
- Streaming ingestion (processing before full download completes)
- Support for Argo trajectory files (`*_traj.nc`)
- BGC delayed-mode data adjustments (stored as received; no reprocessing)
- Multi-tenancy (data isolation per user/organization)

---

## 12. Open Questions

| # | Question | Owner | Due |
|---|---|---|---|
| Q1 | Should we support ARGO Trajectory (traj) NetCDF files in v1, or profile files only? | Product | Before dev start |
| Q2 | What is the expected dataset size per upload? Are files from full ARGO GDAC archives (50GB+) in scope? | Data Team | Before dev start |
| Q3 | Should QC = 3 (probably bad) data be stored or discarded? PRD assumes stored with flag; confirm. | Product | Before dev start |
| Q4 | Is ClamAV virus scanning required, or is admin-only upload sufficient security? | Security | Before deploy |
| Q5 | LLM provider: GPT-4o or Claude? Need confirmed API key and billing setup. | Infra | Before integration |
