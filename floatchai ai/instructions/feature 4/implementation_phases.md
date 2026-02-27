# Feature 4 — Natural Language Query Engine: Implementation Phases

## Status: Complete

| Phase | Name | Status | Dependencies |
|-------|------|--------|-------------|
| 1 | Configuration & Dependencies | **Complete** | None |
| 2 | Schema Prompt | **Complete** | Phase 1 |
| 3 | Geography Module | **Complete** | Phase 1 |
| 4 | Context Module | **Complete** | Phase 1 |
| 5 | Validator Module | **Complete** | Phase 1 |
| 6 | Executor Module | **Complete** | Phase 1, Phase 5 |
| 7 | Pipeline Module | **Complete** | Phase 1, Phase 2, Phase 3, Phase 5 |
| 8 | API Router & Wiring | **Complete** | Phase 4, Phase 6, Phase 7 |
| 9 | Tests | **Complete** | Phases 1–8 |
| 10 | Documentation | **Complete** | Phases 1–9 |

---

## Gap Resolutions (Incorporated)

All 11 gaps identified during Step 1 were resolved by the user before phases were created. These resolutions are embedded into the phase specifications below.

| # | Gap | Resolution |
|---|-----|-----------|
| 1 | Interpretation LLM call strategy | Separate LLM call for interpretation (system prompt wins over PRD) |
| 2 | Geography file path conflict | `data/geography_lookup.json` relative to backend root; config default matches |
| 3 | Context turn storage timing | Only after execution completes (row_count must be real) |
| 4 | SQL visibility | Always include SQL in response for all users in v1 |
| 5 | Non-ingested data handling | Let query run, return row_count=0, per FR-26 |
| 6 | Redis dependency for query module | `get_redis_client()` local to query router; returns None on failure |
| 7 | sqlglot version | `sqlglot>=20.0.0` |
| 8 | Confirmation threshold heuristic | EXPLAIN (FORMAT JSON) for row estimation; default to execute on failure |
| 9 | bbp700/downwelling_irradiance columns | Include in schema prompt; note no QC flag columns |
| 10 | OPENAI_API_KEY optionality | Keep Optional; pipeline returns structured error if None |
| 11 | QUERY_LLM_MODEL vs LLM_MODEL | Separate setting (QUERY_LLM_MODEL); intentionally independent |

**Additional Requirement:** Multi-model LLM support with benchmarking. Four providers: DeepSeek (default, `deepseek-reasoner`), Qwen QwQ (`qwq-32b`), Gemma (`gemma3`), OpenAI (`gpt-4o`). All use OpenAI-compatible API format. `POST /api/v1/query/benchmark` endpoint compares all providers on a single query (SQL generation only, no execution).

---

## Phase 1 — Configuration & Dependencies

**Goal:** Add all Feature 4 settings to `config.py`, add `sqlglot` to `requirements.txt`, update `.env.example`, and create the `data/` directory with an empty placeholder.

### Files to Create or Modify

| File | Action |
|------|--------|
| `app/config.py` | Add 18+ new settings for Feature 4 |
| `requirements.txt` | Add `sqlglot>=20.0.0` |
| `.env.example` | Add Feature 4 env vars section |
| `app/query/__init__.py` | Create empty package init |
| `data/` | Create directory (geography_lookup.json comes in Phase 3) |

### New Settings in `config.py`

```python
# ── Feature 4: Natural Language Query Engine ──
QUERY_LLM_PROVIDER: str = "deepseek"          # deepseek | qwen | gemma | openai
QUERY_LLM_MODEL: str = "deepseek-reasoner"    # Model name for chosen provider
QUERY_LLM_TEMPERATURE: float = 0.0
QUERY_LLM_MAX_TOKENS: int = 2048
QUERY_MAX_RETRIES: int = 3
QUERY_MAX_ROWS: int = 1000
QUERY_CONFIRMATION_THRESHOLD: int = 50000
QUERY_CONTEXT_TTL: int = 3600
QUERY_CONTEXT_MAX_TURNS: int = 20
QUERY_BENCHMARK_TIMEOUT: int = 60             # Total timeout for benchmark endpoint
GEOGRAPHY_FILE_PATH: str = "data/geography_lookup.json"

# Provider-specific base URLs
DEEPSEEK_API_KEY: Optional[str] = None
DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
QWEN_API_KEY: Optional[str] = None
QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
GEMMA_API_KEY: Optional[str] = None
GEMMA_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai"
# OPENAI_API_KEY already exists as Optional[str]
```

### Done Checklist
- [x] `config.py` has all new settings with correct types and defaults
- [x] No existing settings removed or renamed
- [x] `requirements.txt` includes `sqlglot>=20.0.0`
- [x] `.env.example` has a `# Feature 4` section with all new env vars
- [x] `app/query/__init__.py` exists (empty)
- [x] `data/` directory exists

---

## Phase 2 — Schema Prompt

**Goal:** Create `app/query/schema_prompt.py` containing the `SCHEMA_PROMPT` module-level constant. This is the system prompt sent to the LLM for SQL generation.

**Important:** Read `app/db/models.py` before writing this file — do not rely on memory. The schema prompt must exactly reflect the real table/column definitions.

### Files to Create

| File | Action |
|------|--------|
| `app/query/schema_prompt.py` | Create with SCHEMA_PROMPT constant |

### Requirements
- Module-level constant `SCHEMA_PROMPT: str` — never rebuilt per request (Hard Rule 3)
- Must include all 10 tables and 2 materialized views from `models.py`
- Must include column names, types, nullable flags, and foreign key relationships
- Must include `bbp700` and `downwelling_irradiance` with a note that they have NO QC flag columns
- Must include 20+ few-shot examples covering:
  - Temporal filters (`DATE()`, `BETWEEN`, `>=`)
  - Spatial filters (`ST_DWithin`, `ST_MakePoint(longitude, latitude)` — longitude first, Hard Rule 9)
  - Aggregations (`AVG`, `COUNT`, `MAX`, `MIN`)
  - JOINs across profiles → measurements, floats → profiles, etc.
  - QC-filtered queries (`WHERE temp_qc = 1`)
  - Ocean region queries using `ocean_regions` table
  - Materialized view queries
  - `LIMIT` usage (default 1000)
- Must include explicit instructions:
  - Use `ST_MakePoint(longitude, latitude)` — longitude is the first argument
  - Always cast geometry columns: `::geography` for distance, `::geometry` for containment
  - Default `LIMIT 1000` unless user specifies otherwise
  - Only use tables listed in the prompt
  - Only generate SELECT statements
  - Never use `DELETE`, `UPDATE`, `INSERT`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`

### Done Checklist
- [x] `SCHEMA_PROMPT` is a module-level string constant
- [x] All 10 tables and 2 materialized views are documented with columns and types
- [x] 20+ few-shot examples included
- [x] `bbp700` and `downwelling_irradiance` noted as having no QC columns
- [x] ST_MakePoint longitude-first instruction is explicit
- [x] Geography cast instructions included
- [x] Default LIMIT 1000 instruction included

---

## Phase 3 — Geography Module

**Goal:** Create the geography lookup JSON and the resolver module.

### Files to Create

| File | Action |
|------|--------|
| `data/geography_lookup.json` | Create with ocean basins, seas, straits, bounding boxes |
| `app/query/geography.py` | Create with `resolve_geography()` function |

### `data/geography_lookup.json` Structure
```json
{
  "arabian sea": {"lat_min": 0.0, "lat_max": 25.0, "lon_min": 45.0, "lon_max": 78.0},
  "bay of bengal": {"lat_min": 5.0, "lat_max": 23.0, "lon_min": 78.0, "lon_max": 100.0},
  ...
}
```
- Keys are lowercase, trimmed
- Values are bounding boxes with `lat_min`, `lat_max`, `lon_min`, `lon_max`
- Must include: all major ocean basins, major seas (30+), key straits and gulfs
- File loaded once at module import time, not per request

### `app/query/geography.py` API
```python
def resolve_geography(query: str) -> Optional[dict]:
    """
    Scans the NL query for known geography names.
    Returns {"name": str, "lat_min": float, "lat_max": float, "lon_min": float, "lon_max": float}
    or None if no geography detected.
    Matching: case-insensitive substring scan of query against all keys.
    """
```

### Done Checklist
- [x] `data/geography_lookup.json` has 30+ entries with bounding boxes
- [x] `geography.py` loads JSON once at module level
- [x] `resolve_geography()` returns correct dict or None
- [x] Matching is case-insensitive substring
- [x] No external dependencies (pure Python + json stdlib)

---

## Phase 4 — Context Module

**Goal:** Create `app/query/context.py` for Redis-backed conversation context storage.

### Files to Create

| File | Action |
|------|--------|
| `app/query/context.py` | Create with get/append/clear functions |

### API

```python
async def get_context(redis_client: Optional[Redis], session_id: str) -> list[dict]:
    """Returns list of turns [{role, content, sql, row_count}] or [] if Redis unavailable."""

async def append_context(redis_client: Optional[Redis], session_id: str, turn: dict, settings) -> None:
    """Appends turn, trims to max turns, sets TTL. No-op if Redis unavailable."""

async def clear_context(redis_client: Optional[Redis], session_id: str) -> None:
    """Deletes session context. No-op if Redis unavailable."""
```

### Requirements
- All functions accept `redis_client: Optional[Redis]` — if None, gracefully no-op / return empty
- Key format: `query:context:{session_id}`
- Stored as JSON string in Redis (list of turn dicts)
- `append_context` trims oldest turns if length exceeds `QUERY_CONTEXT_MAX_TURNS`
- `append_context` sets TTL = `QUERY_CONTEXT_TTL` on every append
- Turn dict schema: `{"role": "user"|"assistant", "content": str, "sql": Optional[str], "row_count": Optional[int]}`
- Context is NOT stored in the pipeline (Hard Rule / Gap 3 resolution) — it is stored in the API layer after execution

### Done Checklist
- [x] All 3 functions implemented with Optional[Redis] pattern
- [x] Graceful no-op when redis_client is None
- [x] TTL and max turns enforced
- [x] Key format is `query:context:{session_id}`
- [x] Turn schema matches specification

---

## Phase 5 — Validator Module

**Goal:** Create `app/query/validator.py` with the 3-check SQL validation pipeline plus geography cast check.

### Files to Create

| File | Action |
|------|--------|
| `app/query/validator.py` | Create with validate_sql() and sub-checks |

### API

```python
def validate_sql(sql: str, allowed_tables: set[str]) -> ValidationResult:
    """
    Runs 3 checks sequentially. Returns ValidationResult.
    Checks:
    1. Syntax check — parse with sqlglot (dialect="postgres"), catch ParseError
    2. Read-only check — walk AST, reject if any node is not SELECT/WITH (Hard Rule 4)
    3. Table whitelist check — extract all table names from AST, reject if any not in allowed_tables
    Additionally:
    4. Geography cast warning — scan AST for ST_DWithin/ST_MakePoint without ::geography cast
    """

@dataclass
class ValidationResult:
    valid: bool
    error: Optional[str] = None      # Human-readable error message
    check_failed: Optional[str] = None  # "syntax" | "readonly" | "whitelist" | None
    warnings: list[str] = field(default_factory=list)  # e.g., geography cast warnings
```

### Requirements
- Uses `sqlglot` for all AST operations — no regex-based SQL parsing
- Read-only enforcement via AST inspection, not string matching (Hard Rule 4)
- `allowed_tables` set is defined as a module-level constant derived from the schema prompt
- Geography cast check is a warning, not a hard failure
- Must handle multi-statement SQL (reject — only single SELECT allowed)
- Must handle CTE (WITH ... AS ... SELECT) — allowed
- Must handle subqueries — allowed, but all referenced tables must be in whitelist

### Done Checklist
- [x] `validate_sql()` runs all 3 checks + geography warning
- [x] Syntax check uses `sqlglot.parse()` with postgres dialect
- [x] Read-only check walks AST for non-SELECT statements (Hard Rule 4)
- [x] Whitelist check extracts all table names from AST
- [x] `ALLOWED_TABLES` is a module-level constant
- [x] Geography cast warning implemented
- [x] Multi-statement SQL rejected
- [x] CTEs and subqueries handled correctly

---

## Phase 6 — Executor Module

**Goal:** Create `app/query/executor.py` for safe SQL execution on the readonly database session.

### Files to Create

| File | Action |
|------|--------|
| `app/query/executor.py` | Create with execute_sql() and estimate_rows() |

### API

```python
async def execute_sql(sql: str, db: Session, max_rows: int) -> ExecutionResult:
    """
    Executes validated SQL on readonly session.
    Returns ExecutionResult with columns, rows, row_count, truncated flag.
    """

async def estimate_rows(sql: str, db: Session) -> Optional[int]:
    """
    Runs EXPLAIN (FORMAT JSON) on the SQL. Extracts estimated row count.
    Returns None on any failure (default to execute per Gap 8 resolution).
    """

@dataclass
class ExecutionResult:
    columns: list[str]
    rows: list[dict]
    row_count: int
    truncated: bool  # True if row_count > max_rows (results were limited)
    error: Optional[str] = None
```

### Requirements
- Always uses the session from `get_readonly_db()` — never creates its own engine (Hard Rule 2)
- `execute_sql` adds `LIMIT {max_rows}` if not already present in the SQL
- `execute_sql` catches all DB exceptions and returns error in `ExecutionResult`
- `estimate_rows` uses `EXPLAIN (FORMAT JSON)` — parses the JSON output for `"Plan Rows"`
- `estimate_rows` returns None on any failure (per Gap 8: default to execute)
- Original SQL is never modified after validation (Hard Rule 8) — LIMIT is added as a wrapper: `SELECT * FROM ({original_sql}) AS _q LIMIT {max_rows}`

### Done Checklist
- [x] `execute_sql()` wraps SQL with LIMIT if needed
- [x] Uses `get_readonly_db()` session only (Hard Rule 2)
- [x] All exceptions caught and returned in ExecutionResult
- [x] `estimate_rows()` parses EXPLAIN JSON output
- [x] `estimate_rows()` returns None on failure
- [x] Original SQL never modified (Hard Rule 8)

---

## Phase 7 — Pipeline Module

**Goal:** Create `app/query/pipeline.py` — the core LLM orchestration module. All LLM calls happen here and only here (Hard Rule 7).

### Files to Create

| File | Action |
|------|--------|
| `app/query/pipeline.py` | Create with nl_to_sql(), interpret_results(), get_llm_client() |

### API

```python
async def nl_to_sql(
    query: str,
    context: list[dict],
    geography: Optional[dict],
    settings,
    provider: Optional[str] = None,  # Override for benchmark
    model: Optional[str] = None,     # Override for benchmark
) -> PipelineResult:
    """
    Core pipeline: builds prompt → calls LLM → extracts SQL → validates → retries up to max_retries.
    Returns PipelineResult.
    """

async def interpret_results(
    query: str,
    sql: str,
    columns: list[str],
    rows: list[dict],
    row_count: int,
    settings,
) -> str:
    """
    Separate LLM call to generate a natural language interpretation of query results.
    Uses the same provider/model as the main query.
    """

def get_llm_client(provider: str, settings) -> OpenAI:
    """
    Factory function. Returns an OpenAI-compatible client for the given provider.
    Providers: deepseek, qwen, gemma, openai.
    Raises ValueError if API key for provider is not set.
    """

@dataclass
class PipelineResult:
    sql: Optional[str] = None
    error: Optional[str] = None
    retries_used: int = 0
    validation_errors: list[str] = field(default_factory=list)
    provider: str = ""
    model: str = ""
```

### Requirements
- All LLM calls happen in this file only (Hard Rule 7)
- Prompt assembly: SCHEMA_PROMPT + context turns + geography coordinates (if resolved) + user query
- SQL extraction: parse LLM response for ```sql ... ``` block or raw SELECT statement
- Validation: call `validate_sql()` after extraction
- Retry loop: up to `QUERY_MAX_RETRIES` attempts; each retry includes the previous validation error in the prompt
- After 3 failed validations, return error — never execute (Hard Rule 10)
- `get_llm_client()` uses OpenAI library with custom `base_url` per provider
- If API key is None/missing, return structured error immediately (Gap 10)
- `interpret_results()` is a separate LLM call (Gap 1 resolution)
- Context is NOT stored here — that happens in the API layer (Gap 3 resolution)

### Done Checklist
- [x] `nl_to_sql()` implements full prompt → LLM → extract → validate → retry loop
- [x] `get_llm_client()` returns correct client for all 4 providers
- [x] `interpret_results()` makes a separate LLM call
- [x] All LLM calls are in this file only (Hard Rule 7)
- [x] Retry loop respects `QUERY_MAX_RETRIES` (Hard Rule 10)
- [x] Missing API key returns structured error (Gap 10)
- [x] Context is NOT stored in this module (Gap 3)
- [x] Provider/model overrides work for benchmark use case

---

## Phase 8 — API Router & Wiring

**Goal:** Create `app/api/v1/query.py` with two endpoints, wire into `main.py`, and implement the full request/response flow including context storage.

### Files to Create or Modify

| File | Action |
|------|--------|
| `app/api/v1/query.py` | Create with POST /query and POST /query/benchmark |
| `app/main.py` | Add query_router import and include |

### Endpoints

#### `POST /api/v1/query`
```python
Request: {
    "query": str,           # Natural language query
    "session_id": Optional[str],  # For conversation context; auto-generated if missing
    "provider": Optional[str],    # Override default provider
    "model": Optional[str],       # Override default model
    "confirm_execution": Optional[bool]  # For large result confirmation flow
}

Response: {
    "session_id": str,
    "sql": str,              # Always included (Gap 4)
    "columns": list[str],
    "rows": list[dict],
    "row_count": int,
    "truncated": bool,
    "interpretation": str,
    "confirmation_required": Optional[bool],  # True if estimated rows > threshold
    "estimated_rows": Optional[int],
    "error": Optional[str],
    "provider": str,
    "model": str,
}
```

#### `POST /api/v1/query/benchmark`
```python
Request: {
    "query": str,            # Natural language query
    "providers": Optional[list[str]]  # Default: all configured providers
}

Response: {
    "query": str,
    "results": [
        {
            "provider": str,
            "model": str,
            "sql": Optional[str],
            "valid": bool,
            "validation_errors": list[str],
            "latency_ms": float,
            "error": Optional[str],
        }
    ]
}
```

### Requirements
- `get_redis_client()` defined locally in query router — returns `Optional[Redis]`, returns None on failure (Gap 6)
- Context stored AFTER execution completes with real row_count (Gap 3)
- `session_id` auto-generated via `uuid4()` if not provided
- Confirmation flow: if `estimate_rows()` > threshold AND `confirm_execution` is not True, return `confirmation_required=True` without executing
- Benchmark endpoint runs providers sequentially with a total timeout of `QUERY_BENCHMARK_TIMEOUT` seconds
- Benchmark endpoint: SQL generation only, no execution (safe + fast)
- Wire `query_router` into `main.py` at prefix `/api/v1`

### Done Checklist
- [x] `POST /query` endpoint implements full flow: geography → context → pipeline → estimate → execute → interpret → store context
- [x] `POST /query/benchmark` endpoint compares all providers (SQL gen only)
- [x] `get_redis_client()` is local to this router, returns None on failure
- [x] Context stored after execution with real row_count (Gap 3)
- [x] session_id auto-generated if missing
- [x] Confirmation flow with EXPLAIN threshold
- [x] Benchmark has total timeout
- [x] `query_router` wired into `main.py`

---

## Phase 9 — Tests ✅ COMPLETE

**Goal:** Comprehensive test coverage for all Feature 4 modules.

### Files to Create

| File | Tests |
|------|-------|
| `tests/test_validator.py` | Syntax check, read-only check, whitelist check, CTE handling, multi-statement rejection, geography cast warning |
| `tests/test_executor.py` | Execute valid SQL, LIMIT wrapping, error handling, estimate_rows parsing |
| `tests/test_geography.py` | Resolve known regions, case insensitivity, no match returns None, substring matching |
| `tests/test_context.py` | Get/append/clear, TTL, max turns trim, None redis graceful no-op |
| `tests/test_pipeline_f4.py` | LLM client factory, SQL extraction, retry loop, missing API key error, provider override |

### Requirements
- Use `pytest` + `pytest-asyncio`
- Mock all LLM calls (no real API calls in tests)
- Mock Redis where needed
- Use the readonly session fixture from existing `conftest.py` for executor tests
- Validator tests should use real `sqlglot` parsing (no mocks)
- Test count target: 40+ tests across all 5 files

### Results
- **97 Feature 4 tests** across 5 files — all passing
- **283 total tests** (including Features 1-3) — all passing, 0 regressions
- Fixed sqlglot v29 compatibility: replaced `expressions.AlterTable` with `expressions.Alter` + expanded write-type detection

### Done Checklist
- [x] 5 test files created
- [x] All validator checks tested (syntax, readonly, whitelist, cast, CTE, multi-statement)
- [x] Executor tested with mocked DB session
- [x] Geography resolver tested with known and unknown inputs
- [x] Context module tested with real and None Redis
- [x] Pipeline tested with mocked LLM responses
- [x] All tests pass (97 Feature 4 + 186 Features 1-3 = 283 total)
- [x] No tests require real API keys or live database

---

## Phase 10 — Documentation ✅ COMPLETE

**Goal:** Update README.md and finalize this implementation_phases.md.

### Files to Modify

| File | Action |
|------|--------|
| `README.md` | Add Feature 4 section: endpoints, configuration, architecture |
| `instructions/feature 4/implementation_phases.md` | Mark all phases complete, add final notes |

### Requirements
- README documents both endpoints with request/response examples
- README lists all new environment variables
- README explains the multi-model provider system
- Implementation phases file has all checkboxes checked and status updated

### Done Checklist
- [x] README.md updated with Feature 4 documentation
- [x] Implementation phases file finalized
- [x] All phase statuses marked "Complete"
- [x] Project structure updated (query/ module, data/ directory, test files)
- [x] Tech stack updated (sqlglot, multi-provider LLM)
- [x] Test counts updated (309 total)
- [x] Hard Rules 27–36 added for Feature 4
- [x] Release Plan Phase 4 marked Complete

### Files Created/Modified Across All Phases

| File | Phase | Action |
|------|-------|--------|
| `app/config.py` | 1 | Modified — 18 new settings |
| `requirements.txt` | 1 | Modified — added sqlglot |
| `.env.example` | 1 | Modified — Feature 4 section |
| `app/query/__init__.py` | 1 | Created — empty package |
| `data/README.md` | 1 | Created — placeholder |
| `app/query/schema_prompt.py` | 2 | Created — SCHEMA_PROMPT + ALLOWED_TABLES |
| `data/geography_lookup.json` | 3 | Created — 50 ocean regions |
| `app/query/geography.py` | 3 | Created — resolve_geography + reload |
| `app/query/context.py` | 4 | Created — get/append/clear context |
| `app/query/validator.py` | 5 | Created — 3-check validation |
| `app/query/executor.py` | 6 | Created — execute_sql + estimate_rows |
| `app/query/pipeline.py` | 7 | Created — nl_to_sql + interpret_results |
| `app/api/v1/query.py` | 8 | Created — POST /query + POST /query/benchmark |
| `app/main.py` | 8 | Modified — query_router wired in |
| `tests/test_validator.py` | 9 | Created — 33 tests |
| `tests/test_executor.py` | 9 | Created — 19 tests |
| `tests/test_geography.py` | 9 | Created — 17 tests |
| `tests/test_context.py` | 9 | Created — 15 tests |
| `tests/test_pipeline_f4.py` | 9 | Created — 13 tests |
| `README.md` | 10 | Modified — Feature 4 docs, project structure, tests, hard rules |

---

## Dependency Graph

```
Phase 1 (Config)
├── Phase 2 (Schema Prompt)
├── Phase 3 (Geography)
├── Phase 4 (Context)
├── Phase 5 (Validator)
│   └── Phase 6 (Executor)
│       └── Phase 8 (API Router)
└── Phase 7 (Pipeline) ← depends on 2, 3, 5
    └── Phase 8 (API Router) ← depends on 4, 6, 7
        └── Phase 9 (Tests)
            └── Phase 10 (Docs)
```

## Notes

- **Phase 8 benchmark timeout:** The benchmark endpoint runs all providers sequentially, which could take 15–30 seconds. A total `QUERY_BENCHMARK_TIMEOUT` config setting is included in Phase 1 to cap this.
- **Phase 2 models.py read:** Before writing the schema prompt, `models.py` must be re-read — do not rely on cached knowledge.
- **Hard Rules:** All 10 hard rules from `feature4_system_prompt.md` are enforced across the relevant phases. No exceptions.
