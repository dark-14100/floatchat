# FloatChat Backend — Data Ingestion Pipeline

Backend service for ingesting ARGO oceanographic float NetCDF data into a PostgreSQL + PostGIS database via an async Celery pipeline.

## Architecture

```
                  ┌──────────────┐
                  │ FastAPI API  │
                  │  (upload +   │
                  │   job mgmt)  │
                  └──────┬───────┘
                         │ dispatches
                  ┌──────▼───────┐
                  │ Celery Worker │
                  │  (Redis)     │
                  └──────┬───────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
    ┌─────▼─────┐ ┌─────▼─────┐ ┌─────▼─────┐
    │  S3/MinIO │ │  Parser   │ │  Writer   │
    │  staging  │ │  Cleaner  │ │  (PG+GIS) │
    └───────────┘ └───────────┘ └───────────┘
```

**Pipeline flow:** Upload → S3 staging → Parse NetCDF → Clean/flag outliers → Upsert to DB → Compute metadata → LLM summary

## Prerequisites

- **Docker** (for infrastructure services)
- **Python 3.11+**

## Quick Start

### 1. Start infrastructure

```bash
cd floatchat
docker-compose up -d
```

This starts:
| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL 15 + PostGIS | 5432 | Primary database |
| Redis 7 | 6379 | Celery broker & result backend |
| MinIO | 9000 (API), 9001 (Console) | S3-compatible object storage |

### 2. Install Python dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 3. Configure environment

Copy the example env file and edit as needed:

```bash
cp .env.example .env
```

### 4. Run database migrations

```bash
alembic upgrade head
```

### 5. Start the API server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 6. Start the Celery worker

```bash
celery -A celery_worker.celery worker --loglevel=info --pool=solo
```

### 7. (Optional) Start the Celery beat scheduler

For periodic stale-job retry:

```bash
celery -A celery_worker.celery beat --loglevel=info
```

## API Endpoints

All endpoints require admin JWT authentication via `Authorization: Bearer <token>` header.

### Upload a file

```
POST /api/v1/datasets/upload
```

- Accepts `.nc`, `.nc4`, or `.zip` files (up to 2 GB)
- Returns `202 Accepted` with `job_id` immediately
- Body: `multipart/form-data` with `file` field; optional `dataset_name` field

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/datasets/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@my_argo_profile.nc"
```

**Response:**
```json
{
  "job_id": "a1b2c3d4-...",
  "dataset_id": 1,
  "status": "pending",
  "message": "File 'my_argo_profile.nc' accepted for ingestion"
}
```

### Get job status

```
GET /api/v1/datasets/jobs/{job_id}
```

Returns status, progress, errors, and timestamps.

### List jobs

```
GET /api/v1/datasets/jobs?status_filter=failed&limit=20&offset=0
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status_filter` | string | — | Filter by `pending`, `running`, `succeeded`, `failed` |
| `limit` | int | 20 | Max results (capped at 100) |
| `offset` | int | 0 | Pagination offset |

### Retry a failed job

```
POST /api/v1/datasets/jobs/{job_id}/retry
```

Only jobs with `status=failed` can be retried. Resets progress and re-dispatches the Celery task.

### Health check

```
GET /health
```

No authentication required.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+psycopg2://floatchat:floatchat@localhost:5432/floatchat` | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/1` | Celery result store |
| `S3_ENDPOINT_URL` | `None` | MinIO/S3 endpoint (set for MinIO) |
| `S3_ACCESS_KEY` | `minioadmin` | S3 access key |
| `S3_SECRET_KEY` | `minioadmin` | S3 secret key |
| `S3_BUCKET_NAME` | `floatchat-raw-uploads` | Upload staging bucket |
| `S3_REGION` | `us-east-1` | S3 region |
| `OPENAI_API_KEY` | `None` | Optional — LLM summary generation |
| `LLM_MODEL` | `gpt-4o` | LLM model for dataset summaries |
| `LLM_TIMEOUT_SECONDS` | `30` | LLM request timeout |
| `MAX_UPLOAD_SIZE_BYTES` | `2147483648` | Max upload size (2 GB) |
| `DB_INSERT_BATCH_SIZE` | `1000` | Measurement insert batch size |
| `SECRET_KEY` | `dev-secret-key-change-in-production` | JWT signing key (**change in prod**) |
| `SENTRY_DSN` | `None` | Optional — Sentry error tracking |
| `DEBUG` | `False` | Enable debug mode (exposes /docs) |
| `LOG_LEVEL` | `INFO` | Logging level |

## Project Structure

```
backend/
├── alembic/                    # Database migrations
│   └── versions/
│       └── 001_initial_schema.py
├── app/
│   ├── main.py                 # FastAPI application & lifespan
│   ├── config.py               # Pydantic settings from env
│   ├── celery_app.py           # Celery configuration
│   ├── api/
│   │   ├── auth.py             # JWT validation (admin-only)
│   │   └── v1/
│   │       └── ingestion.py    # Upload + job management endpoints
│   ├── db/
│   │   ├── models.py           # SQLAlchemy ORM (6 tables)
│   │   └── session.py          # Engine, session factory, get_db
│   ├── ingestion/
│   │   ├── parser.py           # NetCDF → structured data
│   │   ├── cleaner.py          # Outlier detection & flagging
│   │   ├── writer.py           # Idempotent DB upserts
│   │   ├── metadata.py         # Post-ingestion stats + LLM summary
│   │   └── tasks.py            # Celery task definitions
│   └── storage/
│       └── s3.py               # S3/MinIO upload/download/presign
├── celery_worker.py            # Celery worker entry point
├── tests/
│   ├── conftest.py             # SQLite session, TestClient, auth fixtures
│   ├── fixtures/
│   │   ├── generate_fixtures.py
│   │   ├── core_single_profile.nc
│   │   ├── bgc_multi_profile.nc
│   │   └── malformed_missing_psal.nc
│   ├── test_parser.py          # 22 unit tests
│   ├── test_cleaner.py         # 23 unit tests
│   ├── test_writer.py          # 25 unit tests
│   ├── test_api.py             # 17 API integration tests
│   └── test_integration.py     # 15 pipeline integration tests
├── requirements.txt
└── alembic.ini
```

## Database Schema

6 tables managed by Alembic migrations:

| Table | Description |
|-------|-------------|
| `floats` | One row per ARGO float (keyed by `platform_number`) |
| `datasets` | One row per ingested file |
| `profiles` | One row per float cycle (PostGIS POINT geometry) |
| `measurements` | One row per depth level (bulk-inserted) |
| `float_positions` | Denormalized spatial index for map queries |
| `ingestion_jobs` | Job tracking: `pending → running → succeeded/failed` |

## Running Tests

```bash
# All tests (102 total)
pytest tests/ -v

# Unit tests only
pytest tests/test_parser.py tests/test_cleaner.py tests/test_writer.py -v

# Integration tests only
pytest tests/test_api.py tests/test_integration.py -v
```

Tests use SQLite in-memory (no Docker required). PostGIS-specific types are compiled to SQLite equivalents via conftest hooks.

## Key Design Decisions

| Decision | Detail |
|----------|--------|
| **Non-blocking upload** | Returns 202 + `job_id` within 2 seconds; processing is async via Celery |
| **Idempotent ingestion** | Same file twice = identical DB state (upsert on float/profile, delete+insert on measurements) |
| **Outlier flagging, not removal** | Values outside physical bounds are flagged (`is_outlier=True`) but preserved |
| **S3 staging first** | Raw file is uploaded to S3 before parsing — if S3 fails, the job aborts |
| **Batch inserts** | Measurements are inserted via `bulk_insert_mappings` in configurable batches (default 1000) |
| **LLM failure isolation** | `metadata.py` wraps OpenAI calls in try/except with a template fallback |
| **Transaction safety** | `writer.py` never calls `commit()` — tasks.py manages the single transaction |
