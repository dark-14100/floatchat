# FloatChat — Feature 11: API Layer
## Product Requirements Document (PRD)

**Feature Name:** API Layer
**Version:** 1.0
**Status:** ⏳ Ready for Development
**Depends On:** Feature 10 (Dataset Management — `is_public` column on `datasets` must exist before API key scoping can be enforced), Feature 13 (Auth — API key creation endpoints require JWT auth; `users` table must exist for the `api_keys` FK), GDAC Auto-Sync (all data acquisition must be complete so the public API reflects a current dataset)
**Blocks:** Feature 12 (System Monitoring — `/metrics` endpoint must not be behind API key rate limiting; this requires Feature 11's middleware to exist first so Feature 12 can exclude it correctly)

---

## 1. Purpose & Background

### 1.1 What Problem Does This Solve?
FloatChat's query engine, dataset search, geospatial endpoints, and anomaly feed are all fully built and running. But they are currently only accessible to users authenticated via JWT — meaning only users with a FloatChat account who log in via the browser. External research tools, scripts, Jupyter notebooks, and third-party integrations cannot access FloatChat's capabilities programmatically.

Feature 11 opens FloatChat to external programmatic access by adding API key authentication as an alternative to JWT, rate limiting to prevent abuse, and formal OpenAPI documentation so external developers can understand and integrate the API. The endpoints themselves do not change — this feature is entirely an access and documentation layer on top of what already exists.

### 1.2 What This Feature Is
Three additive layers on top of the existing, fully functional FastAPI infrastructure:

1. **API Key Authentication** — a new `api_keys` table, endpoints for key management, and middleware that accepts `X-API-Key` as an alternative to Bearer JWT on all public endpoints
2. **Rate Limiting** — `slowapi` middleware enforcing per-key and per-user request limits with standard rate limit response headers
3. **OpenAPI Documentation** — full annotation of all existing endpoints with descriptions, schemas, and error codes; API key authentication documented in the security scheme

### 1.3 What This Feature Is Not
- It does not add new data endpoints — all endpoints already exist and are tested
- It does not change how JWT authentication works for browser users — JWT continues to work exactly as before for all existing users
- It does not expose admin endpoints (`/api/v1/admin/*`) to API key holders — admin endpoints remain JWT-only
- It does not expose the `/metrics` Prometheus endpoint through the rate limiter — Feature 12 handles that endpoint separately
- It does not add a developer portal UI — API key management is done via the existing admin panel and via authenticated API calls

### 1.4 Security Model
API key holders are scoped to `is_public = true` datasets only, regardless of the role of the user who created the key. This is a hard constraint: even an admin who creates an API key cannot use that key to access internal datasets. The `is_public` flag set in Feature 10 is the sole mechanism controlling external API data visibility.

API keys are single-use secrets: the plaintext key is returned exactly once at creation time and never stored. Only the SHA-256 hash is persisted in the database. A lost key must be revoked and a new one created.

### 1.5 Relationship to Feature 10
Feature 10 introduced `is_public` on the `datasets` table. Feature 11 is the enforcement mechanism — without Feature 11's middleware, `is_public` has no effect on external access. Feature 11 must be built after Feature 10 is complete.

### 1.6 Relationship to Feature 12
Feature 12 (System Monitoring) adds a `GET /metrics` Prometheus scrape endpoint that must not be rate-limited and must not require API key auth. Feature 12 is aware of this constraint and handles the exclusion, but it depends on Feature 11's middleware existing first so it knows what to exclude.

---

## 2. Goals & Success Criteria

### 2.1 Goals
- Allow external research tools and scripts to access FloatChat's NL query engine and dataset endpoints programmatically
- Prevent API abuse through per-key and per-user rate limiting
- Give external developers clear, accurate documentation for every public endpoint
- Ensure API key holders can never access internal datasets regardless of who created the key
- Keep the path to first API call short — create a key, read the docs, make a call

### 2.2 Success Criteria

| Criterion | Target |
|---|---|
| API key creation to first successful API call | < 5 minutes with documentation |
| Rate limit enforcement accuracy | 100% — no requests succeed above the configured limit |
| `is_public` scoping enforcement | API key requests return zero results from internal datasets |
| OpenAPI docs completeness | Every public endpoint has summary, description, request schema, response schema, and error codes documented |
| JWT users unaffected | All existing JWT-authenticated flows work identically after this feature ships |
| Admin endpoints inaccessible via API key | 401 or 403 returned for all `/api/v1/admin/*` requests with `X-API-Key` |
| Plaintext key stored | Never — only SHA-256 hash in database |

---

## 3. User Stories

### 3.1 External Developer / Researcher
- **US-01:** As a researcher with a Python script, I want to query FloatChat's NL engine using an API key instead of a JWT, so I can automate oceanographic data queries without browser authentication.
- **US-02:** As a developer, I want to read complete OpenAPI documentation for every endpoint at `/docs`, so I know exactly what to send and what to expect in return.
- **US-03:** As a developer, I want clear error messages when I exceed the rate limit, including a `Retry-After` header, so my script can back off and retry automatically.
- **US-04:** As a developer, I want to create, list, and revoke API keys via the API itself, so I can manage key rotation programmatically.

### 3.2 Admin
- **US-05:** As an admin, I want to be able to override the default rate limit for specific API keys, so I can give trusted integrations higher throughput without changing the global limit.
- **US-06:** As an admin, I want all API key requests to be scoped to public datasets only, so internal datasets are never accessible via programmatic API regardless of who created the key.

### 3.3 Existing Browser User
- **US-07:** As an existing browser user authenticated via JWT, I want my experience to be completely unchanged by this feature — no new login prompts, no rate limit changes, no broken flows.

---

## 4. Functional Requirements

### 4.1 Database

**FR-01 — `api_keys` Table**
Create a new `api_keys` table:
- `key_id` — UUID primary key, default `gen_random_uuid()`
- `key_hash` — VARCHAR(64), not null, unique — SHA-256 hash of the plaintext API key (hex-encoded, 64 characters)
- `user_id` — UUID, not null, foreign key to `users.user_id` ON DELETE CASCADE — key is owned by the creating user; key is revoked automatically if user is deleted
- `name` — VARCHAR(100), not null — human-readable label for the key (e.g. "Jupyter notebook", "Lab script")
- `is_active` — BOOLEAN, not null, default `true`
- `created_at` — TIMESTAMPTZ, not null, default `now()`
- `last_used_at` — TIMESTAMPTZ, nullable — updated on every authenticated request using this key
- `rate_limit_override` — INTEGER, nullable — requests per minute; if null, the global default applies

B-tree indexes on: `key_hash` (unique, used on every authenticated request), `user_id` (for listing a user's keys).

**FR-02 — Migration**
Alembic migration `009_api_layer.py` with `down_revision = "008"`. Creates the `api_keys` table and all indexes. Down migration drops the table and indexes cleanly. Does not include `GRANT SELECT ON api_keys TO floatchat_readonly` — API key records are not queryable by the NL engine.

### 4.2 Backend: API Key Management Endpoints

All key management endpoints live in `backend/app/api/v1/auth.py` (the existing auth router) and require JWT authentication (`get_current_user`). API keys cannot be used to create or revoke other API keys — key management is JWT-only.

**FR-03 — `POST /api/v1/auth/api-keys`**
Creates a new API key for the authenticated user. Request body: `{ "name": string }`. Process:
1. Generate a cryptographically secure random key (32 bytes, URL-safe base64 encoded — produces a 43-character string prefixed with `fck_` for easy identification, e.g. `fck_<43chars>`)
2. Compute the SHA-256 hash of the full key string
3. Insert a new `api_keys` row with the hash, user_id, name
4. Return the full response including the plaintext key exactly once: `{ "key_id": "...", "name": "...", "key": "fck_...", "created_at": "..." }`

The response must include a clear warning that the plaintext key is shown only once and cannot be retrieved again.

**FR-04 — `GET /api/v1/auth/api-keys`**
Lists all API keys for the authenticated user. Returns: `key_id`, `name`, `is_active`, `created_at`, `last_used_at`, `rate_limit_override`. Never returns the `key_hash` or any derivation of the plaintext key.

**FR-05 — `DELETE /api/v1/auth/api-keys/{key_id}`**
Revokes an API key. Sets `is_active = false`. Does not delete the row — preserves the audit trail. Returns 404 if `key_id` does not belong to the authenticated user. Returns 409 if already inactive.

**FR-06 — `PATCH /api/v1/auth/api-keys/{key_id}`**
Updates a key's `name` or `rate_limit_override`. Admin-only for `rate_limit_override` changes (non-admins can only update `name`). Returns 404 if key does not belong to the authenticated user.

### 4.3 Backend: API Key Authentication Middleware

**FR-07 — `X-API-Key` Header Resolution**
Create a new FastAPI dependency `get_api_key_or_user` that:
1. Checks for `X-API-Key` header first
2. If present: SHA-256 hashes the provided value, looks up `api_keys` where `key_hash = hash AND is_active = true`
3. If found: updates `last_used_at = now()` asynchronously (fire-and-forget, non-blocking), returns the associated `User` object with an additional `api_key_scoped: true` flag
4. If not found or inactive: returns 401 with `{ "detail": "Invalid or inactive API key" }`
5. If `X-API-Key` header absent: falls through to standard JWT Bearer token resolution (existing `get_current_user` behaviour)

This dependency replaces `get_current_user` on all public endpoints. Existing admin endpoints keep `get_current_admin_user` unchanged — API keys never satisfy the admin dependency.

**FR-08 — Public Dataset Scoping for API Key Requests**
When a request is authenticated via API key (`api_key_scoped: true`), all database queries that touch the `datasets` table must additionally filter `datasets.is_public = true`. This scoping is applied in the dependency layer — the endpoint code does not need to check; the dependency injects a scoped database session or a scoping context that the query layer respects.

The exact implementation mechanism (scoped session, query interceptor, or context variable) is to be determined during gap analysis based on how existing queries are structured. The key constraint: API key scoping must be enforced centrally, not scattered across individual endpoints.

**FR-09 — Endpoints Updated to Use New Dependency**
The following existing endpoints are updated to use `get_api_key_or_user` instead of `get_current_user`:
- `POST /api/v1/query`
- `GET /api/v1/datasets/search`
- `GET /api/v1/profiles/{profile_id}/chart-data`
- `POST /api/v1/export`
- `GET /api/v1/floats/{wmo_id}`
- `GET /api/v1/map/*` (all map endpoints)
- `GET /api/v1/anomalies`

Admin endpoints (`/api/v1/admin/*`), auth endpoints (`/api/v1/auth/*`), and chat/SSE endpoints (`/api/v1/chat/*`) are explicitly excluded — they retain `get_current_user` or `get_current_admin_user` as before.

### 4.4 Backend: Rate Limiting

**FR-10 — `slowapi` Integration**
Install `slowapi` and configure it as FastAPI middleware. The rate limiter uses Redis as the backend store (already running for Celery). Rate limit keys are constructed from the API key `key_id` (for API key requests) or the user `user_id` (for JWT requests) — not from IP address, which would break shared environments.

**FR-11 — Default Rate Limits**
- API key requests: 100 requests per minute per `key_id`
- JWT user requests: 300 requests per minute per `user_id`
- Per-key override: if `api_keys.rate_limit_override` is not null, that value replaces the 100 req/min default for that key

**FR-12 — Rate Limit Response Headers**
Every response from a rate-limited endpoint includes:
- `X-RateLimit-Limit` — the applicable limit (100 or 300 or override value)
- `X-RateLimit-Remaining` — requests remaining in the current window
- `X-RateLimit-Reset` — Unix timestamp when the window resets

**FR-13 — 429 Response**
When rate limit is exceeded: HTTP 429 with body `{ "detail": "Rate limit exceeded", "retry_after": N }` and `Retry-After: N` header (seconds until window resets).

**FR-14 — Excluded Endpoints**
The following endpoints are excluded from rate limiting entirely:
- `GET /api/v1/health` (Feature 12 health check — not yet built but must be excluded when added)
- `GET /metrics` (Feature 12 Prometheus endpoint — same)
- All `/api/v1/auth/*` endpoints (login, signup, token refresh — rate limiting these separately is a security feature, not in scope here)

### 4.5 Backend: OpenAPI Documentation

**FR-15 — Endpoint Annotations**
Every public endpoint listed in FR-09 must have the following OpenAPI annotations added:
- `summary` — one-line description
- `description` — full description including what the endpoint does, what parameters it accepts, and what it returns
- `response_model` — explicit Pydantic response model (or update existing ones to be complete)
- `responses` — explicit documentation for all possible HTTP status codes: 200, 400, 401, 403, 404, 422, 429, 500 where applicable
- `tags` — appropriate tag grouping (e.g. "Queries", "Datasets", "Floats", "Map", "Anomalies", "Export")

**FR-16 — Security Scheme**
The OpenAPI security scheme must document both authentication methods:
- `BearerAuth` — JWT Bearer token in `Authorization` header
- `ApiKeyAuth` — API key in `X-API-Key` header

Both schemes are listed as alternatives (OR, not AND) on all endpoints in FR-09.

**FR-17 — API Key Scoping Note**
Every endpoint in FR-09 must include a note in its `description` field: "When authenticated with an API key, results are automatically scoped to public datasets only (`is_public = true`)."

**FR-18 — Swagger UI and ReDoc**
Both `/docs` (Swagger UI) and `/redoc` (ReDoc) are enabled. Both are accessible without authentication (the docs themselves are public; the endpoints they describe require auth). The docs include a "Getting Started" section describing how to obtain an API key and how to authenticate.

### 4.6 Integration Test Suite

**FR-19 — API Key Auth Tests**
- Create API key via JWT → receive plaintext key → use key on protected endpoint → succeed
- Use revoked key → 401
- Use invalid key → 401
- Use API key on admin endpoint → 403
- Key management endpoints reject API key auth (must use JWT)

**FR-20 — Dataset Scoping Tests**
- API key request for datasets → returns only `is_public = true` datasets
- API key request for NL query that references an internal dataset → returns empty or filtered results
- JWT request for same data → returns all accessible datasets (no public scoping)

**FR-21 — Rate Limit Tests**
- Exceed 100 req/min with API key → 429 on the 101st request
- `Retry-After` header present and accurate on 429 response
- Per-key override respected — key with `rate_limit_override = 200` allows 200 req/min
- JWT user at 300 req/min not affected by API key limit

**FR-22 — OpenAPI Schema Tests**
- `GET /docs` returns 200 (public access)
- `GET /openapi.json` returns valid OpenAPI 3.x schema
- All endpoints in FR-09 appear in the schema with security requirements

---

## 5. Non-Functional Requirements

### 5.1 Security
- Plaintext API key is never stored, logged, or returned after the creation response
- `key_hash` is computed using SHA-256 — collision-resistant, fast to compute on every request
- The `fck_` prefix on keys allows easy identification and automated secret scanning (GitHub, GitLab secret scanning can be configured to detect these)
- `last_used_at` updates are non-blocking (fire-and-forget) — they must not add latency to authenticated requests
- Timing-safe comparison must be used when comparing key hashes to prevent timing attacks

### 5.2 Performance
- API key resolution adds one DB query per request (hash lookup) — must be under 5ms with the `key_hash` unique index
- `last_used_at` updates are fire-and-forget — they do not block the response
- Rate limit checks use Redis — must be under 2ms per check
- No change to existing JWT authentication performance

### 5.3 Backward Compatibility
- All existing JWT-authenticated flows work identically after this feature ships
- No existing endpoint changes its response schema
- No existing test breaks — the dependency swap from `get_current_user` to `get_api_key_or_user` is backward-compatible for JWT tokens

### 5.4 Developer Experience
- OpenAPI docs are the primary integration guide — they must be accurate, complete, and include working examples
- API key format (`fck_` prefix) is easily identifiable and grep-able
- Error messages are specific enough to diagnose auth failures without exposing security details

---

## 6. File Structure

```
floatchat/
└── backend/
    ├── alembic/versions/
    │   └── 009_api_layer.py                   # New migration
    ├── app/
    │   ├── api/v1/
    │   │   ├── auth.py                        # Additive: API key management endpoints
    │   │   ├── query.py                       # Additive: swap dependency, add OpenAPI annotations
    │   │   ├── search.py                      # Additive: swap dependency, add OpenAPI annotations
    │   │   ├── map.py                         # Additive: swap dependency, add OpenAPI annotations
    │   │   ├── export.py                      # Additive: swap dependency, add OpenAPI annotations
    │   │   ├── anomalies.py                   # Additive: swap dependency, add OpenAPI annotations
    │   │   └── floats.py                      # Additive: swap dependency, add OpenAPI annotations
    │   ├── auth/
    │   │   └── dependencies.py                # Additive: get_api_key_or_user dependency
    │   ├── db/models.py                       # Additive: ApiKey ORM model
    │   ├── middleware/
    │   │   └── rate_limit.py                  # New: slowapi configuration and key extraction
    │   ├── main.py                            # Additive: slowapi middleware, security schemes
    │   └── config.py                          # Additive: rate limit config settings
    └── tests/
        ├── test_api_keys.py                   # Key management CRUD tests
        ├── test_api_key_auth.py               # Auth flow tests
        ├── test_rate_limiting.py              # Rate limit enforcement tests
        └── test_openapi_schema.py             # Schema completeness tests
```

---

## 7. Dependencies

| Dependency | Source | Status |
|---|---|---|
| `users` table | Feature 13 | ✅ Built |
| `get_current_user` dependency | Feature 13 | ✅ Built |
| `get_current_admin_user` dependency | Feature 13 | ✅ Built |
| `is_public` column on `datasets` | Feature 10 migration 008 | ✅ Built |
| Redis | Feature 1 / Celery | ✅ Running |
| FastAPI | Existing | ✅ Installed |
| `slowapi` | New pip dependency | ⏳ To install |
| `hashlib` (SHA-256) | Python stdlib | ✅ Available |
| `secrets` (key generation) | Python stdlib | ✅ Available |

---

## 8. Open Questions

| # | Question | Owner | Due |
|---|---|---|---|
| OQ1 | The `is_public` scoping for API key requests (FR-08) needs to be enforced centrally without modifying each endpoint. What is the best mechanism given the existing query structure — a context variable read by query helpers, a scoped SQLAlchemy session that adds the filter automatically, or a middleware that modifies the request state? The answer depends on how existing endpoint queries access the `datasets` table. | Architecture | Before FR-07/FR-08 implementation |
| OQ2 | `last_used_at` updates are fire-and-forget (FR-07). In FastAPI, this means using `BackgroundTasks` or `asyncio.create_task`. Which pattern is already in use in the codebase for background tasks that are not Celery? If neither is used, which is preferred? | Engineering | Before FR-07 implementation |
| OQ3 | The rate limit key is `key_id` for API key requests and `user_id` for JWT requests. `slowapi` typically uses a callable to extract the rate limit key from the request. Does the existing `slowapi` integration pattern support dynamic key extraction per request type, or does it require a custom key function? Confirm after reading `slowapi` documentation and existing middleware patterns. | Engineering | Before FR-10 implementation |
| OQ4 | Chat and SSE endpoints (`/api/v1/chat/*`) are excluded from API key auth. Should they also be excluded from rate limiting entirely, or should they have their own (separate, lower) rate limit given that SSE connections are long-lived and a single connection counts as one request? | Product | Before FR-10/FR-14 implementation |
| OQ5 | Should the `/docs` and `/redoc` pages be accessible without any authentication, or should they require at minimum a valid JWT or API key? Public docs are better for developer adoption; gated docs are better for keeping the API private. | Product | Before FR-18 implementation |
| OQ6 | The `DELETE /api/v1/auth/api-keys/{key_id}` endpoint sets `is_active = false` (soft revoke). Should there also be a hard delete option that removes the row entirely? Soft revoke preserves the audit trail but means the `api_keys` table grows indefinitely. | Product | Before FR-05 implementation |
| OQ7 | Rate limit storage in Redis uses the existing Redis instance (already running for Celery). Should the rate limit keys use a dedicated Redis database number (e.g. `db=1`) to avoid namespace collision with Celery task data, or is a key prefix (e.g. `ratelimit:`) sufficient? | Engineering | Before FR-10 implementation |
| OQ8 | The `PATCH /api/v1/auth/api-keys/{key_id}` endpoint allows admins to set `rate_limit_override`. Should non-admin users be able to set any `rate_limit_override` value at all (even a lower one to self-throttle), or should `rate_limit_override` be strictly admin-only? | Product | Before FR-06 implementation |
