# FloatChat — Feature 3: Metadata Search Engine
## Implementation Phases

**Status:** Complete — all 12 phases done
**Created:** 2026-02-26

---

## Gap Resolutions (Pre-Implementation Decisions)

| # | Gap | Resolution |
|---|---|---|
| 1 | pgvector not in Docker image | Custom `backend/Dockerfile.postgres` extending `postgis/postgis:15-3.4` with pgvector apt package. Update `docker-compose.yml` to build from it. |
| 2 | Incremental vs full float re-embedding | Full re-embed all floats linked to the dataset. System prompt already assumes this. |
| 3 | Pagination for `get_all_summaries` | No pagination for v1. Flat list of all active datasets. |
| 4 | `build_float_embedding_text` needs DB access | Pre-resolve region name in `indexer.py`, pass as string parameter. Embeddings module stays DB-free. |
| 5 | `celery_app.py` and `main.py` need modification | Confirmed. Both are required modifications. |
| 6 | Task routing for `index_dataset_task` | Route to `"default"` queue for v1. |
| 7 | `mv_float_latest_position` never refreshed | Refresh both materialized views in `index_dataset_task` after successful reindex. |
| 8 | Missing `pgvector` Python package | Add `pgvector>=0.2.5` to `requirements.txt`. |
| 9 | Q2 (search auth) | Resolved by system prompt. Read endpoints public, write endpoints admin-only. |
| 10 | Q3 (HNSW vs IVFFlat) | Resolved by system prompt. HNSW mandated. |
| 11 | One-directional relationship | Confirmed. No `back_populates` on existing models. |

---

## Phase 1 — Infrastructure & Dependencies

**Status:** COMPLETE
**Goal:** Ensure pgvector is available in Docker and all required Python packages are installed.

**Files to create:**
- `backend/Dockerfile.postgres`

**Files to modify:**
- `docker-compose.yml` — switch postgres service from `image:` to `build:` using Dockerfile.postgres
- `init-db.sql` — add `CREATE EXTENSION IF NOT EXISTS vector` and verification
- `requirements.txt` — add `pgvector>=0.2.5`
- `.env.example` — add `EMBEDDING_MODEL` and `EMBEDDING_DIMENSIONS`

**Tasks:**
1. Create `backend/Dockerfile.postgres` extending `postgis/postgis:15-3.4`, installing pgvector apt package
2. Update `docker-compose.yml` postgres service to `build:` with `dockerfile: Dockerfile.postgres`
3. Add `CREATE EXTENSION IF NOT EXISTS vector` to `init-db.sql` with verification
4. Add `pgvector>=0.2.5` to `requirements.txt`
5. Add `EMBEDDING_MODEL` and `EMBEDDING_DIMENSIONS` to `.env.example` under a Feature 3 section

**PRD requirements fulfilled:** FR-01, FR-02 (partial — extension availability)

**Depends on:** None

**Done when:**
- [x] `Dockerfile.postgres` exists and builds successfully
- [x] `docker-compose.yml` references the custom Dockerfile
- [x] `init-db.sql` enables the `vector` extension
- [x] `pgvector>=0.2.5` is in `requirements.txt`
- [x] `.env.example` contains `EMBEDDING_MODEL` and `EMBEDDING_DIMENSIONS`

---

## Phase 2 — Configuration

**Status:** COMPLETE
**Goal:** Add all Feature 3 settings to the application config.

**Files to modify:**
- `app/config.py` — add 10 new settings fields to the `Settings` class

**Tasks:**
1. Add `EMBEDDING_MODEL: str = "text-embedding-3-small"`
2. Add `EMBEDDING_DIMENSIONS: int = 1536`
3. Add `EMBEDDING_BATCH_SIZE: int = 100`
4. Add `SEARCH_SIMILARITY_THRESHOLD: float = 0.3`
5. Add `SEARCH_DEFAULT_LIMIT: int = 10`
6. Add `SEARCH_MAX_LIMIT: int = 50`
7. Add `RECENCY_BOOST_DAYS: int = 90`
8. Add `RECENCY_BOOST_VALUE: float = 0.05`
9. Add `REGION_MATCH_BOOST_VALUE: float = 0.10`
10. Add `FUZZY_MATCH_THRESHOLD: float = 0.4`

**PRD requirements fulfilled:** §7 Configuration Settings

**Depends on:** None

**Done when:**
- [x] All 10 settings are present in the `Settings` class with correct defaults
- [x] No existing settings are removed or renamed
- [x] Application can import `settings` and access all new fields

---

## Phase 3 — Database Migration (003)

**Status:** COMPLETE
**Goal:** Create the Alembic migration that enables pgvector and creates both embedding tables with HNSW indexes.

**Files to create:**
- `alembic/versions/003_metadata_search.py`

**Tasks:**
1. Create migration file with `revision = "003"`, `down_revision = "002"`
2. `upgrade()`: Execute `CREATE EXTENSION IF NOT EXISTS vector`
3. `upgrade()`: Create `dataset_embeddings` table with all columns per PRD §6.1
4. `upgrade()`: Create `float_embeddings` table with all columns per PRD §6.1
5. `upgrade()`: Create HNSW index on `dataset_embeddings.embedding` via `op.execute()` raw SQL with `vector_cosine_ops`, `m=16`, `ef_construction=64`
6. `upgrade()`: Create HNSW index on `float_embeddings.embedding` via `op.execute()` raw SQL
7. `downgrade()`: Drop HNSW indexes, drop both tables, drop vector extension

**PRD requirements fulfilled:** FR-02, FR-06, FR-07, FR-08, §6

**Depends on:** Phase 1 (pgvector must be installable in PostgreSQL)

**Done when:**
- [x] Migration file exists at correct path with `down_revision = "002"`
- [x] `upgrade()` creates vector extension, both tables, and both HNSW indexes
- [x] `downgrade()` drops indexes, tables, and extension in correct order
- [x] HNSW indexes use `op.execute()` with raw SQL (not `op.create_index`)
- [x] All column types, constraints, and defaults match PRD §6.1

---

## Phase 4 — ORM Models

**Status:** COMPLETE
**Goal:** Add `DatasetEmbedding` and `FloatEmbedding` SQLAlchemy models.

**Files to modify:**
- `app/db/models.py` — add two new model classes

**Tasks:**
1. Add `from pgvector.sqlalchemy import Vector` import
2. Add `DatasetEmbedding` model with all fields per system prompt (embedding_id, dataset_id unique FK, embedding_text, embedding Vector(1536), status, created_at, updated_at)
3. Add `FloatEmbedding` model with all fields per system prompt (same structure, float_id FK instead)
4. Both models use one-directional `relationship()` pointing to parent — no `back_populates` on existing models

**PRD requirements fulfilled:** FR-06, FR-07

**Depends on:** Phase 1 (pgvector Python package), Phase 3 (tables exist in DB)

**Done when:**
- [x] Both models exist in `models.py` with correct table names
- [x] `Vector(1536)` column type is used from `pgvector.sqlalchemy`
- [x] Unique constraints on `dataset_id` / `float_id`
- [x] `status` defaults to `'indexed'`
- [x] No existing models are modified
- [x] Relationships are one-directional

---

## Phase 5 — Embeddings Module

**Status:** COMPLETE
**Goal:** Build the centralized OpenAI embedding API caller with batch support and text builders.

**Files to create:**
- `app/search/__init__.py`
- `app/search/embeddings.py`

**Tasks:**
1. Create `app/search/__init__.py` (empty or minimal)
2. Implement `build_dataset_embedding_text(dataset)` — combines summary_text + structured descriptor string
3. Implement `build_float_embedding_text(float_obj, variables_list, region_name)` — builds descriptor including pre-resolved region name (per Gap 4 resolution)
4. Implement `embed_texts(texts, client)` — batches texts into groups of `EMBEDDING_BATCH_SIZE`, one API call per batch, returns flat list of vectors
5. Implement `embed_single(text, client)` — convenience wrapper calling `embed_texts` with a single-item list
6. Add structlog logging: text count, token usage, time taken
7. Never log embedding vectors (Hard Rule #9)
8. Raise errors immediately — no retry logic here (retries are in the Celery task)

**PRD requirements fulfilled:** FR-03, FR-04, FR-05, FR-12

**Depends on:** Phase 2 (config settings for model name, batch size)

**Done when:**
- [x] `embeddings.py` is the only file that calls the OpenAI embedding API (Hard Rule #1)
- [x] `embed_texts` batches correctly and never calls API once-per-text (Hard Rule #2)
- [x] Text builders produce non-empty strings containing expected fields
- [x] Logging includes text count, tokens, time — never vectors
- [x] No DB access in this module

---

## Phase 6 — Indexer Module

**Status:** COMPLETE
**Goal:** Build the logic that constructs embedding texts from DB records and persists them.

**Files to create:**
- `app/search/indexer.py`

**Tasks:**
1. Implement `index_dataset(dataset_id, db, openai_client)` — fetch dataset, build text, call `embed_single`, upsert into `dataset_embeddings` with ON CONFLICT, handle failure by setting `status='embedding_failed'`
2. Implement `index_floats_for_dataset(dataset_id, db, openai_client)` — fetch floats, pre-resolve region names from `ocean_regions` via spatial query (per Gap 4), build texts, call `embed_texts` with batching, upsert all, handle partial failures per batch
3. Implement `reindex_dataset(dataset_id, db, openai_client)` — calls `index_dataset` then `index_floats_for_dataset`, both must run even if one fails
4. All upserts use `INSERT ... ON CONFLICT ... DO UPDATE` for idempotency
5. Log dataset_id, float count, and time taken

**PRD requirements fulfilled:** FR-09 (partial), FR-10, FR-13

**Depends on:** Phase 4 (ORM models), Phase 5 (embeddings module)

**Done when:**
- [x] `index_dataset` upserts correctly and handles failure gracefully (Hard Rule #3)
- [x] `index_floats_for_dataset` batches correctly and handles partial failures
- [x] `reindex_dataset` runs both operations even if one fails
- [x] Region resolution happens here, not in embeddings.py
- [x] Re-indexing is idempotent — no duplicate rows

---

## Phase 7 — Search Module

**Status:** COMPLETE
**Goal:** Implement semantic search with hybrid scoring for datasets and floats.

**Files to create:**
- `app/search/search.py`

**Tasks:**
1. Implement `search_datasets(query, db, openai_client, filters, limit)` per system prompt spec
2. Implement `search_floats(query, db, openai_client, filters, limit)` per system prompt spec
3. Use pgvector `<=>` cosine distance operator (Hard Rule #6)
4. Apply recency boost (+0.05 for datasets within RECENCY_BOOST_DAYS)
5. Apply region match boost (+0.10 when region filter matches bbox)
6. Filter out results below SEARCH_SIMILARITY_THRESHOLD (Hard Rule #5)
7. Filter out `status = 'embedding_failed'` results
8. Cap score at 1.0
9. Retrieve 3× limit candidates before filtering/boosting, then return top `limit`
10. Validate limit does not exceed SEARCH_MAX_LIMIT
11. Log query text (truncated to 100 chars), result count, total time

**PRD requirements fulfilled:** FR-14, FR-15, FR-16, FR-17, FR-18

**Depends on:** Phase 2 (config), Phase 4 (ORM models), Phase 5 (embed_single for query embedding)

**Done when:**
- [x] Both search functions return ranked results with scores
- [x] Cosine distance operator `<=>` is used (not `<->` or `<#>`)
- [x] Recency and region boosts applied correctly
- [x] Results below threshold are excluded
- [x] Empty list returned when no results meet threshold (not an error)
- [x] `limit` validated and respected

---

## Phase 8 — Discovery Module

**Status:** COMPLETE
**Goal:** Implement float discovery, fuzzy region resolution, and dataset summary functions.

**Files to create:**
- `app/search/discovery.py`

**Tasks:**
1. Implement `resolve_region_name(region_name, db)` — query `ocean_regions` with `pg_trgm` `similarity()`, threshold from config, return match or raise ValueError with top 3 suggestions (Hard Rule #7)
2. Implement `discover_floats_by_region(region_name, float_type, db)` — resolve region, query `mv_float_latest_position` with `ST_Within`, optionally filter by float_type
3. Implement `discover_floats_by_variable(variable_name, db)` — validate variable against allowed list, query measurements joined to floats
4. Implement `get_dataset_summary(dataset_id, db)` — return rich dict per FR-22, convert bbox to GeoJSON, raise ValueError if not found or inactive
5. Implement `get_all_summaries(db)` — return lightweight summaries for all active datasets, ordered by ingestion_date desc, truncate summary_text to 300 chars, no pagination

**PRD requirements fulfilled:** FR-19, FR-20, FR-21, FR-22, FR-23

**Depends on:** Phase 2 (config for fuzzy threshold), Phase 4 (ORM models)

**Done when:**
- [x] `resolve_region_name` is the sole point for region name resolution (Hard Rule #7)
- [x] Fuzzy matching uses `pg_trgm` `similarity()` function
- [x] "Bengal Bay" resolves to "Bay of Bengal" when threshold met
- [x] ValueError raised with suggestions when no match
- [x] Discovery functions return correct float metadata
- [x] Summaries return only active datasets

---

## Phase 9 — Celery Task & App Wiring

**Status:** COMPLETE
**Goal:** Create the `index_dataset_task` Celery task and register it for discovery.

**Files to create:**
- `app/search/tasks.py` ← IMPORTANT: this is `app/search/tasks.py`, NOT a root-level `tasks.py`. Do not confuse with `app/ingestion/tasks.py`.

**Files to modify:**
- `app/celery_app.py` — add `app.search.tasks` to `include` list and task routing

**Tasks:**
1. Implement `index_dataset_task(dataset_id)` as a bound Celery task in `app/search/tasks.py`
2. Configure: `max_retries=3`, `default_retry_delay=10`, `autoretry_for=(openai.APIConnectionError, openai.RateLimitError)`
3. Do not retry on `openai.AuthenticationError` or `openai.NotFoundError`
4. Call `reindex_dataset(dataset_id, db, openai_client)` inside the task
5. After successful reindex, execute `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_float_latest_position` and `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_dataset_stats` (per Gap 7 resolution)
6. Log completion with dataset_id, float count, total time
7. Update `app/celery_app.py`: add `"app.search.tasks"` to `include` list
8. Update `app/celery_app.py`: add task route for `index_dataset_task` to `"default"` queue

**PRD requirements fulfilled:** FR-09, FR-10, FR-13

**Depends on:** Phase 6 (indexer module)

**Done when:**
- [x] Task file is at `app/search/tasks.py` (not root level)
- [x] Task is discoverable by Celery workers
- [x] Retry logic works for transient errors only
- [x] Permanent errors do not trigger retry
- [x] Materialized views are refreshed after indexing
- [x] Task never crashes on indexing failure (Hard Rule #3)
- [x] Celery `include` and `task_routes` updated in `app/celery_app.py`

---

## Phase 10 — API Router & App Wiring

**Status:** COMPLETE
**Goal:** Expose all six search/discovery endpoints and register the router.

**Router mount point:** `/api/v1/search` — all endpoint paths below are relative to this prefix.
- Full path example: `GET /api/v1/search/datasets` (not `GET /api/v1/datasets`)
- Full path example: `GET /api/v1/search/floats/by-region` (not `GET /api/v1/floats/by-region`)
- Full path example: `GET /api/v1/search/datasets/summaries`

**Files to create:**
- `app/api/v1/search.py`

**Files to modify:**
- `app/main.py` — register the search router with `prefix="/api/v1/search"`

**Tasks:**
1. Implement `GET /datasets` → calls `search_datasets`
2. Implement `GET /floats` → calls `search_floats`
3. Implement `GET /floats/by-region` → calls `discover_floats_by_region`
4. Implement `GET /datasets/{dataset_id}/summary` → calls `get_dataset_summary`
5. Implement `GET /datasets/summaries` → calls `get_all_summaries`
6. Implement `POST /reindex/{dataset_id}` → admin JWT required (Hard Rule #8), enqueues `index_dataset_task`
7. All endpoints: return HTTP 404 for not found, 400 for invalid params, 503 if pgvector unavailable
8. All endpoints: log endpoint name, params, response time via structlog
9. Register router in `app/main.py` with `app.include_router(search_router, prefix="/api/v1/search")`

**PRD requirements fulfilled:** FR-11, FR-24, FR-25, FR-26, FR-27, FR-28, FR-29

**Depends on:** Phase 7 (search), Phase 8 (discovery), Phase 9 (Celery task for reindex)

**Done when:**
- [x] All 6 endpoints exist and are reachable at correct full paths under `/api/v1/search/`
- [x] GET endpoints have no auth requirement
- [x] POST reindex requires admin JWT
- [x] Error responses use correct HTTP status codes (400, 404, 503)
- [x] Router is registered in `app/main.py` at `/api/v1/search`

---

## Phase 11 — Feature 1 Integration

**Status:** COMPLETE
**Goal:** Add the post-ingestion trigger that enqueues indexing after successful ingestion.

**Files to modify:**
- `app/ingestion/tasks.py` — add one fire-and-forget call to `index_dataset_task.delay()`

**Tasks:**
1. At the end of `ingest_file_task`, after job status is set to `"succeeded"`, add `index_dataset_task.delay(dataset_id=dataset_id)`
2. Wrap the `.delay()` call in a try/except — if enqueueing fails, log a warning but do not fail the ingestion job
3. Do not import the task at module top level — use a late import inside the function to avoid circular dependencies

**PRD requirements fulfilled:** FR-09

**Depends on:** Phase 9 (Celery task must exist at `app/search/tasks.py`)

**Done when:**
- [x] `ingest_file_task` enqueues `index_dataset_task` after success
- [x] Enqueueing failure does not fail the ingestion job (Hard Rule #3)
- [x] The call is fire-and-forget — ingestion does not wait for indexing
- [x] No existing ingestion logic is modified, only an additive call at the end

---

## Phase 12 — Tests

**Status:** COMPLETE
**Goal:** Write all unit tests specified in the PRD and system prompt.

**Files to create:**
- `tests/test_embeddings.py`
- `tests/test_search.py`
- `tests/test_discovery.py`

**Tasks:**
1. `test_embeddings.py`: Test `build_dataset_embedding_text` produces non-empty string with dataset name and variables
2. `test_embeddings.py`: Test `build_float_embedding_text` produces string with float type and platform number
3. `test_embeddings.py`: Test `embed_texts` with 150 strings calls API exactly twice (batch 100)
4. `test_embeddings.py`: Test `embed_texts` returns correct length list with 1536-dim vectors
5. `test_embeddings.py`: Test `index_dataset` sets `embedding_failed` on API error without raising
6. `test_search.py`: Test results sorted by score descending
7. `test_search.py`: Test results below threshold excluded
8. `test_search.py`: Test variable filter excludes non-matching datasets
9. `test_search.py`: Test date_from filter works
10. `test_search.py`: Test recency boost increases score
11. `test_search.py`: Test limit respected and capped at max
12. `test_search.py`: Test empty list returned when no results meet threshold
13. `test_discovery.py`: Test "Bengal Bay" → "Bay of Bengal" fuzzy match
14. `test_discovery.py`: Test ValueError with suggestions for unrecognized names
15. `test_discovery.py`: Test `discover_floats_by_region` returns only floats within polygon
16. `test_discovery.py`: Test `discover_floats_by_variable` raises ValueError for unsupported variables
17. `test_discovery.py`: Test `get_all_summaries` returns only active datasets
18. `test_discovery.py`: Test `get_dataset_summary` raises ValueError for inactive dataset

**PRD requirements fulfilled:** §9 Testing Requirements

**Depends on:** All prior phases (1–11)

**Done when:**
- [x] All 3 test files exist with all specified test cases
- [x] Tests use mocks for OpenAI API calls (no real API calls in tests)
- [x] Tests use mocks or fixtures for database access
- [x] All tests are runnable via `pytest`

---

## Phase Summary

| Phase | Name | Creates | Modifies | Depends On | Status |
|---|---|---|---|---|---|
| 1 | Infrastructure & Dependencies | `backend/Dockerfile.postgres` | `docker-compose.yml`, `init-db.sql`, `requirements.txt`, `.env.example` | — | COMPLETE |
| 2 | Configuration | — | `app/config.py` | — | COMPLETE |
| 3 | Database Migration | `alembic/versions/003_metadata_search.py` | — | Phase 1 | COMPLETE |
| 4 | ORM Models | — | `app/db/models.py` | Phase 1, 3 | COMPLETE |
| 5 | Embeddings Module | `app/search/__init__.py`, `app/search/embeddings.py` | — | Phase 2 | COMPLETE |
| 6 | Indexer Module | `app/search/indexer.py` | — | Phase 4, 5 | COMPLETE |
| 7 | Search Module | `app/search/search.py` | — | Phase 2, 4, 5 | COMPLETE |
| 8 | Discovery Module | `app/search/discovery.py` | — | Phase 2, 4 | COMPLETE |
| 9 | Celery Task & Wiring | `app/search/tasks.py` | `app/celery_app.py` | Phase 6 | COMPLETE |
| 10 | API Router & Wiring | `app/api/v1/search.py` | `app/main.py` | Phase 7, 8, 9 | COMPLETE |
| 11 | Feature 1 Integration | — | `app/ingestion/tasks.py` | Phase 9 | COMPLETE |
| 12 | Tests | `tests/test_embeddings.py`, `tests/test_search.py`, `tests/test_discovery.py` | — | All | COMPLETE |
