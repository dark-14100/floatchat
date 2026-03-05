# FloatChat — Feature 13: Authentication & User Management
## Product Requirements Document (PRD)

**Feature Name:** Authentication & User Management
**Version:** 1.0
**Status:** Ready for Development
**Depends On:** Features 1–7 (all existing features must be running before auth is added)
**Blocks:** Feature 8 (Export), Feature 14 (RAG Pipeline), Feature 15 (Anomaly Detection), Feature 10 (Dataset Management)

---

## 1. Purpose & Background

### 1.1 What Problem Does This Solve?
FloatChat currently operates with anonymous sessions identified by a browser-generated UUID stored in localStorage. This approach was acceptable for v1 development but has three critical limitations:

- Sessions are browser-local — a researcher loses their entire conversation history if they clear their browser cache, switch devices, or use a different browser
- There is no concept of user identity — the RAG Pipeline (Feature 14) cannot provide tenant-isolated query history without knowing who is querying
- There is no access control — any user can access any endpoint, and the admin-only Dataset Management feature (Feature 10) cannot be protected

Feature 13 adds JWT-based authentication that gives every researcher a persistent account, ties all their sessions and future query history to their identity, and enables role-based access control for administrative functions.

### 1.2 What This Feature Is
A complete authentication system consisting of:
- Backend: user table, JWT token generation and validation, protected route middleware, five auth endpoints
- Frontend: login page, signup page, forgot password page, route protection middleware, user profile in sidebar

### 1.3 What This Feature Is Not
- It is not a third-party auth provider integration (no Clerk, Auth0, NextAuth, Google OAuth, or GitHub OAuth in v1)
- It is not a multi-tenancy system — organisation/workspace management is out of scope for v1
- It is not a permissions system beyond two roles (researcher and admin)
- It does not implement two-factor authentication in v1

### 1.4 Why Build It Now
Auth sits at this point in the build sequence because every feature that follows needs user identity. The RAG Pipeline needs `user_id` to scope query history per user. Anomaly Detection needs `user_id` to know who to notify. Dataset Management needs admin role enforcement. Building auth now means all subsequent features are built with identity context from day one rather than retrofitting it later.

---

## 2. Goals & Success Criteria

### 2.1 Goals
- Give every researcher a persistent account so their sessions survive browser changes and device switches
- Protect all data-producing endpoints from unauthenticated access
- Enable admin-only access to dataset management and administrative functions
- Migrate existing anonymous sessions to authenticated sessions on first login
- Provide a login and signup experience that matches the FloatChat design system exactly

### 2.2 Success Criteria

| Criterion | Target |
|---|---|
| Login endpoint response time (p95) | < 300ms |
| JWT validation middleware overhead | < 5ms per request |
| Signup to first query time | < 60 seconds |
| Session migration on first login | 100% of anonymous sessions linked |
| Password reset email delivery | < 2 minutes |
| Token refresh (silent) | Invisible to user — no loading state |

---

## 3. User Stories

### 3.1 Researcher
- **US-01:** As a researcher, I want to create an account so that my conversation history persists across devices and browser sessions.
- **US-02:** As a researcher, I want to log in with my email and password so that I can access my previous conversations.
- **US-03:** As a researcher, I want my anonymous sessions to be preserved when I create an account, so that I don't lose conversations I had before signing up.
- **US-04:** As a researcher, I want to reset my password via email if I forget it.
- **US-05:** As a researcher, I want to see my name and a logout button in the sidebar so that I know I am logged in and can log out when needed.
- **US-06:** As a researcher, I want to be redirected to my previous page after logging in, so that authentication does not interrupt my workflow.

### 3.2 Admin
- **US-07:** As an admin, I want my admin role to be enforced automatically so that only I can access dataset management and ingestion controls.
- **US-08:** As an admin, I want to see researcher accounts in a simple user list (future Feature 10 scope — auth just needs to support the role).

---

## 4. Functional Requirements

### 4.1 Backend: Database

**FR-01 — `users` Table**
Create a new `users` table with the following columns:
- `user_id` — UUID primary key, server-generated
- `email` — VARCHAR, unique, not null, lowercase-normalised on write
- `hashed_password` — VARCHAR, not null
- `name` — VARCHAR, not null
- `role` — VARCHAR, not null, default `researcher`, allowed values: `researcher`, `admin`
- `created_at` — TIMESTAMP WITH TIME ZONE, not null, default now()
- `is_active` — BOOLEAN, not null, default true
- Index on `email` (unique index)

**FR-02 — `password_reset_tokens` Table**
Create a `password_reset_tokens` table:
- `token_id` — UUID primary key, server-generated
- `user_id` — UUID, foreign key to `users.user_id`, CASCADE DELETE
- `token_hash` — VARCHAR, not null (store hash of the token, not the token itself)
- `expires_at` — TIMESTAMP WITH TIME ZONE, not null (tokens expire after 1 hour)
- `used` — BOOLEAN, not null, default false
- Index on `token_hash`

**FR-03 — Migration**
Alembic migration file `005_auth.py` with `down_revision = "004"`. Migration must include both tables and all indexes. Down migration must drop both tables cleanly.

**FR-04 — `chat_sessions` Table Update**
Add a foreign key from `chat_sessions.user_identifier` to `users.user_id`. This is an additive migration change — the column already exists. After migration, `user_identifier` accepts either a browser UUID (for legacy anonymous sessions) or a `user_id` UUID from the `users` table. The column type does not change.

### 4.2 Backend: Auth Endpoints

All auth endpoints are mounted at `/api/v1/auth/`. They do not require authentication except `GET /me` and `POST /logout`.

**FR-05 — `POST /api/v1/auth/signup`**
Request body: `name` (string, required), `email` (string, required, validated as email format), `password` (string, required, minimum 8 characters).

Processing:
- Normalise email to lowercase
- Check if email already exists — return HTTP 409 with message `"An account with this email already exists"` if so
- Hash password using bcrypt via passlib
- Insert new user with role `researcher`
- Generate access token (JWT, 15 minute expiry) and refresh token (JWT, 7 day expiry)
- Set refresh token in httpOnly cookie (`floatchat_refresh`, SameSite=Lax, Secure in production, path=`/api/v1/auth`)
- Return: `user_id`, `name`, `email`, `role`, and `access_token` in response body

**FR-06 — `POST /api/v1/auth/login`**
Request body: `email` (string, required), `password` (string, required).

Processing:
- Normalise email to lowercase
- Look up user by email — return HTTP 401 with message `"Invalid email or password"` if not found (do not reveal which field is wrong)
- Verify password against stored hash — return HTTP 401 with same message if mismatch
- Check `is_active` — return HTTP 403 with message `"Account is deactivated"` if false
- Generate new access token and refresh token
- Set refresh token in httpOnly cookie (same settings as signup)
- Return: `user_id`, `name`, `email`, `role`, and `access_token` in response body

**FR-07 — `POST /api/v1/auth/logout`**
Requires valid access token. Clears the `floatchat_refresh` cookie by setting it with an expired date. Returns HTTP 200 with `"Logged out successfully"`. No token blacklist in v1 — access tokens expire naturally after 15 minutes.

**FR-08 — `GET /api/v1/auth/me`**
Requires valid access token. Returns the current user's profile: `user_id`, `name`, `email`, `role`, `created_at`. Does not return `hashed_password`. Returns HTTP 401 if token is missing or invalid.

**FR-09 — `POST /api/v1/auth/refresh`**
Does not require access token. Reads the `floatchat_refresh` httpOnly cookie. Validates the refresh token (signature, expiry). Returns a new access token in the response body. Returns HTTP 401 if the cookie is missing or the refresh token is invalid or expired. This endpoint is called silently by the frontend when an access token expires.

**FR-10 — `POST /api/v1/auth/forgot-password`**
Request body: `email` (string, required). Always returns HTTP 200 regardless of whether the email exists — never reveal whether an account exists. If the email exists: generate a random token, hash it, store in `password_reset_tokens` with 1-hour expiry, send reset email with a link containing the raw token. Email sending uses the same notification infrastructure as Feature 10 (SendGrid or SMTP). If email infrastructure is not yet available, log the reset link to stdout at INFO level in development.

**FR-11 — `POST /api/v1/auth/reset-password`**
Request body: `token` (string, required), `new_password` (string, required, minimum 8 characters). Look up the token by hashing it and querying `password_reset_tokens`. Return HTTP 400 if not found, already used, or expired. If valid: update the user's `hashed_password`, mark the token as `used = true`, clear all refresh cookies for that user (by convention — no token blacklist). Return HTTP 200.

### 4.3 Backend: JWT Middleware

**FR-12 — Access Token Structure**
JWT payload: `sub` (user_id as string), `email`, `role`, `type` (value: `access`), `exp` (expiry timestamp). Signed with `settings.JWT_SECRET_KEY` using HS256 algorithm.

**FR-13 — Refresh Token Structure**
JWT payload: `sub` (user_id as string), `type` (value: `refresh`), `exp`. Signed with same secret.

**FR-14 — JWT Validation Dependency**
Create a FastAPI dependency `get_current_user(token: str = Depends(oauth2_scheme))` that:
- Decodes and validates the JWT
- Returns the user object fetched from the database
- Raises HTTP 401 with `"Could not validate credentials"` on any failure (expired, invalid signature, malformed)

Create a second dependency `get_current_admin_user()` that calls `get_current_user()` and additionally checks `user.role == "admin"` — raises HTTP 403 with `"Admin access required"` if not.

**FR-15 — Protected Routes**
Add `get_current_user` as a dependency on all endpoints in:
- `app/api/v1/chat.py` — all chat session and message endpoints
- `app/api/v1/query.py` — all query and benchmark endpoints
- `app/api/v1/map.py` — all geospatial endpoints
- Any future export router

Add `get_current_admin_user` as a dependency on any future admin endpoints.

No endpoints from Features 1–3 (search, discovery) require auth — they remain public read endpoints.

**FR-16 — New Config Settings**
Add to `Settings` class in `backend/app/config.py`:
- `JWT_SECRET_KEY` — no default, must be set in environment, raise error on startup if missing
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` — default `15`
- `JWT_REFRESH_TOKEN_EXPIRE_DAYS` — default `7`
- `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES` — default `60`
- `FRONTEND_URL` — default `http://localhost:3000` — used to construct password reset links in emails

### 4.4 Backend: Session Migration

**FR-17 — Anonymous Session Migration**
When a user logs in or signs up, the backend checks if a `user_identifier` header is present in the request (the frontend sends the current browser UUID as `X-User-ID`). If present: update all `chat_sessions` rows where `user_identifier = {browser_uuid}` to `user_identifier = {user_id}`. This is a one-time migration per user. After migration, the browser UUID in localStorage is cleared — all subsequent requests use the JWT.

### 4.5 Frontend: Auth Pages

**FR-18 — Login Page (`/login`)**
Full-page layout with no sidebar. Background illustration visible at higher opacity per design spec §9.1. Centered card (max-width 420px) containing:
1. FloatChat wordmark (`Fraunces` font, `Waves` icon)
2. Tagline: "Ocean data, in plain English."
3. Email input with label
4. Password input with label and show/hide toggle
5. Inline error message below the form (not per-field) in `--color-danger`
6. "Sign in" primary button (full width)
7. "Forgot password?" ghost text link — navigates to `/forgot-password`
8. Divider line with "or" text
9. "Create an account" secondary button (full width) — navigates to `/signup`

Loading state on submit: button shows spinner icon (`Loader2` from lucide-react), form fields disabled.

**FR-19 — Signup Page (`/signup`)**
Same card layout as login. Contains:
1. FloatChat wordmark and tagline
2. Name input with label
3. Email input with label
4. Password input with label, show/hide toggle, and strength indicator (weak/fair/strong based on length and character variety)
5. Inline error message below the form
6. "Create account" primary button (full width)
7. "Already have an account? Sign in" ghost text link — navigates to `/login`

On successful signup: redirect to `/chat` (new session created automatically).

**FR-20 — Forgot Password Page (`/forgot-password`)**
Same card layout. Contains:
1. FloatChat wordmark and tagline
2. "Reset your password" heading
3. Brief instruction: "Enter your email and we'll send you a reset link."
4. Email input
5. "Send reset link" primary button (full width)
6. "Back to sign in" ghost text link

On submit: replace form with confirmation state — "If an account exists for that email, you'll receive a reset link shortly." No spinner or loading state that reveals whether the email exists.

**FR-21 — Reset Password Page (`/reset-password`)**
Reached via link in reset email containing the token as a query parameter. Card layout. Contains:
1. FloatChat wordmark
2. "Set a new password" heading
3. New password input with strength indicator
4. Confirm password input — inline error if passwords don't match
5. "Set new password" primary button
On success: redirect to `/login` with a success message: "Password updated. Please sign in."
On invalid/expired token: show error card — "This reset link is invalid or has expired. Request a new one."

**FR-22 — Route Protection Middleware**
Next.js middleware at `middleware.ts` in the frontend root. Intercepts all requests. Rules:
- If accessing `/login`, `/signup`, `/forgot-password`, or `/reset-password` while authenticated: redirect to `/chat`
- If accessing any other route while unauthenticated: redirect to `/login?redirect={current_path}`
- Public routes that do not require auth: `/login`, `/signup`, `/forgot-password`, `/reset-password`
- After login: if a `redirect` query param exists, navigate there instead of `/chat`

**FR-23 — Access Token Management (Frontend)**
The access token is stored in memory (JavaScript variable in an auth context or Zustand auth slice) — never in localStorage or sessionStorage. On page load, immediately call `POST /api/v1/auth/refresh` using the httpOnly cookie — if successful, store the returned access token in memory and proceed. If the refresh call fails (cookie missing or expired): redirect to `/login`.

All API calls (in `lib/api.ts` and `lib/mapQueries.ts`) include the access token as `Authorization: Bearer {token}` header. If any API call returns HTTP 401, silently attempt a token refresh and retry the original request once. If the retry also returns 401, clear auth state and redirect to `/login`.

**FR-24 — Auth Zustand Slice**
Add to `chatStore.ts` or create a separate `authStore.ts`:
- `currentUser: User | null` — the authenticated user profile
- `accessToken: string | null` — in-memory only
- `isAuthenticated: boolean`
- `setAuth(user, token)` — sets both
- `clearAuth()` — clears both, called on logout

**FR-25 — User Profile in Sidebar**
Add to `SessionSidebar.tsx` at the bottom of the sidebar (below the Dashboard and Map links):
- Divider line
- User avatar: circle with user's initials (first letter of first name + first letter of last name) in `--color-ocean-primary` background, white text
- User's name in `--text-sm` `--font-medium`
- Logout button: ghost icon button with `LogOut` icon from lucide-react, positioned to the right of the name
- On logout: call `POST /api/v1/auth/logout`, call `clearAuth()`, redirect to `/login`

This replaces the anonymous state that currently shows no user info in the sidebar.

---

## 5. Non-Functional Requirements

### 5.1 Security
- Passwords stored only as bcrypt hashes — never logged or returned in any API response
- Refresh tokens stored in httpOnly cookies — not accessible to JavaScript
- Access tokens short-lived (15 minutes) to limit exposure if intercepted
- Reset tokens stored only as hashes — the raw token exists only in the email link and briefly in memory
- All auth endpoints rate-limited: 10 requests per minute per IP for `/login`, `/signup`, `/forgot-password`
- Email normalised to lowercase before storage and lookup — prevents duplicate accounts via case variation
- JWT secret key must be a minimum of 32 characters — validated on startup

### 5.2 Performance
- JWT validation middleware adds < 5ms overhead per request
- Login endpoint responds in < 300ms including database lookup and bcrypt verify
- Silent token refresh is invisible to the user — no UI loading state

### 5.3 Backward Compatibility
- All existing anonymous sessions remain accessible — the migration is additive, not destructive
- The `user_identifier` column on `chat_sessions` retains its existing browser UUID values until a user logs in and migration runs
- No existing Feature 1–6 functionality is broken by adding auth — search and discovery endpoints remain public

---

## 6. Design Specification References

All auth pages follow the FloatChat design spec (`floatchat_design_spec.md`) exactly. Key references:
- §2.1 and §2.2 — color tokens for light and dark mode
- §3 — typography (Fraunces wordmark, DM Sans body)
- §5 — background illustration treatment (more prominent on auth pages — wave opacity 25–30% in light mode)
- §6.1 — primary and secondary button styles
- §6.2 — input and textarea styles including focus rings
- §6.3 — card styles (background, border-radius, shadow)
- §9 — auth page layouts (login §9.1, signup §9.2, plus forgot password and reset password follow the same card pattern)
- §10 — dark mode implementation (theme toggle must remain available on auth pages)
- §13 — accessibility (form labels, focus management, ARIA attributes on error messages)

---

## 7. File Structure

```
floatchat/
├── backend/
│   ├── app/
│   │   ├── auth/
│   │   │   ├── __init__.py
│   │   │   ├── jwt.py          # Token generation and validation
│   │   │   ├── passwords.py    # bcrypt hashing utilities
│   │   │   ├── dependencies.py # get_current_user, get_current_admin_user
│   │   │   └── email.py        # Password reset email sending
│   │   └── api/
│   │       └── v1/
│   │           └── auth.py     # All 7 auth endpoints
│   └── tests/
│       └── test_auth_api.py
└── frontend/
    ├── middleware.ts               # Route protection
    ├── app/
    │   ├── login/
    │   │   └── page.tsx
    │   ├── signup/
    │   │   └── page.tsx
    │   ├── forgot-password/
    │   │   └── page.tsx
    │   └── reset-password/
    │       └── page.tsx
    ├── components/
    │   └── auth/
    │       ├── AuthCard.tsx        # Shared card wrapper for all auth pages
    │       ├── PasswordInput.tsx   # Input with show/hide toggle
    │       └── PasswordStrength.tsx # Strength indicator component
    └── store/
        └── authStore.ts            # Auth Zustand slice
```

Files to modify (additive only):
- `backend/app/config.py` — add 5 new auth settings
- `backend/app/main.py` — register auth router
- `backend/app/db/models.py` — add User and PasswordResetToken ORM models
- `backend/app/api/v1/chat.py` — add `get_current_user` dependency to all endpoints
- `backend/app/api/v1/query.py` — add `get_current_user` dependency to all endpoints
- `backend/app/api/v1/map.py` — add `get_current_user` dependency to all endpoints
- `frontend/components/layout/SessionSidebar.tsx` — add user profile section
- `frontend/lib/api.ts` — add Authorization header and silent refresh logic
- `frontend/lib/mapQueries.ts` — add Authorization header

---

## 8. Testing Requirements

### 8.1 Backend Tests (`test_auth_api.py`)
- `POST /signup` with valid data creates user and returns access token
- `POST /signup` with duplicate email returns HTTP 409
- `POST /signup` with password under 8 characters returns HTTP 422
- `POST /login` with correct credentials returns access token and sets cookie
- `POST /login` with wrong password returns HTTP 401
- `POST /login` with unknown email returns HTTP 401 (same message as wrong password)
- `POST /login` with deactivated account returns HTTP 403
- `GET /me` with valid token returns user profile
- `GET /me` with expired token returns HTTP 401
- `GET /me` with no token returns HTTP 401
- `POST /refresh` with valid cookie returns new access token
- `POST /refresh` with missing cookie returns HTTP 401
- `POST /logout` clears the refresh cookie
- `POST /forgot-password` with known email returns HTTP 200
- `POST /forgot-password` with unknown email returns HTTP 200 (same response)
- `POST /reset-password` with valid token updates password and marks token used
- `POST /reset-password` with expired token returns HTTP 400
- `POST /reset-password` with already-used token returns HTTP 400
- Protected endpoint (`GET /chat/sessions`) without token returns HTTP 401
- Protected endpoint with valid token returns data
- Admin endpoint without admin role returns HTTP 403
- Session migration: anonymous sessions linked to user on login

### 8.2 Frontend Tests
- Unauthenticated user navigating to `/chat` is redirected to `/login`
- Authenticated user navigating to `/login` is redirected to `/chat`
- After login, redirect to `?redirect` path if present
- Logout clears auth state and redirects to `/login`
- Silent token refresh called on page load
- Failed refresh redirects to `/login`
- Password inputs show/hide toggle works
- Password strength indicator shows correct level

---

## 9. Migration Number

This is migration `005`. The existing migration sequence is:
- `001` — initial schema (Features 1 and 2)
- `002` — pgvector and embeddings (Feature 3)
- `003` — chat sessions and messages (Feature 5)
- `004` — chat messages addendum (Feature 5 continuation)

Migration `005_auth.py` adds `users` and `password_reset_tokens` tables and the FK update to `chat_sessions.user_identifier`.

---

## 10. Open Questions

| # | Question | Owner | Due |
|---|---|---|---|
| Q1 | Is SendGrid or SMTP the email provider for password reset emails? If neither is configured yet, the reset link should be logged to stdout in development. | Infrastructure | Before reset-password implementation |
| Q2 | Should the admin role be assignable only via database directly (acceptable for v1) or via an admin UI endpoint? | Product | Before Feature 10 build |
| Q3 | Should session migration run silently on login, or should the user be informed that their previous conversations have been linked? A brief "Your previous conversations have been linked to your account" toast would be good UX. | Product | Before session migration implementation |
| Q4 | Token refresh strategy: should the frontend proactively refresh the access token before it expires (e.g. at 12 minutes), or reactively on first 401? Proactive is smoother UX. | Frontend | Before auth store implementation |
| Q5 | Should `is_active` user deactivation be manageable from the admin UI (Feature 10), or only via direct database access in v1? | Product | Before Feature 10 build |
