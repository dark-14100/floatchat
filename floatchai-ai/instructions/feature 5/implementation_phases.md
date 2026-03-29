# Feature 5 — Conversational Chat Interface: Implementation Phases

**Status:** Phase 10 complete — Feature 5 DONE  
**Created:** 2026-02-28  
**Last Updated:** 2026-02-28  
**Total Phases:** 10  
**Tests:** 396 passing (283 existing + 68 Feature 5 backend + 45 Feature 5 frontend)

---

## Gap Resolutions (All 13 Confirmed)

| # | Gap | Resolution |
|---|---|---|
| A1 | `execute_safe_query` → `execute_sql` | Use `execute_sql` — actual codebase name |
| A2 | `estimate_row_count` → `estimate_rows` | Use `estimate_rows` — actual codebase name |
| B1 | `interpreting` event content | Brief query-intent template + SQL. Full `interpret_results()` goes into `results` event after execution |
| C1 | `awaiting_confirmation` event type | Add it to discriminated union. Required when row estimate exceeds threshold |
| D1 | Confirmation endpoint design | Store SQL server-side in `chat_messages`. Confirm by `message_id`. Frontend never sends SQL |
| Q2 | `user_identifier` | Browser UUID in localStorage, sent as `X-User-ID` header |
| Q3 | Sidebar session cap | Unlimited with CSS overflow scroll |
| Q4 | Follow-up LLM provider | Same as Feature 4 (`QUERY_LLM_PROVIDER`) |
| Q5 | Show SQL to user | Collapsible `<details>` block, collapsed by default, label "View SQL" |
| F1 | CORS middleware | Add `CORSMiddleware` to `main.py` with `CORS_ORIGINS` config setting |
| F2 | `NEXT_PUBLIC_API_URL` | Add to `frontend/.env.local.example` |
| F3 | SSE library | Raw `StreamingResponse` — no `sse-starlette` |
| I1 | Frontend Docker | Skip for v1. Document `npm run dev` in README |

---

## Phase 1 — Configuration & Database Schema
**Status:** ✅ Complete

### Tasks
1. Add 6 new settings to `Settings` class in `backend/app/config.py`:
   - `CHAT_SUGGESTIONS_CACHE_TTL_SECONDS` — default `3600`
   - `CHAT_SUGGESTIONS_COUNT` — default `6`
   - `CHAT_MESSAGE_PAGE_SIZE` — default `50`
   - `FOLLOW_UP_LLM_TEMPERATURE` — default `0.7`
   - `FOLLOW_UP_LLM_MAX_TOKENS` — default `150`
   - `CORS_ORIGINS` — default `"http://localhost:3000"` (comma-separated string)
2. Add `ChatSession` model to `backend/app/db/models.py`:
   - Table: `chat_sessions`
   - Columns: `session_id` (UUID PK), `user_identifier` (VARCHAR nullable), `name` (VARCHAR nullable), `created_at` (TIMESTAMPTZ default now), `last_active_at` (TIMESTAMPTZ updated on each message), `is_active` (BOOLEAN default true), `message_count` (INTEGER default 0)
   - Relationship: `messages` → `ChatMessage`, `lazy="dynamic"`, `cascade="all, delete-orphan"`
3. Add `ChatMessage` model to `backend/app/db/models.py`:
   - Table: `chat_messages`
   - Columns: `message_id` (UUID PK), `session_id` (UUID FK → chat_sessions CASCADE), `role` (VARCHAR), `content` (TEXT), `nl_query` (TEXT nullable), `generated_sql` (TEXT nullable), `result_metadata` (JSONB nullable), `follow_up_suggestions` (JSONB nullable), `error` (JSONB nullable), `status` (VARCHAR nullable — `pending_confirmation` | `confirmed` | `completed` | `error`), `created_at` (TIMESTAMPTZ default now)
   - Index: `(session_id, created_at)`
   - Relationship back to `ChatSession`
4. Create migration `backend/alembic/versions/004_chat_interface.py`:
   - `down_revision = "003"`
   - `upgrade()`: create both tables + composite index
   - `downgrade()`: drop `chat_messages` first (FK), then `chat_sessions`
5. Add Feature 5 section to `backend/.env.example` with all 6 new settings

### Verification
- `alembic upgrade head` succeeds
- Both tables exist in PostgreSQL
- `alembic downgrade -1` cleanly removes them

### Files Modified
- `backend/app/config.py` — add 6 settings
- `backend/app/db/models.py` — add 2 models
- `backend/.env.example` — add Feature 5 section

### Files Created
- `backend/alembic/versions/004_chat_interface.py`

---

## Phase 2 — Chat Modules (Suggestions + Follow-Ups)
**Status:** ✅ Complete

### Tasks
1. Create `backend/app/chat/__init__.py` (empty)
2. Create `backend/app/chat/suggestions.py` with `generate_load_time_suggestions(db, redis_client, settings)`:
   - Check Redis key `chat_suggestions` — return cached if found
   - Call `get_all_summaries(db)` from `app.search.discovery`
   - If datasets exist: build 4–6 example queries from dataset variables, regions, date ranges (at least one spatial, one temporal, one variable-specific). Each is `{"query": str, "description": str}`
   - If no datasets: return 4 hardcoded Argo fallback suggestions
   - Cache in Redis with TTL from `settings.CHAT_SUGGESTIONS_CACHE_TTL_SECONDS`
   - Never raise — catch all exceptions, log with structlog, return fallbacks
3. Create `backend/app/chat/follow_ups.py` with `generate_follow_up_suggestions(nl_query, sql, column_names, row_count, settings)`:
   - Get LLM client via `get_llm_client(settings.QUERY_LLM_PROVIDER, settings)` from `app.query.pipeline`
   - Build prompt: given query, SQL, columns, row_count → generate 2–3 follow-up questions
   - Temperature: `settings.FOLLOW_UP_LLM_TEMPERATURE`, max tokens: `settings.FOLLOW_UP_LLM_MAX_TOKENS`
   - Parse response into `list[str]` (2–3 items)
   - Never raise — catch all exceptions, log, return `[]`

### Verification
- Import and call both functions in a Python shell
- `generate_load_time_suggestions` returns 4–6 dicts
- `generate_follow_up_suggestions` returns 2–3 strings (or `[]` on failure)

### Files Created
- `backend/app/chat/__init__.py`
- `backend/app/chat/suggestions.py`
- `backend/app/chat/follow_ups.py`

---

## Phase 3 — Chat Router: Session CRUD + Message History
**Status:** ✅ Complete

### Tasks
1. Create `backend/app/api/v1/chat.py` with `router = APIRouter(prefix="/chat", tags=["Chat"])`
2. Implement Pydantic request/response schemas for all endpoints
3. Implement session endpoints (FR-04):
   - `POST /sessions` — create session. Accept optional `name`, `X-User-ID` header. Return `session_id`, `created_at`
   - `GET /sessions` — list sessions filtered by `X-User-ID` header, `is_active=True`, ordered by `last_active_at` desc
   - `GET /sessions/{session_id}` — get session details (404 if not found or inactive)
   - `PATCH /sessions/{session_id}` — rename session
   - `DELETE /sessions/{session_id}` — soft delete (`is_active = false`)
4. Implement message history (FR-05): `GET /sessions/{session_id}/messages` with cursor pagination (`limit` default 50, `before_message_id`). Return ascending `created_at` order
5. Add `CORSMiddleware` to `backend/app/main.py` — read `CORS_ORIGINS` from settings, split on comma, pass to `allow_origins`. Allow methods `["*"]`, allow headers `["*"]`
6. Register chat router in `backend/app/main.py`: `app.include_router(chat_router, prefix="/api/v1")`

### Verification
- All CRUD endpoints respond correctly via Swagger at `/docs`
- Session list filters by `X-User-ID`
- Soft delete hides from list but preserves messages
- Message history returns paginated results in ascending order

### Files Created
- `backend/app/api/v1/chat.py`

### Files Modified
- `backend/app/main.py` — add CORS middleware + chat router

---

## Phase 4 — SSE Query Endpoint + Confirmation + Suggestions Endpoint
**Status:** ✅ Complete

### Tasks
1. Implement SSE query endpoint (FR-06) in `backend/app/api/v1/chat.py`: `POST /sessions/{session_id}/query`
   - Validate session exists and is active (HTTP 404 otherwise)
   - Persist user message to `chat_messages` (with `nl_query` set)
   - Return `StreamingResponse(media_type="text/event-stream")`
   - SSE generator yields events in sequence:
     - `event: thinking` → `{"status": "thinking"}`
     - Call `resolve_geography()`, `get_context()`, `nl_to_sql()` (imported directly from `app.query.*`)
     - On pipeline error → yield `event: error` + `event: done`, persist error message, return
     - `event: interpreting` → `{"interpretation": "<brief query-intent template>", "sql": "<generated_sql>"}`
     - Call `estimate_rows()` — if above threshold and `confirm=False` → persist assistant message with `status="pending_confirmation"` and `generated_sql` → yield `event: awaiting_confirmation` + `event: done`, return
     - `event: executing` → `{"status": "executing"}`
     - Call `execute_sql()` with readonly DB session. Time the execution
     - On execution error → yield `event: error` + `event: done`, persist error, return
     - Call `interpret_results()` for full natural-language interpretation
     - `event: results` → full payload: `rows`, `columns`, `row_count`, `truncated`, `sql`, `interpretation`, `execution_time_ms`, `attempt_count`
     - Call `generate_follow_up_suggestions()` — non-blocking, short timeout
     - `event: suggestions` → `{"suggestions": [str, str, str]}`
     - Persist assistant message to `chat_messages` with all result metadata + suggestions
     - Update `chat_sessions.last_active_at` + increment `message_count`
     - Store context via `append_context()` (user turn + assistant turn)
     - `event: done` → `{"status": "done"}`
   - All events: `data: {json}\n\n` format. Catch all exceptions → yield `event: error` before closing
2. Implement confirmation endpoint (FR-09): `POST /sessions/{session_id}/query/confirm`
   - Accept `message_id` in request body
   - Retrieve assistant message by `message_id`, verify `status="pending_confirmation"` and `generated_sql` is set
   - Return SSE stream: skip thinking/interpreting, go directly to executing → results → suggestions → done
   - Update message `status` to `"confirmed"` then `"completed"` after execution
3. Implement suggestions endpoint (FR-08): `GET /suggestions`
   - Call `generate_load_time_suggestions(db, redis_client, settings)`
   - Return `{"suggestions": [...]}`

### Verification
- `curl` POST to `/sessions/{id}/query` — SSE events arrive in correct order
- Error flow: invalid query yields error + done
- Confirmation flow: `awaiting_confirmation` fires for large estimates, confirm endpoint executes stored SQL
- Suggestions endpoint returns 4–6 items

### Files Modified
- `backend/app/api/v1/chat.py` — add SSE query, confirmation, suggestions endpoints

---

## Phase 5 — Backend Tests
**Status:** ✅ Complete

### Tasks
1. Create `backend/tests/test_chat_api.py`:
   - `POST /sessions` returns 201 with `session_id`
   - `GET /sessions` returns sessions filtered by user
   - `GET /sessions/{id}/messages` returns paginated messages in ascending order
   - SSE stream emits `thinking` as first event
   - SSE stream emits `done` as final event
   - SSE stream emits `error` event when `nl_to_sql` returns a validation failure
   - SSE stream emits `awaiting_confirmation` when estimate exceeds threshold
   - Confirmation endpoint retrieves stored SQL and executes
   - Soft delete sets `is_active=false` without deleting messages
   - Message persisted to `chat_messages` after successful query
   - `X-User-ID` header isolation works
2. Create `backend/tests/test_suggestions.py`:
   - `generate_load_time_suggestions` returns 4–6 items
   - Second call within TTL returns cached result
   - Returns fallback suggestions when no datasets exist
   - `generate_follow_up_suggestions` returns 2–3 strings on success
   - `generate_follow_up_suggestions` returns `[]` on LLM failure — does not raise
   - `GET /api/v1/chat/suggestions` returns suggestions via API

### Verification
- `pytest tests/test_chat_api.py tests/test_suggestions.py -v` — all pass
- `pytest` (full suite) — existing 283 tests + new tests all pass

### Files Created
- `backend/tests/test_chat_api.py`
- `backend/tests/test_suggestions.py`

---

## Phase 6 — Frontend Scaffolding
**Status:** ✅ Complete

### Tasks
1. Initialize Next.js 14 project at `frontend/` with `npx create-next-app@14 --typescript --tailwind --app --src-dir=false`
2. Install packages: `zustand@4`, `react-markdown@9`, `remark-gfm@4`, `rehype-highlight@7`, `rehype-sanitize@6`, `lucide-react`
3. Initialize shadcn/ui: `npx shadcn-ui@latest init` (New York style, slate color)
4. Configure `tailwind.config.ts` and `next.config.ts`
5. Create `frontend/.env.local.example` with `NEXT_PUBLIC_API_URL=http://localhost:8000`
6. Create `frontend/types/chat.ts`: interfaces for `ChatSession`, `ChatMessage`, `ResultData`, `Suggestion`, `FollowUpSuggestion`, `SSEEvent` (discriminated union: thinking | interpreting | executing | results | suggestions | awaiting_confirmation | error | done). No `any` types
7. Create `frontend/lib/api.ts`: typed async functions — `createSession`, `listSessions`, `getSession`, `renameSession`, `deleteSession`, `getMessages`, `getLoadTimeSuggestions`. All send `X-User-ID` header from localStorage. All throw typed errors
8. Create `frontend/lib/sse.ts`: `createQueryStream(sessionId, query, confirm, onEvent, onError, onDone)` using `fetch` + `ReadableStream`. Returns `AbortController`. Handles chunked SSE parsing, auto-close on `event: done`
9. Create `frontend/store/chatStore.ts`: Zustand store with state (`sessions`, `activeSessionId`, `messages`, `isLoading`, `streamState`, `pendingInterpretation`, `loadTimeSuggestions`) and actions (`setSessions`, `addSession`, `setActiveSession`, `setMessages`, `appendMessage`, `updateLastMessage`, `setLoading`, `setStreamState`, `setLoadTimeSuggestions`). No async logic in store

### Verification
- `npm run dev` starts without errors
- `npm run build` succeeds
- TypeScript compiles with zero errors

### Files Created
- `frontend/` (entire scaffolded project)
- `frontend/types/chat.ts`
- `frontend/lib/api.ts`
- `frontend/lib/sse.ts`
- `frontend/store/chatStore.ts`
- `frontend/.env.local.example`

---

## Phase 7 — Layout + SessionSidebar
**Status:** ✅ Complete

### Tasks
1. Create `frontend/app/layout.tsx`: root layout with two-panel structure — left sidebar (280px fixed, collapsible below 768px via hamburger icon) + right main panel. Dark mode default. Generate and persist anonymous UUID in localStorage on first visit
2. Create `frontend/components/layout/SessionSidebar.tsx` per FR-18:
   - "FloatChat" branding at top
   - "New Conversation" button → calls `createSession()`, navigates to `/chat/{session_id}`
   - Scrollable session list (unlimited, CSS overflow) ordered by `last_active_at` desc
   - Each item: name (or "New conversation"), relative time, message count
   - Active session highlighted
   - Context menu (shadcn `DropdownMenu`) with Rename + Delete
   - Load sessions on mount, refresh on new session creation
   - Responsive: collapses to hamburger on <768px

### Verification
- Layout renders two-panel structure
- Sidebar loads sessions from API
- New Conversation creates a session and navigates
- Rename and delete work via context menu
- Hamburger toggle works on narrow viewport

### Files Created
- `frontend/app/layout.tsx`
- `frontend/components/layout/SessionSidebar.tsx`

---

## Phase 8 — Chat Components
**Status:** ✅ Complete

### Tasks
1. `frontend/components/chat/ChatInput.tsx` (FR-17): `<textarea>`, auto-resize up to 6 lines, Enter submits, Shift+Enter newline, disabled while `isLoading`, character count at >450 chars, exposes `ref`, placeholder "Ask about ocean data..."
2. `frontend/components/chat/LoadingMessage.tsx` (FR-20): accepts `streamState` prop. Animated dots for `thinking`, interpretation text for `interpreting`, indeterminate progress bar for `executing`. CSS animations only
3. `frontend/components/chat/ResultTable.tsx` (FR-14): HTML `<table>` with Tailwind, column sort, show first 100 rows + "Show more" toggle, horizontal scroll, `toFixed(4)` for numbers, `Intl.DateTimeFormat` for timestamps, amber highlight for `is_outlier`, "Truncated" badge with tooltip
4. `frontend/components/chat/SuggestedFollowUps.tsx` (FR-15): 2–3 clickable chips, `onSelect(query)` callback, render nothing if empty
5. `frontend/components/chat/SuggestionsPanel.tsx` (FR-16): grid of 4–6 cards from `getLoadTimeSuggestions()`, each with query + description, `onSelect(query)` callback, 4 hardcoded fallbacks on API failure
6. `frontend/components/chat/ChatMessage.tsx` (FR-13): discriminated rendering:
   - User: right-aligned plain text + avatar placeholder
   - Assistant success: Markdown interpretation, collapsible SQL (`<details>`/`<summary>` "View SQL"), `ResultTable`, `chartComponent?` slot, `mapComponent?` slot, `SuggestedFollowUps`, metadata line, Export button placeholder
   - Assistant awaiting_confirmation: interpretation + "Run this query" / "Cancel" buttons
   - Assistant error: error message + reformulation suggestion (FR-23 mapping) + "Try again" button
   - Assistant loading: renders `LoadingMessage`
   - Empty results: guidance per FR-24
7. `frontend/components/chat/ChatThread.tsx` (FR-12): scrollable area, load 50 messages on mount, auto-scroll to bottom, "Scroll to bottom" button, infinite scroll upward, empty state → `SuggestionsPanel`

### Verification
- Each component renders correctly with mock data
- `ChatInput` Enter/Shift+Enter behavior works
- `ResultTable` sorts and scrolls
- `ChatMessage` renders all 4 states
- `ChatThread` auto-scrolls and shows suggestions on empty

### Files Created
- `frontend/components/chat/ChatInput.tsx`
- `frontend/components/chat/LoadingMessage.tsx`
- `frontend/components/chat/ResultTable.tsx`
- `frontend/components/chat/SuggestedFollowUps.tsx`
- `frontend/components/chat/SuggestionsPanel.tsx`
- `frontend/components/chat/ChatMessage.tsx`
- `frontend/components/chat/ChatThread.tsx`

---

## Phase 9 — Page Routes + Full Integration
**Status:** ✅ Complete

### Tasks
1. `frontend/app/page.tsx` (FR-11): `redirect("/chat")`
2. `frontend/app/chat/page.tsx` (FR-11): on mount, call `createSession()`, then `router.push(/chat/${session_id})`
3. `frontend/app/chat/[session_id]/page.tsx`: main chat view composing all components:
   - Load session + messages on mount
   - Wire `ChatInput.onSubmit` → `createQueryStream()` → dispatch store actions as SSE events arrive
   - Wire `SuggestedFollowUps.onSelect` + `SuggestionsPanel.onSelect` → submit query
   - Wire confirmation buttons → confirmation SSE stream
   - Wire "Try again" → re-submit original query
   - `X-User-ID` header on all requests
   - ARIA live regions for loading state announcements
   - Keyboard navigation

### Verification
- Full end-to-end flow: open app → `/chat/{session_id}` → suggestion cards → click → SSE stream → loading states → results → follow-up chips → click → second query with context
- Sidebar reflects session activity
- New conversation, rename, delete all work

### Files Created
- `frontend/app/page.tsx`
- `frontend/app/chat/page.tsx`
- `frontend/app/chat/[session_id]/page.tsx`

---

## Phase 10 — Frontend Tests + Documentation
**Status:** ✅ Complete

### Tasks
1. Frontend component tests (Vitest + React Testing Library):
   - `ChatInput`: submits on Enter, newline on Shift+Enter, disabled when loading
   - `SuggestedFollowUps`: renders chips, click fires callback
   - `ResultTable`: correct row count, truncated badge, sort
   - `ChatThread`: empty state shows `SuggestionsPanel`
   - SSE stream: store updates through correct state sequence
2. Update `backend/README.md`: add Feature 5 section — new tables, endpoints, settings, migration instructions
3. Create `frontend/README.md`: setup instructions, architecture overview, component map
4. Update this file (`implementation_phases.md`): mark all phases complete

### Verification
- All frontend tests pass
- All backend tests pass (283 existing + new Feature 5 tests)
- `npm run build` succeeds with zero errors
- READMEs accurately document setup

### Files Created
- `frontend/README.md`

### Files Modified
- `backend/README.md`
- `instructions/feature 5/implementation_phases.md`

---

## Progress Summary

| Phase | Description | Status | Files |
|-------|-------------|--------|-------|
| 1 | Configuration & Database Schema | ✅ Complete | config.py, models.py, .env.example, 004_chat_interface.py |
| 2 | Chat Modules (Suggestions + Follow-Ups) | ✅ Complete | chat/__init__.py, suggestions.py, follow_ups.py |
| 3 | Chat Router: Session CRUD + Message History | ✅ Complete | api/v1/chat.py, main.py |
| 4 | SSE Query + Confirmation + Suggestions Endpoint | ✅ Complete | api/v1/chat.py |
| 5 | Backend Tests | ✅ Complete | test_chat_api.py, test_suggestions.py |
| 6 | Frontend Scaffolding | ✅ Complete | frontend/*, types, lib, store |
| 7 | Layout + SessionSidebar | ✅ Complete | layout.tsx, layout-shell.tsx, SessionSidebar.tsx, page routes |
| 8 | Chat Components | ✅ Complete | 7 component files + tailwind.config.ts |
| 9 | Page Routes + Full Integration | ✅ Complete | app/chat/[session_id]/page.tsx |
| 10 | Frontend Tests + Documentation | ✅ Complete | tests, READMEs |
