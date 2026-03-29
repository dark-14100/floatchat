# Feature 11: API Layer — Implementation Phases

All confirmed gap analysis decisions are incorporated below.

---

## Phase 1 — Database Migration

**Goal:** Create the `api_keys` table so the ORM model and endpoints can use it.

**Files to create:**
- `backend/alembic/versions/009_api_layer.py`

**Tasks:**
1. Create migration with `revision = "009"`, `down_revision = "010"`
2. Create `api_keys` table: `key_id` (UUID PK), `key_hash` (VARCHAR(64) UNIQUE NOT NULL), `user_id` (UUID FK → users ON DELETE CASCADE), `name` (VARCHAR(100) NOT NULL), `is_active` (BOOLEAN default true), `created_at` (TIMESTAMPTZ default now()), `last_used_at` (TIMESTAMPTZ nullable), `rate_limit_override` (INTEGER nullable)
3. Create B-tree indexes: `ix_api_keys_key_hash` (unique), `ix_api_keys_user_id`
4. Expand `ck_admin_audit_log_action` CHECK to add `'api_key_created'`, `'api_key_revoked'`, `'api_key_updated'`
5. Expand `ck_admin_audit_log_entity_type` CHECK to add `'api_key'`
6. Down migration drops table, indexes, and reverts both CHECK constraints
7. No `GRANT SELECT TO floatchat_readonly`

**PRD requirements:** FR-01, FR-02

**Depends on:** Nothing

**Done when:**
- [ ] Migration file exists with correct `down_revision = "010"`
- [ ] All columns match FR-01 spec exactly
- [ ] CHECK constraints expanded
- [ ] Down migration is clean and reversible
- [ ] All existing tests still pass

---

## Phase 2 — ORM Model + Auth Dependency

**Goal:** Create `ApiKey` model and `get_api_key_or_user` dependency that existing endpoints can swap to.

**Files to modify:**
- `backend/app/db/models.py` — add `ApiKey` class, add `api_keys` relationship to `User`
- `backend/app/auth/dependencies.py` — add `get_api_key_or_user`, `get_optional_api_key_or_user`

**Tasks:**
1. Add `ApiKey` ORM model following existing conventions (Mapped[], mapped_column, UUID PK with default uuid4). Fields match FR-01 exactly. Relationship to `User`.
2. Add `api_keys` relationship on `User` model (one-to-many, cascade delete-orphan)
3. Update `AdminAuditLog` CHECK constraints in model to match migration 009
4. Create `get_api_key_or_user(request, db)`:
   - Check `X-API-Key` header
   - If present: SHA-256 hash → DB lookup by `key_hash` where `is_active = true` → `hmac.compare_digest` for timing-safe comparison → schedule `last_used_at` update via `run_in_executor` → set `request.state.api_key_scoped = True` and `request.state.rate_limit_key = f"apikey:{key_id}"` → return associated `User` ORM object
   - If absent: delegate to existing `get_current_user` → set `request.state.api_key_scoped = False` and `request.state.rate_limit_key = f"user:{user_id}"` → return `User`
   - If `X-API-Key` present but invalid/inactive: return 401 immediately (no JWT fallback)
5. Create `get_optional_api_key_or_user(request, db)` — same as above but returns `None` if neither header is present (for `search.py` anonymous access)

**PRD requirements:** FR-07 (partial)

**Depends on:** Phase 1

**Done when:**
- [ ] `ApiKey` model matches FR-01 columns
- [ ] `get_api_key_or_user` returns `User` ORM object (same as existing `get_current_user`)
- [ ] `request.state.api_key_scoped` is set correctly
- [ ] `last_used_at` update is non-blocking (fire-and-forget)
- [ ] `hmac.compare_digest` used for hash comparison
- [ ] JWT fallback works when no `X-API-Key` header
- [ ] Invalid API key returns 401 without JWT fallback
- [ ] All existing tests still pass

---

## Phase 3 — API Key Management Endpoints

**Goal:** CRUD endpoints for API key lifecycle — JWT-only, API keys cannot manage API keys.

**Files to modify:**
- `backend/app/api/v1/auth.py` — add 4 endpoints

**Tasks:**
1. `POST /api/v1/auth/api-keys` (FR-03): generate `fck_` + 43-char URL-safe base64, SHA-256 hash, insert row, return plaintext once with warning
2. `GET /api/v1/auth/api-keys` (FR-04): list user's keys — return `key_id`, `name`, `is_active`, `created_at`, `last_used_at`, `rate_limit_override`. Never return `key_hash`
3. `DELETE /api/v1/auth/api-keys/{key_id}` (FR-05): soft revoke (`is_active = false`). 404 if not owned by user. 409 if already inactive
4. `PATCH /api/v1/auth/api-keys/{key_id}` (FR-06): update `name` (any user) or `rate_limit_override` (admin only). 404 if not owned by user. 403 if non-admin tries to set `rate_limit_override`
5. All 4 endpoints require `Depends(get_current_user)` — JWT only
6. Add Pydantic request/response models for each endpoint

**PRD requirements:** FR-03, FR-04, FR-05, FR-06

**Depends on:** Phase 2

**Done when:**
- [ ] All 4 endpoints work with JWT auth
- [ ] Plaintext key returned exactly once (POST only)
- [ ] `key_hash` never in any response
- [ ] `rate_limit_override` is admin-only in PATCH
- [ ] Soft revoke preserves audit trail
- [ ] All existing tests still pass

---

## Phase 4 — `is_public` Dataset Scoping

**Goal:** Centralised enforcement — API key requests only see `is_public = true` datasets. Hybrid Approach A + C + validator.

**Files to modify:**
- `backend/app/query/schema_prompt.py` — add `get_schema_prompt(api_key_scoped)` wrapper
- `backend/app/query/pipeline.py` — accept `api_key_scoped` param, use modified prompt
- `backend/app/query/validator.py` — add `is_public` check for API-key-scoped SQL
- `backend/app/api/v1/query.py` — read `request.state.api_key_scoped`, pass to pipeline

**Tasks:**
1. Add `is_public` column to the `datasets` table description in `SCHEMA_PROMPT` (so LLM knows it exists)
2. Create `get_schema_prompt(api_key_scoped: bool)` — when `True`, appends absolute rule: *"MANDATORY: Any query that references the `datasets` table MUST include the filter `datasets.is_public = true`. This is a security constraint and must not be omitted."*
3. Update `nl_to_sql()` signature to accept `api_key_scoped: bool = False`, pass to `get_schema_prompt()`
4. Add post-processing validator: after SQL is generated, if `api_key_scoped = True` and SQL references `datasets` table, check that `is_public` appears in the SQL. If not, reject with error: *"Query references restricted datasets. API key access is limited to public datasets only."*
5. Update `query.py` to read `request.state.api_key_scoped` and pass to `nl_to_sql()`
6. For `search.py` scoping: handled in Phase 6 via the search service reading the flag

**PRD requirements:** FR-08

**Depends on:** Phase 2

**Done when:**
- [ ] `SCHEMA_PROMPT` mentions `is_public` column
- [ ] `get_schema_prompt(True)` appends scoping rule
- [ ] `nl_to_sql()` uses scoped prompt when `api_key_scoped = True`
- [ ] Post-processing validator rejects SQL without `is_public` when required
- [ ] Test: API key query referencing datasets → SQL includes `is_public = true`
- [ ] Test: JWT query → no scoping applied
- [ ] All existing tests still pass

---

## Phase 5 — Rate Limiting

**Goal:** Identity-based rate limiting with Redis backend.

**Files to modify:**
- `backend/app/rate_limiter.py` — custom key function, Redis storage
- `backend/app/config.py` — add rate limit settings
- `backend/app/main.py` — exclude endpoints, ensure response headers

**Tasks:**
1. Add to `config.py`: `API_KEY_RATE_LIMIT: int = 100`, `JWT_USER_RATE_LIMIT: int = 300`, `RATE_LIMIT_STORAGE_URI: str` (defaults to `REDIS_URL`)
2. Replace `get_remote_address` in `rate_limiter.py` with `get_rate_limit_key(request)` — reads `request.state.rate_limit_key`, falls back to IP
3. Configure `slowapi` Redis storage with `ratelimit:` key prefix
4. In `main.py`: ensure `SlowAPIMiddleware` is configured. Exclude `/api/v1/auth/*`, `/api/v1/chat/*`, future `/health`, future `/metrics` from rate limiting
5. Ensure `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers on all responses (FR-12)
6. Ensure 429 response includes `Retry-After` header and `{"detail": "Rate limit exceeded", "retry_after": N}` body (FR-13)

**PRD requirements:** FR-10, FR-11, FR-12, FR-13, FR-14

**Depends on:** Phase 2

**Done when:**
- [ ] Rate limit key is `key_id` or `user_id`, never IP (except unauthenticated)
- [ ] API key: 100 req/min default, overridable by `rate_limit_override`
- [ ] JWT user: 300 req/min
- [ ] `X-RateLimit-*` headers present
- [ ] 429 response correct
- [ ] Chat/SSE endpoints excluded
- [ ] Auth endpoints excluded
- [ ] All existing tests still pass

---

## Phase 6 — Endpoint Dependency Swaps

**Goal:** Swap `get_current_user` → `get_api_key_or_user` on all public endpoints. Apply `is_public` scoping in search service.

**Files to modify:**
- `backend/app/api/v1/query.py` — swap router dependency
- `backend/app/api/v1/search.py` — add `get_optional_api_key_or_user` to GET endpoints, add `is_public` filter in search service
- `backend/app/api/v1/map.py` — swap router dependency
- `backend/app/api/v1/export.py` — swap router + endpoint dependencies
- `backend/app/api/v1/anomalies.py` — swap per-endpoint dependencies

**Tasks:**
1. `query.py`: change router `dependencies=[Depends(get_current_user)]` → `dependencies=[Depends(get_api_key_or_user)]`. Update endpoint `current_user` parameter type.
2. `search.py`: add `get_optional_api_key_or_user` as optional dependency to GET endpoints. When `request.state.api_key_scoped = True`, add `Dataset.is_public == True` filter. Preserve anonymous access.
3. `map.py`: swap router dependency. No dataset scoping needed.
4. `export.py`: swap router and endpoint dependencies.
5. `anomalies.py`: swap per-endpoint `Depends(get_current_user)` → `Depends(get_api_key_or_user)`.
6. **Not changed:** `admin.py`, `auth.py` (JWT-only), `chat.py` (excluded), `clarification.py` (excluded), `ingestion.py` (admin-only via old auth module)

**PRD requirements:** FR-09

**Depends on:** Phase 2 (dependency), Phase 4 (scoping both verified)

**Done when:**
- [ ] All 5 endpoint files updated
- [ ] JWT tokens still work on all swapped endpoints (backward compatibility)
- [ ] API key works on all swapped endpoints
- [ ] API key rejected on admin, auth, chat, clarification, ingestion endpoints
- [ ] `search.py` anonymous access preserved
- [ ] `search.py` applies `is_public` filter for API key requests
- [ ] All existing tests still pass

---

## Phase 7 — OpenAPI Annotations

**Goal:** Full endpoint documentation with dual security schemes.

**Files to modify:**
- `backend/app/main.py` — security schemes, always-on docs, OpenAPI metadata
- All FR-09 endpoint files — `summary`, `description`, `responses`, `tags`

**Tasks:**
1. In `main.py`: add `BearerAuth` (JWT) and `ApiKeyAuth` (`X-API-Key`) security schemes to OpenAPI config
2. Remove `DEBUG` gating on `/docs` and `/redoc` — always public
3. Update OpenAPI `title`, `description`, `version`
4. Add `summary`, `description`, `responses` (200, 400, 401, 422, 429, etc.) to every endpoint in FR-09 files
5. Add `is_public` scoping note to every FR-09 endpoint description (FR-17)
6. Add `tags` where missing

**PRD requirements:** FR-15, FR-16, FR-17, FR-18

**Depends on:** Phase 6

**Done when:**
- [ ] `/docs` loads without auth
- [ ] Both security schemes visible in Swagger UI
- [ ] Every FR-09 endpoint has summary, description, responses
- [ ] `is_public` scoping note present
- [ ] All existing tests still pass

---

## Phase 8 — Integration Tests

**Goal:** Comprehensive test coverage for all Feature 11 functionality.

**Files to create:**
- `backend/tests/test_api_keys.py` — key management CRUD (FR-19)
- `backend/tests/test_api_key_auth.py` — auth flows + `is_public` scoping (FR-20)
- `backend/tests/test_rate_limiting.py` — rate limit enforcement (FR-21)
- `backend/tests/test_openapi_schema.py` — schema completeness (FR-22)

**Tasks:**
1. `test_api_keys.py`: create via JWT → receive plaintext → use on endpoint → succeed. Revoked key → 401. Invalid key → 401. API key on admin endpoint → 403. Key management rejects API key auth.
2. `test_api_key_auth.py`: API key returns only `is_public = true` datasets. JWT returns all. NL query with API key → generated SQL includes `is_public`.
3. `test_rate_limiting.py`: 429 after limit exceeded. `Retry-After` header present. Per-key override respected. JWT not affected by API key limit. (Redis mocked.)
4. `test_openapi_schema.py`: `/docs` returns 200. `/openapi.json` valid. All FR-09 endpoints in schema with security.

**PRD requirements:** FR-19, FR-20, FR-21, FR-22

**Depends on:** Phases 1–7

**Done when:**
- [ ] All new tests pass
- [ ] All existing tests still pass
- [ ] Zero regressions

---

## Phase 9 — Documentation

**Goal:** Update all project docs. Feature is not complete until this is done.

**Files to modify:**
- `instructions/features.md` — mark Feature 11 as complete
- API developer guide (new or existing) — getting started, key creation, auth, rate limits
- `README.md` — if applicable

**Tasks:**
1. Update `features.md` Feature 11 status
2. Write API developer guide with: key creation flow, authentication headers, rate limit rules, `is_public` scoping explanation, error codes
3. Update `README.md` if needed

**PRD requirements:** Hard Rule 12

**Depends on:** Phases 1–8

**Done when:**
- [ ] `features.md` updated
- [ ] Developer guide complete
- [ ] All documentation accurate
