# FloatChat — Feature 13 Implementation Phases

## Phase 1 — Alembic Migration
**Goal:** Create `users` and `password_reset_tokens` tables with rollback support.

**Files to create**
- `backend/alembic/versions/005_auth.py`

**Files to modify**
- `backend/app/db/models.py` — add `User` and `PasswordResetToken` models

**Tasks**
1. Add `User` ORM model.
2. Add `PasswordResetToken` ORM model.
3. Create migration `005_auth.py` with `down_revision = "004"`.
4. Create `users` table + unique index on `email`.
5. Create `password_reset_tokens` table + index on `token_hash`.
6. Add migration comment: FK on `chat_sessions.user_identifier` deferred to v2 pending anonymous session cleanup.
7. Implement downgrade to drop both tables.
8. Validate migration upgrade and downgrade.

**PRD requirements fulfilled:** FR-01, FR-02, FR-03
**Depends on:** None

**Done when**
- Upgrade succeeds.
- Downgrade succeeds.
- Both tables are created/dropped as expected.
- Existing backend tests still pass.

---

## Phase 2 — Config + Dependencies + Rate Limiting Setup
**Goal:** Add auth settings and backend package/middleware prerequisites.

**Files to create**
- None

**Files to modify**
- `backend/app/config.py` — add Feature 13 settings and JWT secret validation
- `backend/requirements.txt` — add `passlib`, `bcrypt`, `slowapi`
- `backend/app/main.py` — register SlowAPI middleware

**Tasks**
1. Add `JWT_SECRET_KEY` (new separate setting; do not rename existing `SECRET_KEY`).
2. Add `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, `JWT_REFRESH_TOKEN_EXPIRE_DAYS`, `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES`, `FRONTEND_URL`.
3. Add startup validation for `JWT_SECRET_KEY` (present and length >= 32).
4. Add missing backend dependencies.
5. Register SlowAPI middleware.

**PRD requirements fulfilled:** FR-16, NFR security/rate-limiting prerequisites, Hard Rule 9
**Depends on:** Phase 1

**Done when**
- Backend fails startup for missing/short `JWT_SECRET_KEY`.
- Backend starts with valid `JWT_SECRET_KEY`.
- Dependencies install cleanly.
- Existing backend tests still pass.

---

## Phase 3 — Auth Module (`app/auth/`)
**Goal:** Build reusable JWT, password, dependency, and email utilities.

**Files to create**
- `backend/app/auth/__init__.py`
- `backend/app/auth/jwt.py`
- `backend/app/auth/passwords.py`
- `backend/app/auth/dependencies.py`
- `backend/app/auth/email.py`

**Files to modify**
- None

**Tasks**
1. Implement token create/decode with type validation.
2. Implement bcrypt hashing/verify utilities.
3. Implement `get_current_user` and `get_current_admin_user` dependencies.
4. Implement reset-email sender with stdout logging path.
5. Add TODO note for production SendGrid/SMTP replacement.

**PRD requirements fulfilled:** FR-12, FR-13, FR-14 (module layer), FR-10 (email infrastructure behavior)
**Depends on:** Phase 2

**Done when**
- Access/refresh token validation enforces token type.
- Password hash/verify works.
- User/admin dependencies raise correct auth/role errors.
- Email reset link logging works via structlog.
- Existing backend tests still pass.

---

## Phase 4 — Auth Router (`/api/v1/auth`)
**Goal:** Implement all auth endpoints and session migration behavior.

**Files to create**
- `backend/app/api/v1/auth.py`

**Files to modify**
- `backend/app/main.py` — register auth router

**Tasks**
1. Implement `/signup`, `/login`, `/logout`, `/me`, `/refresh`, `/forgot-password`, `/reset-password`.
2. Apply rate limits (10/min per IP) on `/signup`, `/login`, `/forgot-password`.
3. Implement session migration on login/signup when `X-User-ID` is present.
4. Keep migration fire-and-forget; log failure, do not fail auth response.
5. Ensure forgot-password always returns identical 200 response.
6. `/refresh` returns both `access_token` and `user` object.
7. Add comment that admin role assignment is DB-only in v1.

**PRD requirements fulfilled:** FR-05 through FR-11, FR-17
**Depends on:** Phase 3

**Done when**
- All 7 endpoints function per spec.
- Cookies and response shapes match requirements.
- Session migration runs conditionally and safely.
- Existing backend tests still pass.

---

## Phase 5 — Protect Existing Routers (High-Risk Additive Changes)
**Goal:** Add auth dependencies to `chat`, `query`, and `map` without breaking existing functionality.

**Files to create**
- `backend/tests/conftest.py` updates/fixtures as needed for auth token generation

**Files to modify**
- `backend/app/api/v1/chat.py` — require authenticated user on all endpoints
- `backend/app/api/v1/query.py` — require authenticated user on all endpoints
- `backend/app/api/v1/map.py` — require authenticated user on all endpoints
- Existing tests touching these routers — inject real auth headers using fixture

**Tasks**
1. Add `get_current_user` dependency to all endpoints in the 3 routers.
2. Replace `_get_user_id()` ownership pattern in `chat.py` with `current_user.user_id`.
3. Ensure `POST /chat/sessions` writes `current_user.user_id` as `user_identifier`.
4. Remove runtime dependency on `X-User-ID` from `chat.py` after this phase.
5. Keep search/public endpoints unchanged.
6. Update tests to use real generated token fixture (no dependency mocks).

**PRD requirements fulfilled:** FR-15, Hard Rule 6
**Depends on:** Phase 4

**Done when**
- Protected endpoints return 401 without token and succeed with valid token.
- Chat ownership uses authenticated `user_id` only.
- Updated tests pass with real tokens.
- Existing backend tests still pass.

---

## Phase 6 — Backend Auth Test Suite
**Goal:** Add dedicated backend test coverage for Feature 13.

**Files to create**
- `backend/tests/test_auth_api.py`

**Files to modify**
- `backend/tests/conftest.py` (if additional fixtures required)

**Tasks**
1. Implement full auth endpoint tests from PRD test list.
2. Add session migration test coverage.
3. Add protected-route auth enforcement tests.

**PRD requirements fulfilled:** Backend testing scope in Feature 13 PRD
**Depends on:** Phase 5

**Done when**
- Auth tests pass.
- Existing backend tests still pass.

---

## Phase 7 — Frontend Auth Types + Store
**Goal:** Establish frontend auth state model and in-memory token store.

**Files to create**
- `frontend/types/auth.ts`
- `frontend/store/authStore.ts`

**Files to modify**
- None

**Tasks**
1. Add User/auth response/request types.
2. Build Zustand auth store (`currentUser`, `accessToken`, `isAuthenticated`, `setAuth`, `clearAuth`, `setAccessToken`).
3. Keep access token memory-only.

**PRD requirements fulfilled:** FR-24, Hard Rule 1
**Depends on:** None

**Done when**
- Type checks pass.
- Build passes.

---

## Phase 8 — Frontend Route Protection Middleware
**Goal:** Protect routes using cookie-presence proxy auth logic.

**Files to create**
- `frontend/middleware.ts`

**Files to modify**
- None

**Tasks**
1. Add public-route allowlist (`/login`, `/signup`, `/forgot-password`, `/reset-password`).
2. Redirect unauthenticated access to protected routes -> `/login?redirect=...`.
3. Redirect authenticated access to auth pages -> `/chat`.

**PRD requirements fulfilled:** FR-22
**Depends on:** Phase 7

**Done when**
- Route redirects behave correctly in local testing.
- Type checks and build pass.

---

## Phase 9 — Shared Auth UI Components
**Goal:** Build reusable auth page components from design spec.

**Files to create**
- `frontend/components/auth/AuthCard.tsx`
- `frontend/components/auth/PasswordInput.tsx`
- `frontend/components/auth/PasswordStrength.tsx`

**Files to modify**
- None

**Tasks**
1. Implement shared auth card wrapper and wordmark.
2. Implement password input with show/hide toggle.
3. Implement password strength indicator.
4. Ensure all styling uses existing tokens; no hardcoded colors.

**PRD requirements fulfilled:** FR-18 to FR-21 UI building blocks, design spec §9
**Depends on:** Phase 8

**Done when**
- Components render in light/dark mode correctly.
- Type checks and build pass.

---

## Phase 10 — Auth Pages
**Goal:** Build `/login`, `/signup`, `/forgot-password`, `/reset-password` pages.

**Files to create**
- `frontend/app/login/page.tsx`
- `frontend/app/signup/page.tsx`
- `frontend/app/forgot-password/page.tsx`
- `frontend/app/reset-password/page.tsx`

**Files to modify**
- None

**Tasks**
1. Implement all page flows and validation.
2. Add loading/error/success states per spec.
3. Implement reset token query-param handling.
4. Add session migration success toast only when migrated count > 0.

**PRD requirements fulfilled:** FR-18, FR-19, FR-20, FR-21
**Depends on:** Phase 9

**Done when**
- Flows function correctly in light/dark mode.
- Type checks and build pass.

---

## Phase 11 — API Client Auth Integration
**Goal:** Move request auth to bearer token + reactive refresh.

**Files to create**
- None

**Files to modify**
- `frontend/lib/api.ts`
- `frontend/lib/mapQueries.ts`

**Tasks**
1. Add bearer token header from auth store.
2. Add reactive refresh-on-401, retry once.
3. On repeated 401, clear auth and redirect to login.
4. Ensure migration-window behavior still sends `X-User-ID` where required for login/signup requests.

**PRD requirements fulfilled:** FR-23, FR-17 integration requirement
**Depends on:** Phase 10

**Done when**
- Authenticated API calls succeed with bearer token.
- Refresh/retry flow works.
- Type checks and build pass.

---

## Phase 12 — Sidebar + Layout/Auth Initializer Integration
**Goal:** Integrate auth UX into app shell and logout behavior.

**Files to create**
- Any small client initializer component only if needed by implementation

**Files to modify**
- `frontend/components/layout/SessionSidebar.tsx`
- `frontend/app/layout-shell.tsx`

**Tasks**
1. Add user profile block in sidebar with avatar initials + name + logout.
2. Logout flow: call backend logout, `clearAuth()`, remove `floatchat_user_id` from localStorage, redirect to `/login`.
3. Ensure auth pages render without sidebar/nav.
4. Add auth initialization at app-shell level (silent refresh on mount).

**PRD requirements fulfilled:** FR-25, FR-23 bootstrap behavior, gap F6
**Depends on:** Phase 11

**Done when**
- Sidebar shows authenticated user profile and logout works end-to-end.
- Anonymous UUID is cleared on logout.
- Auth page layout rules are respected.
- Type checks and build pass.

---

## Phase 13 — Frontend Tests
**Goal:** Add frontend auth/middleware/store/component test coverage.

**Files to create**
- Frontend auth test files under `frontend/tests/` as needed

**Files to modify**
- Existing frontend test setup files if needed

**Tasks**
1. Add middleware redirect behavior tests.
2. Add auth-store and refresh-flow tests.
3. Add password input/strength and key page behavior tests.
4. Add logout and redirect behavior tests.

**PRD requirements fulfilled:** Frontend testing scope in Feature 13 PRD
**Depends on:** Phase 12

**Done when**
- Frontend auth tests pass.
- `tsc --noEmit` passes.
- `npm run build` passes.
