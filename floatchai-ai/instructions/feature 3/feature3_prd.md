# FloatChat — Feature 3: Metadata Search Engine
## Product Requirements Document (PRD)

**Feature Name:** Metadata Search Engine
**Version:** 1.0
**Status:** Ready for Development
**Owner:** Backend / AI Engineering
**Depends On:** Feature 1 (Data Ingestion Pipeline) — datasets and summaries must exist before indexing. Feature 2 (Ocean Data Database) — `ocean_regions` table and `floats` table must exist for spatial and type-based discovery.

---

## 1. Purpose & Background

### 1.1 What Problem Does This Solve?
Before a researcher can query ocean data, they need to know what data exists. Without a discovery layer, users face a blank chat box with no idea what datasets are available, what time periods are covered, which ocean regions have data, or which variables were measured.

The Metadata Search Engine solves the cold-start problem. It gives researchers a way to explore and discover available datasets using natural language — before committing to a full data query. Think of it as the catalogue that sits in front of the database.

### 1.2 What This Feature Is
A semantic search and discovery layer that:
- Embeds dataset summaries and float metadata into vector representations
- Allows researchers to find relevant datasets by describing what they are looking for in plain English
- Supports structured filters (region, date, variable, float type) layered on top of semantic search
- Provides fuzzy region name matching so "Bengal Bay" resolves to "Bay of Bengal"
- Indexes data automatically whenever new datasets are ingested via Feature 1

### 1.3 What This Feature Is Not
- It is not the NL Query Engine (Feature 4) — it does not query measurement data or generate SQL
- It is not a full-text search engine over measurements
- It does not replace the database — it is a discovery layer that sits in front of it
- It does not handle visualization or export

### 1.4 Relationship to Other Features
- Feature 1 triggers indexing after each successful ingestion job
- Feature 2 provides the `ocean_regions` table used for spatial region resolution
- Feature 4 (NL Query Engine) uses the search results to understand which datasets are relevant to a user's query
- Feature 5 (Chat Interface) displays dataset summaries returned by this feature before the user runs a query
- Feature 9 (Guided Query Assistant) uses float discovery results to suggest example queries

---

## 2. Goals & Success Criteria

### 2.1 Goals
- Allow researchers to find relevant datasets without knowing exact dataset names or IDs
- Return results in under 500ms for semantic search queries
- Support natural language descriptions like "Indian Ocean temperature data from last year"
- Index new datasets within 60 seconds of ingestion completing
- Enable float discovery by region, type, and variable availability

### 2.2 Success Criteria

| Criterion | Target |
|---|---|
| Semantic search latency (p95) | < 500ms |
| Indexing latency after ingestion | < 60 seconds |
| Relevant result in top 3 for well-formed queries | ≥ 90% of test cases |
| Region name fuzzy match accuracy | ≥ 95% for known aliases |
| Float discovery query latency | < 300ms |
| Re-indexing on dataset update | Zero stale results after 60s |

---

## 3. User Stories

### 3.1 Researcher
- **US-01:** As a researcher, I want to search for datasets by describing what I need in plain English (e.g., "BGC float data near India from 2022"), so that I can find relevant data without knowing exact dataset names.
- **US-02:** As a researcher, I want to see a plain-English summary for each dataset result, so that I can quickly judge relevance without opening the dataset.
- **US-03:** As a researcher, I want to search for floats by region name even if I use an informal name (e.g., "Bengal Bay" instead of "Bay of Bengal"), so that I don't need to know exact naming conventions.
- **US-04:** As a researcher, I want to filter search results by variable type (temperature, salinity, oxygen, etc.), so that I only see datasets containing the data I need.
- **US-05:** As a researcher, I want to filter results by date range, so that I can find data from a specific time period.

### 3.2 NL Query Engine (Internal Consumer)
- **US-06:** As the NL Query Engine, I need to call the metadata search endpoint with a user's query to retrieve the most relevant dataset IDs before generating SQL, so that the SQL query targets the right data.

### 3.3 Data Manager (Admin)
- **US-07:** As a data manager, I want newly ingested datasets to appear in search results automatically, so that I don't have to manually trigger re-indexing.
- **US-08:** As a data manager, I want to manually re-index a specific dataset if its summary was updated, so that search results stay accurate after metadata edits.

---

## 4. Functional Requirements

### 4.1 Vector Store & Embedding

**FR-01 — Vector Store Selection**
Use `pgvector` as the vector store. It runs as a PostgreSQL extension — no additional service is required. This keeps the infrastructure simple: one database handles both relational data and vector embeddings. Do not use Qdrant, Chroma, or FAISS for v1.

**FR-02 — pgvector Extension**
Enable the `pgvector` extension in PostgreSQL via Alembic migration. Add to the same migration that creates the embedding tables. The extension name is `vector`.

**FR-03 — Embedding Model**
Use OpenAI `text-embedding-3-small` for all embeddings. This model produces 1536-dimensional vectors. Use the same `OPENAI_API_KEY` already present in settings from Feature 1.

**FR-04 — What Gets Embedded**
Embed the following text for each dataset:
- The dataset's `summary_text` (LLM-generated in Feature 1)
- A structured descriptor string composed of: dataset name + variable list + date range + float count + region description

These two are concatenated with a newline separator before embedding. The combined text is what gets embedded — not each piece separately.

**FR-05 — Float Embeddings**
Embed the following text for each float record:
- A descriptor string: float type + platform number + deployment region (derived from lat/lon) + variables available + active date range

Float embeddings are updated whenever new profiles are ingested for that float.

**FR-06 — Embedding Storage Table: `dataset_embeddings`**
One row per dataset. Columns: `embedding_id` (PK), `dataset_id` (FK → datasets, unique), `embedding_text` (the text that was embedded, stored for debugging), `embedding` (pgvector `vector(1536)` column), `created_at`, `updated_at`. Index: IVFFlat or HNSW index on the `embedding` column for fast similarity search.

**FR-07 — Embedding Storage Table: `float_embeddings`**
One row per float. Columns: `embedding_id` (PK), `float_id` (FK → floats, unique), `embedding_text`, `embedding` (pgvector `vector(1536)` column), `created_at`, `updated_at`. Same vector index as dataset embeddings.

**FR-08 — Vector Index Type**
Use HNSW (Hierarchical Navigable Small World) index on both embedding columns. HNSW gives better query performance than IVFFlat at the expected data scale. Index parameters: `m=16`, `ef_construction=64`.

### 4.2 Indexing Pipeline

**FR-09 — Post-Ingestion Trigger**
After each successful ingestion job completes in Feature 1's Celery task (`ingest_file_task`), a new Celery task (`index_dataset_task`) must be enqueued. This task generates and stores embeddings for the newly ingested dataset and all floats updated in that ingestion job. The ingestion task does not wait for indexing to complete — it fires and forgets.

**FR-10 — `index_dataset_task` Celery Task**
This task accepts `dataset_id` as input. It must:
1. Fetch the dataset record from the database
2. Build the embedding text (summary + descriptor string)
3. Call the OpenAI embedding API
4. Upsert the result into `dataset_embeddings`
5. Fetch all floats updated in this dataset's ingestion job
6. For each float, build the float descriptor text, call the embedding API, upsert into `float_embeddings`
7. Log completion with dataset_id, float count, and total time

**FR-11 — Manual Re-index Endpoint**
Expose `POST /api/v1/search/reindex/{dataset_id}` for admins to manually trigger re-indexing of a specific dataset. Auth: admin JWT required. This enqueues `index_dataset_task` for the given dataset ID. Returns immediately with a job acknowledgement — does not wait for completion.

**FR-12 — Batch Embedding Calls**
When indexing multiple floats for a dataset, call the OpenAI embedding API in batches of up to 100 texts per API call (OpenAI supports batch embedding). Do not call the API once per float in a loop — this is too slow and wasteful.

**FR-13 — Embedding Failure Handling**
If the OpenAI API call fails during indexing, retry up to 3 times with exponential backoff. If all retries fail, log the error and mark the dataset/float as `embedding_failed` in a status field on the embedding table. Do not crash the Celery task — the ingestion data is already safely stored. Indexing failure is recoverable.

### 4.3 Semantic Search

**FR-14 — `search_datasets(query, filters)` Function**
Core search function. Accepts:
- `query` (str) — plain English description
- `filters` (optional dict) with keys: `variable`, `float_type`, `date_from`, `date_to`, `region_name`
- `limit` (int, default 10, max 50)

Steps:
1. Embed the query text using `text-embedding-3-small`
2. Run cosine similarity search against `dataset_embeddings` using pgvector's `<=>` operator
3. Apply any structured filters as SQL WHERE clauses on joined `datasets` table
4. Return ranked list of datasets with relevance scores

**FR-15 — `search_floats(query, filters)` Function**
Same structure as `search_datasets` but searches `float_embeddings` and joins `floats` table for filtering.

**FR-16 — Relevance Score**
Include a relevance score (0.0 to 1.0) in every search result. Score is derived from cosine similarity: `score = 1 - cosine_distance`. Higher is more relevant. Include score in API response.

**FR-17 — Hybrid Scoring**
Combine semantic similarity score with two boosting factors:
- **Recency boost:** datasets ingested in the last 90 days receive a +0.05 score bonus
- **Region match boost:** if the query contains a region name that matches `ocean_regions.region_name`, datasets whose bbox intersects that region receive a +0.10 score bonus

Final score = cosine score + recency boost + region match boost, capped at 1.0.

**FR-18 — Minimum Similarity Threshold**
Do not return results with cosine similarity below 0.3. If all results are below this threshold, return an empty list rather than irrelevant results. This prevents garbage results for queries that have no relevant datasets.

### 4.4 Float Discovery

**FR-19 — Float Discovery by Region**
`discover_floats_by_region(region_name, float_type, db)` — resolves region name to polygon via `ocean_regions` table (using the same fuzzy matching as FR-21), then returns all floats whose latest position (from `mv_float_latest_position` materialized view) falls within the polygon. Returns float metadata: platform number, float type, last position, last seen date, variables available.

**FR-20 — Float Discovery by Variable**
`discover_floats_by_variable(variable_name, db)` — returns floats that have at least one measurement for the given variable. Uses the `floats.float_type` and joins to the measurements table to check variable availability. Supported variables: temperature, salinity, dissolved_oxygen, chlorophyll, nitrate, ph.

**FR-21 — Region Name Fuzzy Matching**
Before resolving a region name to a polygon, apply fuzzy matching against all `region_name` values in the `ocean_regions` table. Use the `pg_trgm` extension (already enabled in Feature 2 migration) with `similarity()` function. If similarity score ≥ 0.4, treat as a match and use the closest match. If no match above threshold, raise a descriptive error: `"Region '{name}' not found. Did you mean: {closest_matches}?"`.

### 4.5 Dataset Summary Display

**FR-22 — `get_dataset_summary(dataset_id, db)` Function**
Returns a rich summary object for a single dataset including: name, summary_text, date_range_start, date_range_end, float_count, profile_count, variable_list, bbox as GeoJSON, is_active. Used by the chat interface to display dataset context before a user runs a query.

**FR-23 — `get_all_summaries(db)` Function**
Returns lightweight summary cards for all active datasets, ordered by ingestion_date descending. Each card includes: dataset_id, name, summary_text (truncated to 300 characters), float_count, date_range_start, date_range_end, variable_list. Used by the chat interface home screen to display available data.

### 4.6 Search API Endpoints

**FR-24 — Dataset Search Endpoint**
```
GET /api/v1/search/datasets?q={query}&variable={var}&float_type={type}&date_from={date}&date_to={date}&region={name}&limit={n}
```
Returns ranked list of matching datasets with relevance scores and summaries. All filter params are optional.

**FR-25 — Float Search Endpoint**
```
GET /api/v1/search/floats?q={query}&float_type={type}&region={name}&limit={n}
```
Returns matching floats with relevance scores and metadata.

**FR-26 — Float Discovery by Region Endpoint**
```
GET /api/v1/search/floats/by-region?region={name}&float_type={type}
```
Returns all floats in the named region. Not semantic — pure spatial filter.

**FR-27 — Dataset Summary Endpoint**
```
GET /api/v1/search/datasets/{dataset_id}/summary
```
Returns full summary for a single dataset.

**FR-28 — All Summaries Endpoint**
```
GET /api/v1/search/datasets/summaries
```
Returns lightweight summary cards for all active datasets.

**FR-29 — Manual Re-index Endpoint**
```
POST /api/v1/search/reindex/{dataset_id}
```
Admin only. Triggers re-indexing for a dataset. Returns acknowledgement.

---

## 5. Non-Functional Requirements

### 5.1 Performance
- Semantic search must return results in under 500ms at 10,000 indexed datasets
- Float discovery queries must return in under 300ms
- Embedding generation for a new dataset must complete within 30 seconds
- Batch float embedding (up to 500 floats per dataset) must complete within 60 seconds

### 5.2 Reliability
- Indexing failure must never cause ingestion failure — they are decoupled via Celery
- If pgvector is unavailable, search endpoints must return a 503 with a clear error — they must not return empty results silently
- Re-indexing must be idempotent — running it twice must not create duplicate embeddings

### 5.3 Scalability
- pgvector HNSW index must be used for all similarity searches — never compute similarity via full table scan
- Embedding API calls must always be batched — never call OpenAI once per item in a loop
- The `dataset_embeddings` table must support up to 100,000 datasets without index degradation

### 5.4 Security
- The manual re-index endpoint requires admin JWT — same auth as Feature 1 ingestion endpoints
- OpenAI API key must never appear in logs or error messages
- Embedding texts stored in the database must not contain raw file paths or internal system details

---

## 6. Database Schema

### 6.1 New Tables

**`dataset_embeddings`**
```
embedding_id   SERIAL PRIMARY KEY
dataset_id     INTEGER UNIQUE NOT NULL REFERENCES datasets(dataset_id)
embedding_text TEXT NOT NULL
embedding      vector(1536) NOT NULL
status         VARCHAR(20) DEFAULT 'indexed'   -- indexed | embedding_failed
created_at     TIMESTAMPTZ DEFAULT NOW()
updated_at     TIMESTAMPTZ DEFAULT NOW()
```
HNSW index on `embedding` column with `m=16`, `ef_construction=64`, using cosine distance operator (`vector_cosine_ops`).

**`float_embeddings`**
```
embedding_id   SERIAL PRIMARY KEY
float_id       INTEGER UNIQUE NOT NULL REFERENCES floats(float_id)
embedding_text TEXT NOT NULL
embedding      vector(1536) NOT NULL
status         VARCHAR(20) DEFAULT 'indexed'   -- indexed | embedding_failed
created_at     TIMESTAMPTZ DEFAULT NOW()
updated_at     TIMESTAMPTZ DEFAULT NOW()
```
Same HNSW index as dataset_embeddings.

### 6.2 Migration
Migration `003_metadata_search.py`. Down revision must be `"002"`. Steps:
1. Enable `vector` extension via `CREATE EXTENSION IF NOT EXISTS vector`
2. Create `dataset_embeddings` table
3. Create `float_embeddings` table
4. Create HNSW indexes on both embedding columns
5. `downgrade()` must drop both tables and the vector extension

---

## 7. New Configuration Settings

Add to `Settings` class in `config.py`:
- `EMBEDDING_MODEL` — default `text-embedding-3-small`
- `EMBEDDING_DIMENSIONS` — default `1536`
- `EMBEDDING_BATCH_SIZE` — default `100` (max texts per OpenAI batch call)
- `SEARCH_SIMILARITY_THRESHOLD` — default `0.3` (minimum cosine similarity to return)
- `SEARCH_DEFAULT_LIMIT` — default `10`
- `SEARCH_MAX_LIMIT` — default `50`
- `RECENCY_BOOST_DAYS` — default `90`
- `RECENCY_BOOST_VALUE` — default `0.05`
- `REGION_MATCH_BOOST_VALUE` — default `0.10`
- `FUZZY_MATCH_THRESHOLD` — default `0.4`

---

## 8. File Structure

```
floatchat/
├── backend/
│   ├── app/
│   │   ├── search/
│   │   │   ├── __init__.py
│   │   │   ├── embeddings.py       # Embedding generation + OpenAI calls
│   │   │   ├── indexer.py          # Indexing logic (build text, upsert)
│   │   │   ├── search.py           # search_datasets, search_floats functions
│   │   │   ├── discovery.py        # Float discovery, region lookup, fuzzy match
│   │   │   └── tasks.py            # Celery task: index_dataset_task
│   │   └── api/
│   │       └── v1/
│   │           └── search.py       # FastAPI router for all search endpoints
│   ├── alembic/
│   │   └── versions/
│   │       └── 003_metadata_search.py
│   └── tests/
│       ├── test_embeddings.py
│       ├── test_search.py
│       └── test_discovery.py
```

---

## 9. Testing Requirements

### 9.1 Embedding Tests (`test_embeddings.py`)
- Test that embedding text is built correctly from dataset fields
- Test that float descriptor text is built correctly
- Test that OpenAI API call returns a vector of length 1536
- Test that batch embedding processes 100 items in one API call
- Test that embedding failure sets status to `embedding_failed` and does not raise

### 9.2 Search Tests (`test_search.py`)
- Test that `search_datasets` returns results ordered by relevance score descending
- Test that results below the similarity threshold are excluded
- Test that `variable` filter excludes datasets without the requested variable
- Test that `date_from` / `date_to` filters work correctly
- Test that recency boost increases score for recent datasets
- Test that region match boost increases score for matching region
- Test that `limit` param caps results correctly

### 9.3 Discovery Tests (`test_discovery.py`)
- Test `discover_floats_by_region` returns only floats within the named region polygon
- Test fuzzy region matching: "Bengal Bay" resolves to "Bay of Bengal"
- Test fuzzy matching raises descriptive error for completely unrecognized names
- Test `discover_floats_by_variable` returns only floats with non-null measurements for the variable
- Test `get_all_summaries` returns only active datasets

### 9.4 API Tests
- Test `GET /api/v1/search/datasets?q=temperature+Indian+Ocean` returns ranked results
- Test `GET /api/v1/search/floats/by-region?region=Arabian+Sea` returns correct floats
- Test `POST /api/v1/search/reindex/{id}` returns 401 without admin JWT
- Test search endpoint returns 503 gracefully if pgvector is unavailable

---

## 10. Dependencies & Prerequisites

| Dependency | Reason | Must Be Ready Before |
|---|---|---|
| Feature 1 complete | Datasets and summaries must exist to index | Day 1 |
| Feature 2 complete | `ocean_regions`, `floats`, materialized views must exist | Day 1 |
| pgvector PostgreSQL extension | Vector storage | Before migration 003 |
| OpenAI API key | Embedding generation | Before any indexing |
| Celery worker running | Async indexing tasks | Before integration testing |
| `pg_trgm` extension | Fuzzy region name matching (enabled in Feature 2) | Already done |

---

## 11. Out of Scope for v1.0

- Elasticsearch or OpenSearch integration (pgvector is sufficient for v1)
- Cross-dataset semantic deduplication
- User-specific search personalization
- Embedding model fine-tuning on oceanographic vocabulary
- Search result feedback loop (thumbs up/down)
- Full-text search on raw measurement values

---

## 12. Open Questions

| # | Question | Owner | Due |
|---|---|---|---|
| Q1 | Should float embeddings be updated incrementally (only changed floats) or fully re-generated per ingestion job? Full re-gen is simpler but slower for large datasets. | Backend | Before Phase dev start |
| Q2 | Should the search API be accessible without authentication (public read), or require a user JWT? The PRD scope marks auth as out of scope for initial release. | Product | Before API implementation |
| Q3 | What is the expected number of datasets at launch? This determines whether IVFFlat or HNSW is more appropriate (HNSW is assumed here but IVFFlat performs better below ~1M vectors). | Data Team | Before migration 003 |
| Q4 | Should `get_all_summaries` be paginated, or is a full list acceptable at launch given the small expected dataset count? | Product | Before API implementation |
