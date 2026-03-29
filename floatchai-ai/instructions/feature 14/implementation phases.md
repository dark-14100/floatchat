# FloatChat — Feature 14 Implementation Phases

Phases confirmed on 2026-03-07. Execution is sequential with review gates between phases.
All phases (1-7) completed on 2026-03-07.

## Phase 1 — Alembic Migration (RAG Storage)
**Goal:** Create the `query_history` storage layer and retrieval indexes with safe rollback.

**Files to create**
- `backend/alembic/versions/006_rag_pipeline.py`

**Files to modify**
- None

**Tasks**
1. Create migration `006_rag_pipeline.py` with `down_revision = "005"`.
2. Create `query_history` table with required columns and constraints.
3. Set `session_id` FK to `chat_sessions.session_id` with `ON DELETE SET NULL`.
4. Add `embedding vector(1536)` column.
5. Add B-tree indexes on `user_id` and `created_at`.
6. Add HNSW index on `embedding` using `vector_cosine_ops`, `m=16`, `ef_construction=64` via raw SQL.
7. Add explicit `GRANT SELECT ON query_history TO floatchat_readonly` logic.
8. Implement downgrade to remove indexes/table cleanly.

**PRD requirements fulfilled:** FR-01, FR-02, FR-04
**Depends on:** Existing migrations through `005_auth.py`

**Done when**
- Migration upgrade succeeds.
- Migration downgrade succeeds.
- `query_history` schema and indexes match PRD.
- Readonly grant exists for `floatchat_readonly`.
- All existing backend tests still pass.

---

## Phase 2 — Configuration Flags and Limits
**Goal:** Add RAG configuration controls in `Settings`.

**Files to create**
- None

**Files to modify**
- `backend/app/config.py`

**Tasks**
1. Add `ENABLE_RAG_RETRIEVAL` (global toggle, default `True`).
2. Add `RAG_RETRIEVAL_LIMIT` (default `5`).
3. Add `RAG_SIMILARITY_THRESHOLD` (default `0.4`).
4. Add `RAG_DEDUP_WINDOW_HOURS` (default `24`).
5. Reuse existing timeout configuration path (`LLM_TIMEOUT_SECONDS`) for retrieval timeout behavior.

**PRD requirements fulfilled:** FR-11, NFR reliability fallback behavior
**Depends on:** Phase 1

**Done when**
- New settings load correctly.
- Defaults match PRD.
- Existing backend tests still pass.

---

## Phase 3 — RAG Module (`app/query/rag.py`)
**Goal:** Implement isolated store/retrieve/context functions with robust failure handling.

**Files to create**
- `backend/app/query/rag.py`

**Files to modify**
- None

**Tasks**
1. Implement `store_successful_query(...)` with soft dedup window and silent failure handling.
2. Implement `retrieve_similar_queries(...)` with strict `user_id` SQL filtering.
3. Apply similarity threshold filtering and retrieval limit.
4. Implement `build_rag_context(...)` with prompt-compatible few-shot formatting.
5. Add DEBUG logging for retrieved examples (`nl_query`, `generated_sql` only; never vectors).
6. Keep all embedding calls routed through `embed_texts()`.

**PRD requirements fulfilled:** FR-05, FR-06, FR-07
**Depends on:** Phase 1 (table/indexes), Phase 2 (config)

**Done when**
- Store/retrieve/context functions work against `query_history`.
- No exception escapes these helper functions.
- Tenant isolation is enforced at query SQL layer.
- Existing backend tests still pass.

---

## Phase 4 — Pipeline Retrieval Integration
**Goal:** Integrate retrieval into `nl_to_sql()` as additive context.

**Files to create**
- None

**Files to modify**
- `backend/app/query/pipeline.py`
- `backend/app/api/v1/query.py` (only if call-site signature propagation is needed)

**Tasks**
1. Update `nl_to_sql()` signature to accept optional `user_id` and `db`.
2. Add retrieval call near the start of `nl_to_sql()`.
3. Skip retrieval when RAG is disabled or user/db context is unavailable.
4. Add `_build_messages(rag_context: str = "")` prepending behavior to static schema prompt.
5. Keep static prompt examples intact (RAG additive only).
6. Ensure benchmark path remains static-only.
7. Verify both call sites (`chat.py`, `query.py`) pass readonly DB sessions to retrieval.

**PRD requirements fulfilled:** FR-08, FR-09
**Depends on:** Phase 3

**Done when**
- Retrieval context is injected only when available and valid.
- Empty/failure retrieval gracefully falls back to static prompt.
- Readonly session usage is consistent across both call sites.
- Existing backend tests still pass.

---

## Phase 5 — Chat Router Store Integration (Non-Blocking)
**Goal:** Store successful query pairs without impacting SSE reliability.

**Files to create**
- None

**Files to modify**
- `backend/app/api/v1/chat.py`

**Tasks**
1. Add `current_user` dependency to relevant query/chat execution endpoints.
2. After successful execution with `row_count > 0`, trigger fire-and-forget store call.
3. Use executor-based wrapper for sync path.
4. Create a fresh `SessionLocal()` inside the thread wrapper (never share request-scoped session across threads).
5. Ensure retrieval continues using readonly sessions, while store path uses read-write session.
6. Catch/log all background-store failures without breaking SSE/event flow.

**PRD requirements fulfilled:** FR-10, NFR performance and reliability
**Depends on:** Phase 4

**Done when**
- No store call happens for `row_count == 0`.
- SSE stream remains non-blocking and stable even if storage fails.
- Threaded DB access uses independent session lifecycle.
- Existing backend tests still pass.

---

## Phase 6 — Backend Test Coverage for Feature 14
**Goal:** Add and update tests to validate RAG behavior and safety constraints.

**Files to create**
- `backend/tests/test_rag.py` (or equivalent dedicated Feature 14 test file)

**Files to modify**
- `backend/tests/conftest.py`
- Existing tests that call `nl_to_sql()` / chat query execution paths

**Tasks**
1. Add unit tests for dedup behavior.
2. Add unit tests for tenant-isolated retrieval.
3. Add unit tests for retrieval fallback paths.
4. Add integration coverage for non-blocking store trigger in chat flow.
5. Add coverage for benchmark static-only behavior.

**PRD requirements fulfilled:** FR-05 through FR-10 verification
**Depends on:** Phase 5

**Done when**
- New Feature 14 tests pass.
- Existing backend tests still pass.
- Key NFRs (fallback, isolation, non-blocking behavior) are covered.

---

## Phase 7 — Mandatory Documentation and Status Updates (Final)
**Goal:** Complete documentation updates as a required final phase.

**Files to create**
- None

**Files to modify**
- `instructions/features.md`
- `README.md`
- `instructions/feature 14/feature14_prd.md` (if implementation notes or status updates are required)

**Tasks**
1. Update Feature 14 status from planned to implemented.
2. Document new migration, module, config flags, and operational behavior.
3. Add notes on tenant isolation and fallback behavior.
4. Ensure docs reflect benchmark static-only behavior.

**PRD requirements fulfilled:** Delivery documentation obligations
**Depends on:** Phase 6

**Done when**
- Documentation changes are committed with final implementation.
- Feature status and behavior descriptions are accurate.
- This phase remains final and is not deferred.
- Existing backend tests still pass.
