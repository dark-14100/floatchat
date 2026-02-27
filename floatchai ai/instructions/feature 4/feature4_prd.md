# FloatChat — Feature 4: Natural Language Query Engine
## Product Requirements Document (PRD)

**Feature Name:** Natural Language Query Engine
**Version:** 1.0
**Status:** Ready for Development
**Owner:** Backend / AI Engineering
**Depends On:** Feature 1 (Data Ingestion Pipeline), Feature 2 (Ocean Data Database — schema, DAL, read-only user), Feature 3 (Metadata Search Engine — for dataset context before querying)

---

## 1. Purpose & Background

### 1.1 What Problem Does This Solve?
Even with a perfectly structured database, querying oceanographic data requires writing SQL with PostGIS spatial functions, correct table joins, QC flag filtering, and Julian date arithmetic. This is beyond the reach of most researchers, climate analysts, and students.

The Natural Language Query Engine is the core intelligence layer of FloatChat. It takes a plain English question from a researcher and converts it into valid, safe, optimized PostgreSQL SQL. It executes that query, returns structured results, and maintains conversation context so follow-up questions work naturally.

This is the feature that makes FloatChat a research tool rather than a data portal.

### 1.2 What This Feature Is
A pipeline that:
1. Accepts a natural language question with optional conversation context
2. Resolves geographic place names to coordinates
3. Constructs a detailed LLM prompt with schema, examples, and context
4. Calls an LLM to generate a PostgreSQL SQL query
5. Validates the generated SQL for safety and correctness
6. Retries with error feedback if the SQL is invalid (up to 3 attempts)
7. Executes the validated SQL against the database using a read-only connection
8. Returns structured results with a human-readable interpretation
9. Stores the query turn in Redis for multi-turn conversation context

### 1.3 What This Feature Is Not
- It is not a full chatbot — it does not generate free-form prose responses
- It does not render visualizations — that is Feature 6
- It does not handle file exports — that is Feature 8
- It does not manage the chat UI session — that is Feature 5
- It does not replace the metadata search layer — Feature 3 identifies which datasets exist, Feature 4 queries the data inside them

### 1.4 Relationship to Other Features
- Feature 2 provides the read-only database session (`get_readonly_db`) that Feature 4 must use exclusively for query execution
- Feature 2's DAL provides `get_profiles_by_radius`, `get_profiles_by_basin`, and related functions — Feature 4 may use these for simple queries but generates raw SQL for complex ones
- Feature 3 can be called before query generation to retrieve relevant dataset context (date ranges, regions, variables available) to improve SQL accuracy
- Feature 5 (Chat Interface) calls Feature 4's API endpoint and displays results inline
- Feature 6 (Visualization) consumes the structured result data returned by Feature 4
- Feature 8 (Export) exports the query results that Feature 4 produces
- Feature 9 (Guided Query Assistant) calls Feature 4 after assembling a query from clarification chips

---

## 2. Goals & Success Criteria

### 2.1 Goals
- Convert plain English ocean data questions into correct, executable PostgreSQL SQL
- Return results within 10 seconds end-to-end for standard queries
- Maintain multi-turn conversation context so follow-up questions work without re-stating context
- Never execute unsafe SQL — no write operations, no schema changes, no unauthorized tables
- Handle spatial, temporal, depth, and variable-availability query patterns correctly

### 2.2 Success Criteria

| Criterion | Target |
|---|---|
| SQL generation accuracy on test suite (50+ queries) | ≥ 85% correct on first attempt |
| End-to-end query latency (p95) | < 10 seconds |
| LLM call latency (p95) | < 5 seconds |
| SQL validation rejection of unsafe queries | 100% — zero unsafe queries execute |
| Retry success rate (valid SQL on retry 1 or 2) | ≥ 70% of initially failed generations |
| Multi-turn context recall (follow-up question resolves correctly) | ≥ 90% of test cases |
| Geographic entity resolution accuracy | ≥ 95% for included place names |

---

## 3. User Stories

### 3.1 Researcher
- **US-01:** As a researcher, I want to type "show temperature profiles near the Maldives in 2023" and receive a result table, so that I can explore data without writing SQL.
- **US-02:** As a researcher, I want to ask "now show me salinity for the same region" and have the system understand I mean the same spatial filter, so that follow-up queries work naturally.
- **US-03:** As a researcher, I want to see a plain-English interpretation of what query will run before results appear, so that I can catch misunderstandings early.
- **US-04:** As a researcher, I want queries to finish within 10 seconds for typical data sizes, so that exploration feels interactive.
- **US-05:** As a researcher, I want to filter by depth, saying "deep profiles below 1000m", and have the system translate that to the correct pressure column, so that I don't need to know the schema.

### 3.2 System (Internal Consumer)
- **US-06:** As Feature 5 (Chat Interface), I need to call a single API endpoint with a natural language query and session ID and receive structured results and an interpretation string, so that I can display results inline in the chat.
- **US-07:** As Feature 6 (Visualization), I need structured result data with typed columns so that I can auto-select the correct chart type.
- **US-08:** As Feature 8 (Export), I need the generated SQL and result data to be available for export in CSV/NetCDF/JSON formats.

---

## 4. Functional Requirements

### 4.1 LLM Provider

**FR-01 — LLM Selection**
Use GPT-4o as the primary LLM for SQL generation. Use the same `OPENAI_API_KEY` already present in settings. Do not use Claude, LLaMA, or any other model in v1.

**FR-02 — LLM Call Configuration**
LLM calls for SQL generation must use:
- `temperature: 0` — deterministic output for SQL generation
- `max_tokens: 2000` — sufficient for complex multi-join queries
- A system prompt (the schema prompt) and a user message (the NL query + context)
- Response format: plain text, not JSON mode — the response is a SQL string

### 4.2 Schema Prompt

**FR-03 — Schema Prompt Construction**
Build a static schema prompt string that describes the database to the LLM. This prompt must include:
- The name and purpose of every queryable table: `floats`, `profiles`, `measurements`, `datasets`, `float_positions`, `ocean_regions`
- Every column name, type, and plain-English description for each table
- All foreign key relationships described in plain English
- A description of the `geom` column and how to use PostGIS functions with it
- A description of the ARGO Julian date convention (`juld_raw` = days since 1950-01-01) and how `timestamp` relates to it
- A description of QC flag columns: values 0-9, where 1 = good, 2 = probably good, 4 = bad
- An explicit instruction that only these tables may be queried — no system tables, no embedding tables, no ingestion_jobs except for admins
- An explicit instruction that the response must contain only a SQL SELECT statement — no explanation, no markdown fences, no preamble

**FR-04 — Few-Shot Examples**
Include at least 20 NL→SQL example pairs in the schema prompt. Examples must cover:
- Spatial queries using `ST_DWithin` with a radius in meters
- Spatial queries using `ST_Within` against a named ocean basin via `ocean_regions`
- Time range queries using `BETWEEN` on the `timestamp` column
- Depth/pressure range queries on the `measurements` table
- Variable availability queries (profiles with non-null dissolved oxygen)
- Multi-join queries combining profiles + measurements
- Float type filtering (BGC vs core)
- Queries combining spatial + temporal + depth filters
- Queries using `ORDER BY` and `LIMIT`
- Queries referencing float trajectory (ordered positions for a specific platform)

The examples must be realistic ARGO oceanography queries, not generic SQL examples.

**FR-05 — Prompt Versioning**
The schema prompt must be stored as a versioned string in a dedicated file (`app/query/schema_prompt.py`) and not constructed inline in the query pipeline. When the schema changes, the prompt is updated in one place. Include a `SCHEMA_PROMPT_VERSION` constant in the file.

### 4.3 Geographic Entity Resolution

**FR-06 — Place Name Resolver**
Before constructing the LLM prompt, scan the user's query for geographic place names and resolve them to latitude/longitude coordinates. This prevents the LLM from hallucinating incorrect coordinates.

The resolver must use a curated lookup table (a Python dict or JSON file), not a live geocoding API, for v1. The lookup table must include at minimum:
- All countries bordering the Indian Ocean
- Major island groups: Maldives, Sri Lanka, Andaman Islands, Lakshadweep, Seychelles, Mauritius, Madagascar, Reunion, Comoros
- Major coastal cities relevant to ocean research: Chennai, Mumbai, Colombo, Karachi, Kolkata, Dhaka (coastal region), Yangon, Bangkok, Singapore, Jakarta, Perth, Durban, Nairobi (coastal region), Dar es Salaam
- All named regions in the `ocean_regions` table (Arabian Sea, Bay of Bengal, etc.)

When a match is found, the resolved coordinates are injected into the prompt as additional context: `"Note: '{place_name}' resolves to latitude {lat}, longitude {lon}. Use these coordinates in ST_MakePoint."` If no match is found, pass the query to the LLM unmodified and let it attempt resolution.

**FR-07 — Coordinate Injection**
Injected coordinates must appear in the user message portion of the LLM prompt, not the system prompt. This keeps the static schema prompt cacheable by the OpenAI API.

### 4.4 Context Management

**FR-08 — Redis Session Storage**
Store conversation context in Redis keyed by `session_id`. Each session stores the last 10 query turns. Each turn is a dict containing: `nl_query`, `generated_sql`, `interpretation`, `row_count`, `timestamp`. Use Redis key pattern: `query_context:{session_id}`. TTL: 24 hours.

**FR-09 — Context Window Construction**
When constructing the LLM prompt for a follow-up query, include the last N turns from Redis as context. N is configurable via `QUERY_CONTEXT_TURNS` setting (default 3 — include last 3 turns). Including all 10 turns would exceed the LLM context window for complex sessions.

**FR-10 — Context Format in Prompt**
Format previous turns as a readable conversation history appended to the user message:
```
Previous queries in this session:
Turn 1: "show temperature near Sri Lanka in 2023" → [brief SQL summary]
Turn 2: "now show salinity" → [brief SQL summary]
Current query: "now show deep profiles below 500m"
```
The LLM uses this to resolve relative references ("the same region", "those floats", "now show").

**FR-11 — Session Creation**
If `session_id` is not provided in the API request, generate a new UUID and return it in the response. The client must include this `session_id` in all follow-up requests to maintain context.

**FR-12 — Context Isolation**
Different session IDs must have completely isolated contexts. A query in one session must never influence another session. Redis keys are namespaced by session ID to enforce this.

### 4.5 SQL Generation Pipeline

**FR-13 — `nl_to_sql(query, session_id, db)` Function**
The main pipeline function. Accepts a natural language query string and session ID. Returns a dict containing: `sql`, `interpretation`, `session_id`, `attempt_count`.

Steps:
1. Retrieve context from Redis for the session
2. Resolve geographic entities in the query
3. Build the full LLM prompt (schema prompt + context + resolved query)
4. Call the LLM
5. Extract the SQL from the response (strip any markdown fences, whitespace, or preamble)
6. Validate the SQL
7. If invalid, retry with error feedback (up to 3 times — see FR-16)
8. Generate an interpretation string (see FR-17)
9. Store the turn in Redis
10. Return the result dict

**FR-14 — SQL Extraction**
After the LLM responds, strip the SQL of any markdown code fences (` ```sql `, ` ``` `), leading/trailing whitespace, and any natural language preamble. The extracted string must start with `SELECT`. If the extracted string does not start with `SELECT` after stripping, treat it as a generation failure and retry.

**FR-15 — Interpretation Generation**
Generate a plain-English interpretation of the SQL query before execution. This is a second, short LLM call with a different prompt: "Given this SQL query, write one sentence describing what data it will return, in plain English for a researcher." The interpretation is returned to the client and displayed in the chat before results appear. If this call fails, use a fallback: `"Running your query..."`. Never block execution on interpretation generation.

**FR-16 — Retry Loop**
If SQL validation fails (see FR-18, FR-19, FR-20), retry the LLM call with the validation error appended to the prompt: `"The previous SQL failed validation with error: {error_message}. Please generate a corrected query."` Maximum 3 attempts total (1 original + 2 retries). If all 3 attempts fail validation, return an error response to the client with the last validation error — do not execute any SQL.

**FR-17 — Attempt Tracking**
Record which attempt number produced the final valid SQL. Include `attempt_count` (1, 2, or 3) in the response. Log attempt count per query for monitoring purposes.

### 4.6 SQL Validation

**FR-18 — Syntax Validation**
Parse the generated SQL using `sqlglot` with dialect set to `postgres`. If `sqlglot` raises a parse error, the SQL is invalid. Include the error message in the retry prompt.

**FR-19 — Read-Only Enforcement**
After parsing, inspect the AST produced by `sqlglot`. The query must contain only `SELECT` statements. Reject any query containing: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`, `TRUNCATE`, `GRANT`, `REVOKE`, `EXECUTE`, or any DDL/DML keyword. This check must be done on the parsed AST, not via string matching, to prevent bypass via case variation or comments.

**FR-20 — Table Whitelist**
Inspect the parsed SQL AST for all table references. Only these tables are permitted: `floats`, `profiles`, `measurements`, `datasets`, `float_positions`, `ocean_regions`, `mv_float_latest_position`, `mv_dataset_stats`. Reject any query referencing tables outside this list. If rejected, return a specific error: `"Query references unauthorized table: {table_name}"`.

**FR-21 — Row Limit Enforcement**
Do not add a LIMIT clause during validation — the row limit is enforced at execution time by wrapping the SQL in a subquery with a LIMIT applied by the execution layer. This preserves the original SQL for logging and export purposes. The default execution row limit is `QUERY_DEFAULT_ROW_LIMIT` (default 10,000). The maximum is `QUERY_MAX_ROW_LIMIT` (default 100,000).

**FR-22 — PostGIS Function Allowlist**
If the query uses any PostGIS function (`ST_DWithin`, `ST_Within`, `ST_Distance`, etc.), validate that the geometry arguments use the `::geography` cast, not `::geometry`. Planar geometry calculations are inaccurate at ocean scale. If the wrong cast is detected, include a correction instruction in the retry prompt.

### 4.7 Query Execution

**FR-23 — Read-Only Session**
All query execution must use the `get_readonly_db()` session from Feature 2. Never use the write-capable `get_db()` session for query execution. This is a hard security boundary.

**FR-24 — `execute_safe_query(sql, db)` Function**
Accepts a validated SQL string and a read-only DB session. Wraps the SQL in a subquery with `LIMIT {QUERY_DEFAULT_ROW_LIMIT}` applied. Executes using SQLAlchemy `text()`. Returns results as a list of dicts (column name → value). Includes: `rows` (list of dicts), `row_count` (int), `column_names` (list of str), `truncated` (bool — true if row_count hit the limit), `execution_time_ms` (int).

**FR-25 — Execution Timeout**
Set a PostgreSQL statement timeout of `QUERY_EXECUTION_TIMEOUT_SECONDS` (default 30) on the read-only session before executing. If the query exceeds this timeout, PostgreSQL will cancel it. Catch the timeout error and return a descriptive error to the client: `"Query exceeded the {n}-second time limit. Try narrowing the filters."`.

**FR-26 — Empty Result Handling**
If the query executes successfully but returns zero rows, do not treat this as an error. Return the normal result structure with `row_count = 0` and an empty `rows` list. The interpretation string should reflect this: `"No profiles matched your query. Try adjusting the filters."`.

### 4.8 API Endpoint

**FR-27 — Query Endpoint**
```
POST /api/v1/query
Body: {
  "query": str (required),
  "session_id": str (optional — if absent, a new one is generated),
  "confirm": bool (optional — default false, see FR-28)
}
Response: {
  "session_id": str,
  "interpretation": str,
  "sql": str,
  "results": { "rows": [...], "row_count": int, "column_names": [...], "truncated": bool },
  "execution_time_ms": int,
  "attempt_count": int,
  "awaiting_confirmation": bool
}
```

**FR-28 — Confirmation Mode**
If `confirm: false` (default), the endpoint runs the full pipeline and returns results immediately — no confirmation step. This is the standard mode.

If the system detects a potentially large result (estimated row count > 50,000 based on query structure — this is a heuristic, not a guarantee), set `awaiting_confirmation: true` in the response and return the interpretation and SQL without executing. The client must re-send the request with `confirm: true` to proceed with execution. This prevents accidental massive queries from overwhelming the interface.

**FR-29 — Error Response Format**
All errors must follow a consistent format:
```
{
  "error": str,
  "error_type": "validation_failure" | "generation_failure" | "execution_error" | "timeout",
  "session_id": str,
  "attempts": int
}
```

---

## 5. Non-Functional Requirements

### 5.1 Performance
- End-to-end latency (NL input → results returned) must be under 10 seconds for queries returning under 10,000 rows
- LLM call latency target: under 5 seconds (p95). If GPT-4o exceeds this, log it as a performance event
- SQL execution latency: under 3 seconds for indexed queries at 10M profiles / 100M measurements
- The schema prompt must be constructed once at application startup and cached in memory — never rebuilt per request

### 5.2 Reliability
- A failing LLM call (timeout, API error) must never return a 500 to the client — return a structured error response
- All retries must be logged with attempt number and error message
- If Redis is unavailable, queries must still execute — context is lost but the query still runs. Log a warning.

### 5.3 Security
- The read-only database user (`floatchat_readonly`) must be the only user used for query execution
- The schema prompt must never include table names outside the whitelist
- The API key must never appear in logs
- SQL must never be executed before passing all three validation checks (syntax + read-only + table whitelist)

### 5.4 Observability
- Log every query with: `session_id`, `nl_query` (truncated to 200 chars), `generated_sql`, `attempt_count`, `row_count`, `execution_time_ms`, `llm_latency_ms`
- Log every validation failure with: `session_id`, `attempt_number`, `error_type`, `error_message`
- Log every retry with: `session_id`, `attempt_number`, `previous_error`

---

## 6. New Configuration Settings

Add to the `Settings` class in `config.py`:

- `QUERY_LLM_MODEL` — default `gpt-4o`
- `QUERY_LLM_TEMPERATURE` — default `0`
- `QUERY_LLM_MAX_TOKENS` — default `2000`
- `QUERY_CONTEXT_TURNS` — default `3`
- `QUERY_CONTEXT_TTL_SECONDS` — default `86400` (24 hours)
- `QUERY_DEFAULT_ROW_LIMIT` — default `10000`
- `QUERY_MAX_ROW_LIMIT` — default `100000`
- `QUERY_EXECUTION_TIMEOUT_SECONDS` — default `30`
- `QUERY_CONFIRMATION_THRESHOLD` — default `50000` (row estimate above which confirmation is required)
- `GEOGRAPHY_LOOKUP_FILE` — default `app/query/geography_lookup.json` (path to place name lookup)

---

## 7. File Structure

```
floatchat/
├── backend/
│   ├── app/
│   │   ├── query/
│   │   │   ├── __init__.py
│   │   │   ├── schema_prompt.py      # Static schema prompt + few-shot examples
│   │   │   ├── geography.py          # Place name resolver + lookup table loader
│   │   │   ├── pipeline.py           # nl_to_sql() — main pipeline function
│   │   │   ├── validator.py          # SQL validation (syntax, read-only, whitelist)
│   │   │   ├── executor.py           # execute_safe_query() + timeout handling
│   │   │   └── context.py            # Redis session context storage/retrieval
│   │   └── api/
│   │       └── v1/
│   │           └── query.py          # FastAPI router for POST /api/v1/query
│   ├── data/
│   │   └── geography_lookup.json     # Place name → lat/lon lookup table
│   └── tests/
│       ├── test_pipeline.py
│       ├── test_validator.py
│       ├── test_executor.py
│       ├── test_geography.py
│       └── test_context.py
```

Files to modify:
- `app/config.py` — add new settings
- `app/main.py` — register query router
- `requirements.txt` — add `sqlglot` if not present

---

## 8. Testing Requirements

### 8.1 Pipeline Tests (`test_pipeline.py`)
- Test that `nl_to_sql` returns a dict with all required keys
- Test that a simple spatial query produces SQL containing `ST_DWithin`
- Test that a time range query produces SQL with a `BETWEEN` clause on `timestamp`
- Test that a depth query produces SQL referencing the `pressure` column
- Test that the retry loop is triggered when the first attempt fails validation
- Test that after 3 failed attempts, an error is returned without executing any SQL
- Test that `attempt_count` in the response reflects the correct number of attempts
- Test that context from previous turns is included in the LLM prompt for follow-up queries

### 8.2 Validator Tests (`test_validator.py`)
- Test that a valid `SELECT` query passes all three validation checks
- Test that `INSERT INTO ...` is rejected with `read_only` error type
- Test that `DROP TABLE ...` is rejected
- Test that a query referencing `ingestion_jobs` is rejected with `unauthorized_table` error type
- Test that a query referencing `dataset_embeddings` is rejected
- Test that `::geometry` cast is caught and rejected
- Test that `::geography` cast passes validation
- Test that validation operates on the parsed AST, not raw string (test with mixed-case `DeLeTe`)

### 8.3 Executor Tests (`test_executor.py`)
- Test that `execute_safe_query` wraps SQL in a row-limit subquery
- Test that results are returned as a list of dicts
- Test that `truncated = True` when row count hits the limit
- Test that `truncated = False` when row count is below the limit
- Test that a query timeout returns a structured error, not a 500

### 8.4 Geography Tests (`test_geography.py`)
- Test that "Maldives" resolves to correct lat/lon
- Test that "Sri Lanka" resolves to correct lat/lon
- Test that an unknown place name returns `None` without raising
- Test that resolved coordinates are injected into the prompt correctly
- Test that the lookup file loads without error at startup

### 8.5 Context Tests (`test_context.py`)
- Test that a turn is stored in Redis and retrievable by session_id
- Test that only the last `QUERY_CONTEXT_TURNS` turns are included in the prompt
- Test that a new session_id is generated when none is provided
- Test that two different session_ids have isolated contexts
- Test that context expires after `QUERY_CONTEXT_TTL_SECONDS`

---

## 9. Dependencies & Prerequisites

| Dependency | Reason | Must Be Ready Before |
|---|---|---|
| Feature 2 complete | Read-only DB session, schema, and DAL must exist | Day 1 |
| Feature 3 complete | Dataset context for query enrichment | Before integration testing |
| OpenAI API key configured | LLM calls for SQL generation and interpretation | Day 1 |
| Redis running | Session context storage | Day 1 |
| `sqlglot` Python package | SQL parsing and validation | Before migration |
| `floatchat_readonly` DB user | Query execution safety boundary | Already created in Feature 2 |
| `get_readonly_db()` session | Query execution | Already built in Feature 2 |

---

## 10. Out of Scope for v1.0

- LangChain or LlamaIndex integration (custom pipeline is used)
- Fine-tuned LLM on oceanographic SQL patterns
- Query result caching (covered by Redis cache in Feature 2 — reuse that)
- Streaming SQL results token by token (full result returned at once)
- Multi-dataset join queries spanning more than one ingested dataset
- User feedback loop on query quality (thumbs up/down stored for training)
- Automatic query optimization suggestions

---

## 11. Open Questions

| # | Question | Owner | Due |
|---|---|---|---|
| Q1 | Should the interpretation be generated by a second LLM call, or extracted from the same call by asking the LLM to return both SQL and interpretation in a structured format? A single call is faster but risks mixing SQL with prose. | Backend | Before pipeline implementation |
| Q2 | Should the geography lookup table be a JSON file (as specified) or a Python dict in code? JSON is easier to update without code changes. Python dict is simpler to load. | Backend | Before geography.py implementation |
| Q3 | When `confirm: true` is required for large queries, should the session context turn be stored before or after confirmation? Storing before means the context has a "pending" turn that was never executed. | Backend | Before API implementation |
| Q4 | Should the endpoint expose `sql` in the response for all users, or only for admin users? Showing SQL to researchers may help them learn but also exposes schema details. | Product | Before API implementation |
| Q5 | What is the strategy for handling queries that reference data not yet ingested? (e.g., "show profiles from 2024" when no 2024 data exists). Should the system check against ingested date ranges before calling the LLM? | Backend | Before pipeline implementation |
