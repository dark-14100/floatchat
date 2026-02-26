# FloatChat — Feature 1: Data Ingestion Pipeline
## Implementation Phases

> **Status:** In Progress  
> **Current Phase:** Phase 10 (awaiting approval)

---

## Phase Summary

| Phase | Name | Status | Key Deliverable |
|-------|------|--------|-----------------|
| 1 | Project Scaffolding & Infrastructure | ✅ Complete | `docker-compose.yml`, `requirements.txt`, folder structure |
| 2 | Database Schema & Migrations | ✅ Complete | All 6 tables created via Alembic |
| 3 | Configuration & Application Core | ✅ Complete | `config.py`, `main.py`, structlog |
| 4 | S3/MinIO Storage Helper | ✅ Complete | `s3.py` with upload/download/presign |
| 5 | JWT Authentication | ✅ Complete | `auth.py` with admin validation |
| 6 | NetCDF Parser Module | ✅ Complete | `parser.py` with validate + parse |
| 7 | Celery Configuration | ✅ Complete | `celery_app.py` with Redis broker |
| 8 | Data Cleaner Module | ✅ Complete | `cleaner.py` with outlier detection |
| 9 | Database Writer & Metadata | ✅ Complete | `writer.py` + `metadata.py` |
| 10 | Celery Task Definitions | ⬜ Not Started | `tasks.py` + orchestration |
| 11 | API Endpoints | ⬜ Not Started | `ingestion.py` router |
| 12 | Test Fixture Generator | ⬜ Not Started | 3 synthetic NetCDF files |
| 13 | Unit Tests | ⬜ Not Started | `test_parser.py`, `test_cleaner.py`, `test_writer.py` |
| 14 | Integration Tests | ⬜ Not Started | `test_api.py`, `test_integration.py` |
| 15 | Documentation | ⬜ Not Started | `README.md` |

---

## Phase 1: Project Scaffolding & Infrastructure

**Goal:** Set up the project structure, dependencies, and local development infrastructure.

**Files Created:**
- `floatchat/docker-compose.yml`
- `floatchat/init-db.sql`
- `floatchat/backend/requirements.txt`
- `floatchat/backend/.env.example`
- `floatchat/backend/.env`
- Package `__init__.py` files (7 total)
- Placeholder `.gitkeep` files

**PRD Requirements:** Prerequisite for all FRs (infrastructure dependency from §10)

**Depends On:** None

**Done Checklist:**
- [x] `docker-compose up -d` starts all three services without error
- [x] PostgreSQL is accessible at `localhost:5432` with PostGIS extension available
- [x] Redis is accessible at `localhost:6379`
- [x] MinIO console is accessible at `localhost:9001`
- [x] `pip install -r requirements.txt` installs all dependencies without conflict

---

## Phase 2: Database Schema & Migrations

**Goal:** Define all SQLAlchemy ORM models and create the Alembic migration.

**Files Created:**
- `floatchat/backend/app/db/models.py`
- `floatchat/backend/app/db/session.py`
- `floatchat/backend/alembic.ini`
- `floatchat/backend/alembic/env.py`
- `floatchat/backend/alembic/versions/001_initial_schema.py`

**Tables Created (in FK-dependency order):**
1. `floats` — Unique `platform_number`, check constraint on `float_type`
2. `datasets` — JSONB `variable_list`, PostGIS `bbox` POLYGON
3. `profiles` — GiST index on `geom`, BRIN index on `timestamp`, unique `(platform_number, cycle_number)`
4. `measurements` — FK with `ON DELETE CASCADE`, indexes on `profile_id` and `pressure`
5. `float_positions` — Lightweight spatial index with GiST on `geom`
6. `ingestion_jobs` — UUID PK with `gen_random_uuid()`, status check constraint

**PRD Requirements:** FR-15, FR-16, FR-17, FR-18 (schema foundation); §6 Database Schema

**Depends On:** Phase 1

**Done Checklist:**
- [x] `alembic upgrade head` runs successfully
- [x] All 6 tables exist with correct columns and constraints
- [x] PostGIS GEOGRAPHY columns created on `profiles`, `datasets`, `float_positions`
- [x] GiST indexes exist on all `geom` columns
- [x] BRIN index exists on `profiles.timestamp`
- [x] `alembic downgrade base` drops all tables cleanly

---

## Phase 3: Configuration & Application Core

**Goal:** Set up FastAPI entry point, configuration management, structured logging, and error tracking.

**Files Created:**
- `floatchat/backend/app/config.py`
- `floatchat/backend/app/main.py`

**Key Features:**
- pydantic-settings `Settings` class with all environment variables
- `@lru_cache` singleton for settings
- structlog with JSON output and ISO timestamps
- Sentry integration (when `SENTRY_DSN` is set)
- `/health` endpoint returning `{"status": "ok"}`

**PRD Requirements:** §5.3 Observability (logging), §5.4 Security (Sentry)

**Depends On:** Phase 1

**Done Checklist:**
- [x] `Settings` class loads all values from `.env` without error
- [x] `uvicorn app.main:app` starts the server
- [x] `GET /health` returns `{"status": "ok"}`
- [x] Log output is JSON-formatted with ISO timestamps

---

## Phase 4: S3/MinIO Storage Helper

**Goal:** Implement the object storage interface for staging raw files before processing.

**Files to Create:**
- `floatchat/backend/app/storage/s3.py`

**Functions:**
- `upload_file_to_s3(local_path: str, s3_key: str) -> bool`
- `download_file_from_s3(s3_key: str, local_path: str) -> bool`
- `generate_presigned_url(s3_key: str, expires_in: int = 3600) -> str`

**PRD Requirements:** FR-04 (File Staging)

**Depends On:** Phase 3

**Files Created:**
- `floatchat/backend/app/storage/s3.py`

**Done Checklist:**
- [x] `upload_file_to_s3` function implemented
- [x] `download_file_from_s3` function implemented
- [x] `generate_presigned_url` function implemented
- [x] `file_exists_in_s3` helper added
- [x] `delete_file_from_s3` helper added
- [x] All operations emit structured JSON logs

---

## Phase 5: JWT Authentication

**Goal:** Implement admin authentication for API endpoints.

**Files to Create:**
- `floatchat/backend/app/api/auth.py`

**Functions:**
- `get_current_admin_user()` — FastAPI dependency

**PRD Requirements:** §5.4 Security (admin auth), §7.1 (admin role required)

**Depends On:** Phase 3

**Files Created:**
- `floatchat/backend/app/api/auth.py`

**Done Checklist:**
- [x] `get_current_user` dependency validates JWT tokens
- [x] `get_current_admin_user` checks for admin role
- [x] `create_access_token` helper for testing
- [x] Missing token returns HTTP 401
- [x] Invalid token returns HTTP 401
- [x] Non-admin role returns HTTP 403

---

## Phase 6: NetCDF Parser Module

**Goal:** Implement the core parsing logic that extracts oceanographic data from ARGO NetCDF files.

**Files to Create:**
- `floatchat/backend/app/ingestion/parser.py`

**Functions:**
- `validate_file(file_path: str) -> tuple[bool, Optional[str]]`
- `parse_netcdf_file(file_path: str) -> list[dict]`
- `juld_to_datetime(juld: float) -> Optional[datetime]`

**PRD Requirements:** FR-03, FR-06, FR-07, FR-08, FR-09, FR-10, FR-11, FR-12

**Depends On:** Phase 3

**Files Created:**
- `floatchat/backend/app/ingestion/parser.py`

**Functions Implemented:**
- `parse_netcdf_file()` — Parses single profile from NetCDF
- `parse_netcdf_all_profiles()` — Parses all profiles from multi-profile files
- `compute_file_hash()` — SHA-256 deduplication hash

**Done Checklist:**
- [x] Rejects trajectory files with clear error message
- [x] Extracts float metadata (WMO ID, float_type)
- [x] Extracts profile metadata (cycle, direction, lat/lon, timestamp)
- [x] Extracts measurements at each pressure level
- [x] BGC variables extracted when present (DOXY, CHLA, NITRATE, PH)
- [x] Fill values (99999.0, NaN) converted to None
- [x] Returns structured `ParseResult` dataclass

---

## Phase 7: Celery Configuration

**Goal:** Configure Celery for async task processing with Redis broker.

**Files Created:**
- `floatchat/backend/app/celery_app.py`

**Key Features:**
- Redis broker and result backend
- Task routing to `ingestion` queue
- `task_acks_late` for reliability
- 10-minute soft time limit, 15-minute hard limit
- Beat schedule for retrying stale jobs

**Done Checklist:**
- [x] Celery app configured with Redis broker
- [x] Task serialization set to JSON
- [x] Time limits configured
- [x] Task routing defined for ingestion tasks
- [x] Beat schedule for periodic retry task

---

## Phase 8: Data Cleaner Module

**Goal:** Implement data normalization and outlier detection.

**Files Created:**
- `floatchat/backend/app/ingestion/cleaner.py`

**Functions Implemented:**
- `clean_measurements()` — Clean list of measurements, flag outliers
- `clean_parse_result()` — Convenience wrapper for ParseResult
- `clean_measurement()` — Clean single measurement record
- `validate_against_bounds()` — Validate single value

**Outlier Bounds Implemented:**
- `temperature`: -2.5°C to 40°C
- `salinity`: 0 to 42 PSU
- `pressure`: 0 to 12000 dbar
- `oxygen`: 0 to 600 µmol/kg
- `chlorophyll_a`: 0 to 100 mg/m³
- `nitrate`: 0 to 50 µmol/kg
- `ph`: 7.0 to 8.5

**PRD Requirements:** FR-13 (Outlier Detection)

**Depends On:** Phase 6

**Done Checklist:**
- [x] Temperature 45.0°C flagged as outlier
- [x] Temperature 20.0°C not flagged
- [x] Outlier measurements retained (not deleted)
- [x] CleaningStats tracks flagged counts by variable
- [x] CleanedMeasurement preserves original values with flags

---

## Phase 9: Database Writer & Metadata Generator

**Goal:** Implement idempotent database write operations with upsert logic, batch inserts, and metadata computation.

**Files Created:**
- `floatchat/backend/app/ingestion/writer.py`
- `floatchat/backend/app/ingestion/metadata.py`

**Writer Functions Implemented:**
- `upsert_float(db, platform_number, float_type) -> int` — INSERT ON CONFLICT DO NOTHING
- `upsert_profile(db, profile_info, float_info, float_id, dataset_id) -> int` — INSERT ON CONFLICT DO UPDATE with PostGIS geometry
- `write_measurements(db, profile_id, measurements) -> int` — DELETE + bulk_insert_mappings in batches
- `upsert_float_position(db, profile_info, float_info) -> int` — lightweight spatial index
- `write_dataset(db, source_filename, ...) -> int` — create dataset record
- `write_ingestion_job(db, dataset_id, original_filename) -> str` — create job record
- `update_job_status(db, job_id, status, ...)` — update job progress
- `write_parse_result(db, parse_result, cleaning_result, dataset_id) -> dict` — orchestrate all writes

**Metadata Functions Implemented:**
- `compute_dataset_metadata(db, dataset_id) -> dict` — computes date range, counts, bbox via PostGIS
- `generate_llm_summary(metadata, dataset_name) -> str` — OpenAI GPT-4o with fallback
- `update_dataset_metadata(db, dataset_id)` — main entry point after ingestion
- `get_dataset_summary(db, dataset_id) -> dict` — retrieve dataset info

**Key Implementation Details:**
- Uses `INSERT ... ON CONFLICT` for idempotent upserts
- `bulk_insert_mappings` with `DB_INSERT_BATCH_SIZE` chunks (never single-row loops)
- PostGIS geometry via raw SQL (`ST_GeogFromText`)
- Bbox computed with `ST_ConvexHull(ST_Collect(geom))`
- Only `db.flush()` never `db.commit()` (caller handles transactions)
- LLM calls wrapped in try/except with fallback template

**PRD Requirements:** FR-15, FR-16, FR-17, FR-18, FR-19, FR-20

**Depends On:** Phase 2, Phase 6, Phase 8

**Done Checklist:**
- [x] Ingesting same profile twice results in exactly 1 row
- [x] Re-ingestion updates existing profile's `updated_at`
- [x] Measurements are replaced (not duplicated) on re-ingestion
- [x] Batch insert uses `bulk_insert_mappings`
- [x] `date_range_start` and `date_range_end` computed correctly
- [x] LLM summary generated when API key present
- [x] Fallback template used when API key missing
- [x] LLM failure does not raise exception

---

## Phase 10: Celery Task Definitions

**Goal:** Implement async task processing with job status tracking and retry logic.

**Files to Create:**
- `floatchat/backend/app/ingestion/tasks.py`
- `floatchat/backend/celery_worker.py`

**Tasks:**
- `ingest_file_task(job_id, file_path, dataset_id)`
- `ingest_zip_task(job_id, zip_path)`

**PRD Requirements:** FR-21, FR-22, FR-23

**Depends On:** Phase 4, Phase 6, Phase 7, Phase 8, Phase 9

**Done Checklist:**
- [ ] Celery worker starts successfully
- [ ] Job status transitions: `pending → running → succeeded`
- [ ] `progress_pct` updated at each stage
- [ ] DB transaction rolls back on exception
- [ ] Retry occurs on `ConnectionError`/`OSError`

---

## Phase 11: API Endpoints

**Goal:** Implement the REST API for file upload and job management.

**Files to Create:**
- `floatchat/backend/app/api/v1/ingestion.py`

**Endpoints:**
- `POST /api/v1/datasets/upload`
- `GET /api/v1/datasets/jobs/{job_id}`
- `GET /api/v1/datasets/jobs`
- `POST /api/v1/datasets/jobs/{job_id}/retry`

**PRD Requirements:** FR-01, FR-02, FR-05; §7 API Endpoints

**Depends On:** Phase 5, Phase 10

**Done Checklist:**
- [ ] Upload `.nc` file returns HTTP 202 with `job_id`
- [ ] Upload `.txt` file returns HTTP 400
- [ ] Upload without auth returns HTTP 401
- [ ] Endpoint returns within 2 seconds

---

## Phase 12: Test Fixture Generator

**Goal:** Create synthetic ARGO NetCDF files for testing.

**Files to Create:**
- `floatchat/backend/tests/fixtures/generate_fixtures.py`

**Fixtures Generated:**
- `core_single_profile.nc` — 1 profile, 10 depth levels, core variables only
- `bgc_multi_profile.nc` — 3 profiles, includes DOXY and CHLA
- `malformed_missing_psal.nc` — valid NetCDF, missing PSAL variable

**PRD Requirements:** §9.3 Test Fixtures

**Depends On:** Phase 1

---

## Phase 13: Unit Tests

**Goal:** Write unit tests for parser, cleaner, and writer modules.

**Files to Create:**
- `floatchat/backend/tests/test_parser.py`
- `floatchat/backend/tests/test_cleaner.py`
- `floatchat/backend/tests/test_writer.py`

**PRD Requirements:** §9.1 Unit Tests

**Depends On:** Phase 6, Phase 7, Phase 8, Phase 12

---

## Phase 14: Integration Tests

**Goal:** Write end-to-end integration tests for the full pipeline.

**Files to Create:**
- `floatchat/backend/tests/test_integration.py`
- `floatchat/backend/tests/test_api.py`

**PRD Requirements:** §9.2 Integration Tests

**Depends On:** Phase 11, Phase 12, Phase 13

---

## Phase 15: Documentation

**Goal:** Write setup and usage documentation.

**Files to Create:**
- `floatchat/backend/README.md`

**Contents:**
- Setup instructions
- Running services (FastAPI, Celery)
- API endpoint documentation
- Environment variable reference

**Depends On:** Phase 14

---

## Key Design Decisions

| Decision | Resolution |
|----------|------------|
| PostgreSQL port | Using 5432 (local PG service disabled) |
| `.env` file | Created from `.env.example` with dev defaults |
| ClamAV virus scanning | Skipped for v1; admin-only upload is sufficient |
| JWT auth | Minimal validator using `python-jose`, `SECRET_KEY` from settings |
| Test fixtures | Generated programmatically using `netCDF4` |
| Trajectory files | Rejected with clear error message (profile files only for v1) |
| QC flag 3 data | Stored as-is (filtering is query engine's job) |
| `float_type` | Inferred from presence of BGC variables |
| `wmo_id` vs `platform_number` | Same value stored in both columns |
| One dataset per file | ZIP with 5 files creates 5 `datasets` records |

---

## Hard Rules (from System Prompt)

1. **Upload endpoint must never block** — return `job_id` within 2 seconds
2. **Never insert measurements in a single-row loop** — always use `bulk_insert_mappings`
3. **Never hardcode `99999.0`** — always read `_FillValue` from NetCDF attributes
4. **Never open NetCDF with auto-decoding** — use `decode_cf=False, mask_and_scale=False`
5. **Never cast QC flag bytes directly to int** — decode byte to char first
6. **Never let LLM failures fail an ingestion job** — wrap in try/except with fallback
7. **Never write partial data** — wrap all DB writes in one transaction
8. **Ingestion must be idempotent** — running same file twice = identical DB state
9. **Always stage to S3 before parsing** — if S3 fails, abort the job
10. **Never expose admin endpoints without authentication** — require valid admin JWT

---

*Last Updated: February 25, 2026*
