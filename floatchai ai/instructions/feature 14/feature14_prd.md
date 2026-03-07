# FloatChat — Feature 14: RAG Pipeline
## Product Requirements Document (PRD)

**Feature Name:** RAG Pipeline
**Version:** 1.0
**Status:** ✅ Implemented (2026-03-07)
**Depends On:** Feature 4 (NL Query Engine — `pipeline.py` is the integration point), Feature 5 (Chat Interface — chat router triggers the store call), Feature 13 (Auth — `user_id` is the tenant boundary), Feature 3 (Metadata Search — pgvector and `embed_texts()` infrastructure already in place)
**Blocks:** Feature 9 (Guided Query Assistant — benefits from `query_history` for autocomplete), Feature 15 (Anomaly Detection — `user_id` scoping pattern established here)

---

## 1. Purpose & Background

### 1.1 What Problem Does This Solve?
Feature 4's NL query engine uses a static schema prompt with fixed few-shot examples. This works well for common query patterns but degrades for complex, domain-specific, or region-specific queries that don't match any static example. Every user gets the same starting context regardless of what has worked before.

Feature 14 turns FloatChat into a learning system. Every time a query succeeds — generates valid SQL and returns results — that query-SQL pair is embedded and stored. The next time a similar question is asked, the most relevant past successes are retrieved and injected into the prompt as dynamic few-shot examples. The system gets measurably smarter with each successful query, and each organisation's FloatChat improves based on their own usage patterns.

### 1.2 What This Feature Is
A retrieval-augmented generation layer consisting of:
- A new `query_history` database table that stores successful NL query–SQL pairs with vector embeddings
- A new `app/query/rag.py` module with three functions: store, retrieve, and build context
- Two additive changes to existing files: one retrieval call near the top of `nl_to_sql()` in `pipeline.py`, and one fire-and-forget store call in the chat router after successful execution
- An Alembic migration creating the `query_history` table and its HNSW index
- A config flag (`ENABLE_RAG_RETRIEVAL`) to gate the feature per deployment tier

### 1.3 What This Feature Is Not
- It does not re-execute queries — it only stores and retrieves query-SQL pairs
- It does not replace the static few-shot examples in `schema_prompt.py` — it adds dynamic examples alongside them
- It does not implement cross-user or cross-organisation retrieval — tenant isolation is absolute
- It does not implement a scientific glossary or dataset relevance pre-filter in v1 — those are v2 enhancements
- It does not add any frontend UI — the improvement is invisible to the researcher (queries just get better)
- It does not require any researcher configuration

### 1.4 Why Build It Now
The infrastructure prerequisites are all in place: pgvector from Feature 3, `embed_texts()` from Feature 3, `user_id` from Feature 13, and a working query pipeline from Feature 4. More importantly, timing is right — the product is approaching production and real queries will start flowing. RAG is most valuable when built before the query corpus grows, so that every query from day one contributes to and benefits from the learning loop.

### 1.5 B2B SaaS Significance
Tenant-isolated RAG creates a compounding switching cost. An organisation's `query_history` encodes months of successful oceanographic queries against their specific datasets. Migrating to a competitor means starting from zero — losing every learned example. This is the mechanism that makes FloatChat stickier over time and justifies Pro-tier pricing.

---

## 2. Goals & Success Criteria

### 2.1 Goals
- Improve NL-to-SQL accuracy for repeat and similar query patterns
- Create a self-improving system where each successful query benefits future queries
- Maintain cold-start compatibility — the system behaves identically to pre-RAG when `query_history` is empty
- Never degrade query response time or SSE stream reliability due to RAG operations

### 2.2 Success Criteria

| Criterion | Target |
|---|---|
| `store_successful_query()` latency impact on SSE stream | Zero — fire-and-forget, never blocks |
| `retrieve_similar_queries()` latency (p95) | < 200ms including embedding round-trip |
| Cold start behaviour (empty `query_history`) | Identical to pre-RAG — no errors, no empty prompt sections |
| Retrieval failure behaviour | Silent fallback to static prompt — no user-visible error |
| Tenant isolation | 100% — zero cross-user results in any retrieval query |
| `query_history` rows stored per successful query | Exactly 1 |
| Duplicate suppression | Identical `nl_query` + `user_id` pairs within 24 hours stored only once |

---

## 3. User Stories

### 3.1 Researcher (Implicit — feature is invisible)
- **US-01:** As a researcher, I want my second query about Arabian Sea temperature profiles to return better SQL than my first, because FloatChat has learned from what worked before.
- **US-02:** As a researcher using FloatChat for months, I want complex queries about unusual depth ranges and multi-variable conditions to succeed more reliably, because the system has accumulated relevant examples from my own usage.
- **US-03:** As a researcher, I want my organisation's query history to be private — another organisation's usage patterns should not influence my results.

### 3.2 Admin
- **US-04:** As an admin, I want to be able to disable the RAG retrieval layer globally via a config flag, so that I can debug query accuracy issues in isolation from the RAG context.
- **US-05:** As an admin, I want to understand how many queries are in the history corpus for a given user, so that I can monitor RAG corpus growth.

---

## 4. Functional Requirements

### 4.1 Database: `query_history` Table

**FR-01 — Table Definition**
Create a `query_history` table with the following columns:
- `query_id` — UUID primary key, server-generated via `gen_random_uuid()`
- `nl_query` — TEXT, not null — the original natural language question as typed by the researcher
- `generated_sql` — TEXT, not null — the SQL that was successfully executed
- `embedding` — `vector(1536)`, not null — the OpenAI `text-embedding-3-small` embedding of `nl_query`
- `row_count` — INTEGER, not null — number of rows returned by the successful execution
- `user_id` — UUID, not null, foreign key to `users.user_id` with `ON DELETE CASCADE`
- `session_id` — UUID, nullable, foreign key to `chat_sessions.session_id` with `ON DELETE SET NULL` — nullable because sessions can be deleted while history is retained
- `provider` — VARCHAR(50), not null — the LLM provider used (e.g., `deepseek`, `openai`)
- `model` — VARCHAR(100), not null — the specific model used (e.g., `deepseek-reasoner`)
- `created_at` — TIMESTAMP WITH TIME ZONE, not null, default `now()`

**FR-02 — Indexes**
- HNSW index on `embedding` column using `vector_cosine_ops` with `m=16`, `ef_construction=64` — must be created with raw SQL via `op.execute()` following the same pattern as Feature 3's migration
- B-tree index on `user_id` — for fast tenant-scoped retrieval filtering
- B-tree index on `created_at` — for time-ordered queries and deduplication window checks

**FR-03 — Deduplication Constraint**
No formal unique constraint on `(nl_query, user_id)` — natural language phrasing varies enough that exact deduplication is not reliable. Instead, `store_successful_query()` performs a soft deduplication check: if an identical `nl_query` string was stored for the same `user_id` within the last 24 hours, skip the insert. This prevents rapid re-runs of the same query from inflating the corpus.

**FR-04 — Migration**
Alembic migration file `006_rag_pipeline.py` with `down_revision = "005"`. Down migration drops the `query_history` table and its indexes cleanly.

### 4.2 Backend: `app/query/rag.py` Module

**FR-05 — `store_successful_query()`**
Stores a successful NL query execution in `query_history`.

Parameters: `nl_query` (str), `generated_sql` (str), `row_count` (int), `user_id` (UUID), `session_id` (UUID or None), `provider` (str), `model` (str), `db` (read-write Session).

Processing:
1. Check deduplication window: query `query_history` for any row where `nl_query = :nl_query AND user_id = :user_id AND created_at > now() - interval '24 hours'`. If found, log at DEBUG level and return without inserting.
2. Call `embed_texts([nl_query])` from `app/search/embeddings.py` to generate the embedding. This is the only permitted way to call the embedding API — never call the OpenAI client directly from `rag.py`.
3. Insert a new `query_history` row with all fields.
4. Commit the session.
5. On any exception: log at WARNING level via structlog with the error details. Do not re-raise — the caller must never receive an exception from this function.

This function must never raise. All exceptions are caught, logged, and silently dropped. The caller (chat router) is fire-and-forget.

**FR-06 — `retrieve_similar_queries()`**
Retrieves the most semantically similar past successful queries for the current user.

Parameters: `nl_query` (str), `user_id` (UUID), `db` (read-only Session), `limit` (int, default from `settings.RAG_RETRIEVAL_LIMIT`).

Processing:
1. Call `embed_texts([nl_query])` from `app/search/embeddings.py` to embed the current query.
2. Query `query_history` using pgvector cosine similarity (`<=>`) filtered strictly by `user_id = :user_id`.
3. Order by cosine distance ascending (most similar first).
4. Apply `LIMIT :limit`.
5. Return a list of dicts, each containing `nl_query`, `generated_sql`, and `row_count`.
6. If the table has zero rows for this user, return an empty list — never raise `NoResultFound`.
7. On any exception: log at WARNING level, return an empty list. Never re-raise.

The similarity threshold: only return results where cosine distance is below `settings.RAG_SIMILARITY_THRESHOLD` (default `0.4`). Results above this threshold (dissimilar queries) are not useful as few-shot examples and must be excluded.

**FR-07 — `build_rag_context()`**
Formats retrieved query-SQL pairs as a prompt string to inject into the LLM system message.

Parameters: `similar_queries` (list of dicts from `retrieve_similar_queries()`).

Processing:
1. If `similar_queries` is empty, return an empty string.
2. Format each retrieved pair as a clearly labelled example block. The format must be compatible with the existing static few-shot example format in `schema_prompt.py` — use consistent labelling so the LLM understands these are real working examples from the user's history.
3. Prepend a section header that distinguishes these from the static examples (e.g., "The following are real examples from your query history that succeeded against this database:").
4. Return the formatted string.

The returned string is injected into the `nl_to_sql()` system prompt immediately before the static few-shot examples, not after. Retrieved examples are more specific and more relevant than static examples — they should appear closer to the top of the context.

### 4.3 Backend: `pipeline.py` Integration

**FR-08 — Retrieval Call in `nl_to_sql()`**
Add one retrieval call near the start of `nl_to_sql()`, after the NL query text is available but before the system prompt is assembled.

Behaviour:
- If `settings.ENABLE_RAG_RETRIEVAL` is `False`: skip retrieval entirely and proceed with static prompt only
- If `user_id` is not provided: skip retrieval and proceed with static prompt only
- If retrieval succeeds and returns results: call `build_rag_context()` and inject the result into the system prompt
- If retrieval returns an empty list: proceed with static prompt only — no change in behaviour
- If retrieval raises or times out: catch the exception, log at WARNING, proceed with static prompt only

The static few-shot examples in `SCHEMA_PROMPT` must never be removed or replaced. RAG context is additive — it extends the prompt, never replacing existing content.

**FR-09 — `nl_to_sql()` Signature Update**
To support RAG retrieval, `nl_to_sql()` needs access to `user_id` and a database session. If these are not already parameters:
- Add `user_id: UUID | None = None` as an optional parameter
- Add `db: Session | None = None` as an optional parameter
- Both default to `None` — when either is absent, RAG retrieval is silently skipped
- All existing call sites must be updated to pass these values when available

The benchmark endpoint (`POST /api/v1/query/benchmark`) does not have a user context — it calls `nl_to_sql()` without `user_id`. This is acceptable: RAG retrieval is skipped for benchmark calls and the benchmark behaviour is unchanged.

### 4.4 Backend: `chat.py` Integration

**FR-10 — Store Call After Successful Execution**
Add one fire-and-forget store call in the chat router's SSE stream handler, immediately after the `results` event is emitted and the execution is confirmed successful (row count confirmed non-zero).

The call must be fire-and-forget:
- In an async context: wrap in `asyncio.create_task()` so the SSE stream continues without waiting
- In a sync context: wrap in a background thread via `asyncio.get_event_loop().run_in_executor()`
- The task must catch all exceptions internally — any failure in storage must not surface to the SSE stream

Values to pass: `nl_query` from the current message, `generated_sql` from the pipeline result, `row_count` from the execution result, `user_id` from `current_user.user_id`, `session_id` from the current session, `provider` and `model` from the pipeline result.

Do not store queries where `row_count == 0`. An empty result is not a successful query from a RAG perspective — it provides no useful signal for future retrieval.

### 4.5 Configuration

**FR-11 — New Config Settings**
Add to `Settings` class in `backend/app/config.py`:
- `ENABLE_RAG_RETRIEVAL` — bool, default `True` — master switch for RAG retrieval. Set to `False` to use static prompt only (Basic tier or debugging)
- `RAG_RETRIEVAL_LIMIT` — int, default `5` — number of similar queries to retrieve per request
- `RAG_SIMILARITY_THRESHOLD` — float, default `0.4` — maximum cosine distance for a retrieved example to be included (lower = more similar)
- `RAG_DEDUP_WINDOW_HOURS` — int, default `24` — hours within which identical queries from the same user are deduplicated

---

## 5. Non-Functional Requirements

### 5.1 Performance
- `store_successful_query()` must never add latency to the SSE stream — it is fire-and-forget
- `retrieve_similar_queries()` including the embedding round-trip must complete in under 200ms at p95
- If embedding latency exceeds 300ms, the retrieval call must time out and fall back to the static prompt rather than blocking the query pipeline
- The HNSW index must ensure sub-10ms vector search latency for up to 1 million rows per user

### 5.2 Correctness
- Retrieved examples must always come from the same `user_id` as the requester — cross-tenant retrieval is a data leak and must be architecturally impossible, not just policy
- Only queries with `row_count > 0` are stored — empty results are never used as few-shot examples
- The embedding used for retrieval must be generated from the same model and dimensions as stored embeddings (`text-embedding-3-small`, 1536 dimensions)

### 5.3 Reliability
- Any failure in the RAG path (embedding API down, database error, timeout) must result in graceful fallback to the static prompt
- The system must be fully functional with an empty `query_history` table — cold start is a first-class case, not an edge case
- `store_successful_query()` failures must be logged but must never cause query errors, session errors, or SSE stream failures

### 5.4 Tenant Isolation
- Every retrieval SQL query must include `WHERE user_id = :user_id` as a non-negotiable filter
- The `user_id` filter must be applied at the database layer — not post-filtered in Python after retrieval
- No aggregation, averaging, or cross-user similarity computation is permitted in v1

---

## 6. File Structure

```
floatchat/
└── backend/
    ├── alembic/
    │   └── versions/
    │       └── 006_rag_pipeline.py         # New migration
    ├── app/
    │   ├── config.py                       # 4 new settings added
    │   ├── db/
    │   │   └── models.py                   # QueryHistory ORM model added
    │   └── query/
    │       ├── rag.py                      # New module: store, retrieve, build_context
    │       └── pipeline.py                 # 2 additive changes: retrieve call + signature update
    └── api/
        └── v1/
            └── chat.py                     # 1 additive change: fire-and-forget store call
```

Files to modify (additive only):
- `backend/app/config.py` — 4 new settings
- `backend/app/db/models.py` — `QueryHistory` ORM model
- `backend/app/query/pipeline.py` — retrieval call in `nl_to_sql()`, optional `user_id` and `db` parameters
- `backend/app/api/v1/chat.py` — fire-and-forget store call after successful execution

---

## 7. Dependencies

All required infrastructure is already installed and in use:

| Dependency | Source | Status |
|---|---|---|
| pgvector PostgreSQL extension | Feature 3 migration | ✅ Enabled |
| `pgvector.sqlalchemy` Vector type | Feature 3 models | ✅ In use |
| `embed_texts()` function | `app/search/embeddings.py` | ✅ Built |
| `text-embedding-3-small` model | Feature 3 config | ✅ Configured |
| `users.user_id` UUID | Feature 13 | ✅ Built |
| SQLAlchemy read-write session | `app/db/session.py` | ✅ Built |
| SQLAlchemy read-only session | `app/db/session.py` | ✅ Built |
| structlog | All features | ✅ In use |

No new packages are required for Feature 14.

---

## 8. Testing Requirements

### 8.1 Backend Tests (`test_rag.py`)

**Migration tests:**
- `query_history` table exists after `alembic upgrade head`
- HNSW index on `embedding` column exists
- B-tree index on `user_id` exists
- Down migration drops table and indexes cleanly

**`store_successful_query()` tests:**
- Stores a row successfully with all fields populated
- Deduplication: second identical `nl_query` + `user_id` within 24 hours is not stored
- Deduplication: same `nl_query` after 24 hours is stored (new entry)
- Different `user_id` with same `nl_query` stores separately (no cross-user dedup)
- Does not raise when `embed_texts()` raises (logs and returns silently)
- Does not raise on database error (logs and returns silently)
- Does not store when `row_count == 0`

**`retrieve_similar_queries()` tests:**
- Returns empty list when `query_history` has no rows for this user
- Returns empty list when `query_history` has rows for a different user only (tenant isolation)
- Returns results ordered by cosine similarity (most similar first)
- Respects `limit` parameter
- Excludes results above `RAG_SIMILARITY_THRESHOLD`
- Returns empty list when `embed_texts()` raises (logs and returns silently)
- Returns empty list on database error (logs and returns silently)
- Never returns rows belonging to a different `user_id`

**`build_rag_context()` tests:**
- Returns empty string when `similar_queries` is empty
- Returns formatted string with section header when results are present
- Each result block contains `nl_query` and `generated_sql`
- Output is a valid string (no None, no exception)

**Integration tests:**
- `nl_to_sql()` with `ENABLE_RAG_RETRIEVAL=False` uses static prompt only
- `nl_to_sql()` with `user_id=None` uses static prompt only
- `nl_to_sql()` with populated history retrieves and injects context
- `nl_to_sql()` with empty history behaves identically to pre-RAG
- `nl_to_sql()` when retrieval fails behaves identically to pre-RAG
- Chat SSE stream completes successfully even when store call fails
- Static few-shot examples in `SCHEMA_PROMPT` are preserved in all paths

---

## 9. Migration Number

This is migration `006`. The existing sequence:
- `001` — Feature 1 initial schema
- `002` — Feature 2 ocean database
- `003` — Feature 3 pgvector and embeddings
- `004` — Feature 5 chat interface
- `005` — Feature 13 auth

Migration `006_rag_pipeline.py` must use `down_revision = "005"`. Confirm the exact revision ID in `005_auth.py` before writing the migration.

---

## 10. Forward Compatibility Notes

Feature 9 (Guided Query Assistant) will read from `query_history` to power autocomplete suggestions — showing researchers queries similar to what they are typing. The table design supports this: `nl_query`, `user_id`, and `created_at` are all the fields needed for an autocomplete query. No schema changes are required for Feature 9 to use this table.

Feature 15 (Anomaly Detection) uses the same `user_id` scoping pattern established here. The tenant isolation approach in `rag.py` serves as the reference implementation.

---

## 11. Open Questions

| # | Question | Owner | Due |
|---|---|---|---|
| Q1 | In v1 without a formal tier system, is `ENABLE_RAG_RETRIEVAL` a global config flag only, or should it be checkable per user role? The spec says Pro vs Basic tier — does `admin` role map to Pro and `researcher` to Basic, or are all authenticated users Pro for now? | Product | Before implementation |
| Q2 | Should `session_id` FK use `ON DELETE SET NULL` (preserve history when session deleted) or `ON DELETE CASCADE` (delete history with session)? SET NULL preserves the analytics value of the corpus; CASCADE keeps the database clean. | Architecture | Before migration |
| Q3 | The retrieval call embeds the current NL query via the OpenAI embedding API on every query. Should there be an explicit timeout on this call (e.g., 500ms) after which retrieval is skipped? Or is the existing `LLM_TIMEOUT_SECONDS` setting sufficient? | Performance | Before `rag.py` implementation |
| Q4 | Should retrieved examples from `query_history` be logged at DEBUG level so query accuracy can be analysed? Logging the retrieved queries (not the embeddings) would allow admins to understand why a particular SQL was generated. | Observability | Before `rag.py` implementation |
| Q5 | For the benchmark endpoint (`POST /api/v1/query/benchmark`), should RAG retrieval be optionally supported if a `user_id` is passed? Or should benchmark always use static prompt only to ensure consistent comparisons across providers? | Product | Before `pipeline.py` changes |
