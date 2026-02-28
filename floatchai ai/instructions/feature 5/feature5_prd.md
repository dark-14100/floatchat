# FloatChat — Feature 5: Conversational Chat Interface
## Product Requirements Document (PRD)

**Feature Name:** Conversational Chat Interface
**Version:** 1.0
**Status:** Ready for Development
**Owner:** Frontend / Full-Stack Engineering
**Depends On:** Feature 4 (Natural Language Query Engine — `POST /api/v1/query` must exist), Feature 2 (Database — `chat_sessions` and `chat_messages` tables), Feature 3 (Metadata Search — dataset summaries for load-time suggestions)

---

## 1. Purpose & Background

### 1.1 What Problem Does This Solve?
Feature 4 built the intelligence layer. Feature 5 is how researchers actually use it. Without a chat interface, the NL query engine has no front door — it exists only as an API endpoint that requires technical knowledge to call.

Feature 5 wraps Feature 4's power in a conversational interface that feels familiar, approachable, and intelligent. A researcher opens FloatChat, sees example queries, types a question in plain English, and gets results — tables, charts, and maps — right inside the conversation thread. No SQL. No terminal. No downloads.

### 1.2 What This Feature Is
A full-stack conversational interface consisting of:
- A Next.js 14 frontend with a chat layout
- A FastAPI backend with chat session management and message persistence
- Real-time response streaming via Server-Sent Events (SSE)
- LLM-generated follow-up question suggestions after each response
- Session-scoped context memory with named session support
- Load-time example queries tailored to available datasets
- Structured error guidance when queries fail or return no results
- Inline rendering of result tables, charts (from Feature 6), and maps (from Feature 7)

### 1.3 What This Feature Is Not
- It does not generate SQL — that is Feature 4
- It does not render charts — that is Feature 6 (the chat interface provides the container; Feature 6 provides the components)
- It does not render maps — that is Feature 7
- It does not handle file exports — that is Feature 8
- It is not an admin panel — that is Feature 10

### 1.4 Relationship to Other Features
- Feature 4: The chat interface calls `POST /api/v1/query` and streams the response back to the user
- Feature 6: Chart components built in Feature 6 are rendered inline inside `ChatMessage` components
- Feature 7: Map components built in Feature 7 are rendered inline inside `ChatMessage` components
- Feature 3: Dataset summaries from Feature 3 power the load-time example queries
- Feature 8: The "Export this data" follow-up chip triggers Feature 8's export flow
- Feature 9: The Guided Query Assistant's clarification chips and autocomplete are embedded inside this interface

---

## 2. Goals & Success Criteria

### 2.1 Goals
- Give researchers a familiar, low-friction interface for querying ocean data
- Display query results inline in the conversation without page navigation
- Make multi-turn conversations feel natural via context memory
- Guide new users to useful queries immediately on load
- Provide clear, actionable error messages when things go wrong

### 2.2 Success Criteria

| Criterion | Target |
|---|---|
| Time from page load to first query submittable | < 2 seconds |
| SSE stream first byte latency | < 500ms after query submitted |
| Follow-up suggestions generated and displayed | < 3 seconds after result renders |
| Chat history load time (50 messages) | < 1 second |
| Lighthouse performance score | ≥ 85 |
| Mobile responsiveness | Fully functional on 375px width |

---

## 3. User Stories

### 3.1 Researcher
- **US-01:** As a researcher, I want to type a question and see results appear in the chat without leaving the page, so that exploration feels like a conversation.
- **US-02:** As a researcher, I want to ask follow-up questions that reference prior results without repeating context, so that multi-step investigations feel natural.
- **US-03:** As a researcher, I want to see 2–3 suggested follow-up questions after every response, so that I can explore deeper without thinking of the next question myself.
- **US-04:** As a researcher, I want to start a new conversation to reset context, so that I can begin a fresh investigation without prior turns interfering.
- **US-05:** As a researcher, I want to name and return to previous conversations, so that I can continue an investigation I started earlier.
- **US-06:** As a new user, I want to see example queries on first load, so that I know what FloatChat can do and how to ask it.
- **US-07:** As a researcher, I want clear error messages with reformulation suggestions when my query returns nothing, so that I know how to improve my question.
- **US-08:** As a researcher, I want to see a loading animation while results are being fetched, so that I know the system is working.
- **US-09:** As a researcher, I want to use Enter to submit my query and Shift+Enter to add a new line, so that the interface behaves like a modern chat tool.

### 3.2 System (Internal Consumer)
- **US-10:** As Feature 6 (Visualization), I need a `ChatMessage` component that can render a chart component inline, so that depth profiles and time series appear inside the conversation thread.
- **US-11:** As Feature 7 (Geospatial), I need a `ChatMessage` component that can render a map component inline, so that float positions appear inside the conversation thread.
- **US-12:** As Feature 8 (Export), I need an "Export this data" button or chip that appears after result messages, so that researchers can trigger an export from within the conversation.

---

## 4. Functional Requirements

### 4.1 Backend: Database Schema

**FR-01 — `chat_sessions` Table**
One row per conversation session. Columns: `session_id` (UUID PK), `user_identifier` (VARCHAR, nullable — for future auth, store browser fingerprint or anonymous ID for now), `name` (VARCHAR, nullable — for named sessions), `created_at` (TIMESTAMPTZ, default now), `last_active_at` (TIMESTAMPTZ, updated on each message), `is_active` (BOOLEAN, default true), `message_count` (INTEGER, default 0).

**FR-02 — `chat_messages` Table**
One row per message in a conversation. Columns: `message_id` (UUID PK), `session_id` (UUID FK → chat_sessions, CASCADE DELETE), `role` (VARCHAR — `user` or `assistant`), `content` (TEXT — the message text or result summary), `nl_query` (TEXT, nullable — the original NL query for user messages), `generated_sql` (TEXT, nullable — for assistant messages), `result_metadata` (JSONB, nullable — row count, column names, truncated flag, execution time), `follow_up_suggestions` (JSONB, nullable — array of follow-up question strings), `error` (JSONB, nullable — structured error if the query failed), `created_at` (TIMESTAMPTZ, default now). Index on `session_id` and `created_at` for efficient history retrieval.

**FR-03 — Migration**
Create Alembic migration `004_chat_interface.py` with `down_revision = "003"`. Creates both tables. `downgrade()` drops both tables.

### 4.2 Backend: Chat API

**FR-04 — Session Management Endpoints**

`POST /api/v1/chat/sessions` — Create a new chat session. Body: `{"name": str (optional)}`. Returns: `{"session_id": str, "created_at": str}`.

`GET /api/v1/chat/sessions` — List all sessions for the current user, ordered by `last_active_at` descending. Returns list of session objects with `session_id`, `name`, `message_count`, `last_active_at`.

`GET /api/v1/chat/sessions/{session_id}` — Get session details. Returns session metadata.

`PATCH /api/v1/chat/sessions/{session_id}` — Update session name. Body: `{"name": str}`.

`DELETE /api/v1/chat/sessions/{session_id}` — Soft delete (set `is_active = false`). Does not delete messages.

**FR-05 — Message History Endpoint**

`GET /api/v1/chat/sessions/{session_id}/messages` — Returns paginated message history for a session. Params: `limit` (default 50), `before_message_id` (for cursor pagination). Returns messages ordered by `created_at` ascending (oldest first). Each message includes all fields from `chat_messages`.

**FR-06 — Query Endpoint (SSE Streaming)**

`POST /api/v1/chat/sessions/{session_id}/query`

This is the primary endpoint. It wraps Feature 4's `POST /api/v1/query` with:
- Session validation (session must exist and be active)
- Message persistence (saves user message and assistant response to `chat_messages`)
- SSE streaming so the frontend receives progress events in real time
- Follow-up suggestion generation (separate LLM call after results are ready)

Request body: `{"query": str, "confirm": bool (optional, default false)}`.

The endpoint must stream SSE events in this exact sequence:
1. `event: thinking` — immediately on receipt, before calling Feature 4. Payload: `{"status": "thinking"}`
2. `event: interpreting` — after Feature 4 returns the interpretation string. Payload: `{"interpretation": str}`
3. `event: executing` — after validation passes, before execution. Payload: `{"status": "executing"}`
4. `event: results` — after execution completes. Payload: full result object including `rows`, `row_count`, `column_names`, `truncated`, `execution_time_ms`, `sql`, `attempt_count`
5. `event: suggestions` — after follow-up suggestions are generated. Payload: `{"suggestions": [str, str, str]}`
6. `event: done` — signals stream end. Payload: `{"status": "done"}`

On error at any step: stream `event: error` with `{"error": str, "error_type": str}` then `event: done`.

**FR-07 — Follow-Up Suggestion Generation**
After results are returned, make a short LLM call to generate 2–3 follow-up questions. Prompt: given the user's query, the SQL that was run, and the shape of results (column names, row count), generate 2-3 natural follow-up questions a researcher might ask. Use the same LLM provider as Feature 4 (`QUERY_LLM_PROVIDER`). Temperature: 0.7 (slightly creative). Max tokens: 150. Store the suggestions in the `follow_up_suggestions` column of the assistant message. If the LLM call fails, store an empty array — never block the response.

**FR-08 — Load-Time Suggestions Endpoint**

`GET /api/v1/chat/suggestions` — Returns 4–6 example queries tailored to available datasets. Calls Feature 3's `get_all_summaries()` to get active dataset metadata, then constructs example queries from the dataset variables, date ranges, and regions. Returns: `{"suggestions": [{"query": str, "description": str}]}`. Suggestions are generated once per hour and cached in Redis with key `chat_suggestions` and TTL 3600 seconds. If no datasets exist, return a set of generic ocean data example queries as fallback.

**FR-09 — Confirmation Endpoint**

`POST /api/v1/chat/sessions/{session_id}/query/confirm` — Called when the frontend receives `awaiting_confirmation: true` from Feature 4. Re-sends the query with `confirm: true` to Feature 4 and streams the execution results via SSE. Same event sequence as FR-06 but skips the `thinking` and `interpreting` events (already shown).

### 4.3 Frontend: Layout & Structure

**FR-10 — Application Layout**
The frontend is a Next.js 14 app with App Router. The root layout has two panels:
- **Left sidebar** (280px fixed width, collapsible on mobile): contains the "New Conversation" button, session history list, and branding
- **Right main panel** (fills remaining width): contains the active chat thread and input area

The layout must be responsive. On screens below 768px width, the sidebar collapses to a hamburger menu icon. On screens above 768px, the sidebar is always visible.

**FR-11 — Page Routes**
- `/` — redirects to `/chat` or creates a new session and redirects to `/chat/{session_id}`
- `/chat` — creates a new session automatically and redirects to `/chat/{session_id}`
- `/chat/{session_id}` — the main chat view for a specific session

### 4.4 Frontend: Components

**FR-12 — `ChatThread` Component**
The scrollable area displaying all messages in the current session. Must:
- Load the last 50 messages from `GET /api/v1/chat/sessions/{session_id}/messages` on mount
- Auto-scroll to the bottom when new messages arrive
- Support infinite scroll upward to load older messages (cursor pagination)
- Display a "Scroll to bottom" button when the user has scrolled up and a new message arrives
- Handle empty state (no messages): display the `SuggestionsPanel` component

**FR-13 — `ChatMessage` Component**
Renders a single message. Must support these content types based on the message's role and metadata:

For `role: user`:
- Plain text display, right-aligned, with user avatar placeholder

For `role: assistant` — success state:
- Plain text interpretation string (rendered as Markdown)
- `ResultTable` component (inline data table) if `row_count > 0`
- Chart component slot (Feature 6 renders here — the `ChatMessage` accepts a `chartComponent` prop)
- Map component slot (Feature 7 renders here — the `ChatMessage` accepts a `mapComponent` prop)
- `SuggestedFollowUps` component with 2–3 chips
- `ExportButton` component (triggers Feature 8 export flow)
- Row count and execution time metadata line: "Found {n} profiles in {ms}ms"

For `role: assistant` — awaiting confirmation state:
- Display the interpretation string
- Show "Run this query" and "Cancel" buttons
- On "Run this query" click, send to `/query/confirm` endpoint

For `role: assistant` — error state:
- Display error message
- Display reformulation suggestions based on `error_type`
- "Try again" button that re-sends the original query

For `role: assistant` — loading state (while SSE stream is active):
- Display current SSE event status: "Thinking...", "Interpreting your query...", "Running query...", etc.
- Animated typing indicator (three pulsing dots)

**FR-14 — `ResultTable` Component**
An inline data table rendered inside a `ChatMessage`. Must:
- Display up to 100 rows inline. If `row_count > 100`, show first 100 with a "Show more" toggle
- Support column sorting by clicking headers
- Display a "Truncated" badge if `truncated: true` with tooltip: "Results were limited to 10,000 rows"
- Be horizontally scrollable when columns overflow
- Format numeric values to 4 decimal places
- Format `timestamp` columns as human-readable dates
- Highlight the `is_outlier` column if present with a warning color

**FR-15 — `SuggestedFollowUps` Component**
A row of 2–3 clickable chips below each assistant response. Clicking a chip populates the chat input with that suggestion and submits it automatically. Chips must be visually distinct from regular buttons. If suggestions array is empty, render nothing (no empty chip row).

**FR-16 — `SuggestionsPanel` Component**
Shown when the chat thread is empty (new session). Displays 4–6 example query cards fetched from `GET /api/v1/chat/suggestions`. Each card has a query string and a short description. Clicking a card submits the query. Refreshes every hour (use the cached endpoint). If the endpoint fails, show 4 hardcoded fallback suggestions.

**FR-17 — `ChatInput` Component**
The text input area fixed at the bottom of the main panel. Must:
- Auto-resize vertically as the user types (up to 6 lines max, then scroll)
- Submit on Enter key press
- Insert newline on Shift+Enter
- Disable submission while a query is in progress (show spinner on send button)
- Clear after submission
- Show character count when approaching 500 characters (soft limit)
- Accept a `placeholder` prop: default "Ask about ocean data..."
- Expose a `ref` so the parent can programmatically focus it

**FR-18 — `SessionSidebar` Component**
The left sidebar panel. Must:
- Display "FloatChat" branding at the top
- "New Conversation" button that calls `POST /api/v1/chat/sessions` and navigates to the new session
- Scrollable list of sessions ordered by `last_active_at` descending
- Each session item shows: name (or "New conversation" if unnamed), last active time (relative: "2 hours ago"), message count
- Clicking a session navigates to `/chat/{session_id}`
- Active session is highlighted
- Long press or right-click on a session shows a context menu with "Rename" and "Delete" options
- Sessions load on sidebar mount and refresh when a new session is created

**FR-19 — Markdown Rendering**
All assistant text content is rendered as Markdown. Use `react-markdown` with `remark-gfm` for tables, `rehype-highlight` for code blocks. Do not render raw HTML from the server — sanitise with `rehype-sanitize`. Supported Markdown elements: headings, bold, italic, code inline, code blocks, tables, lists, blockquotes.

**FR-20 — Loading States**
Three loading states must be visually distinct:
- **Thinking** (`event: thinking`): "Thinking..." with animated dots
- **Interpreting** (`event: interpreting`): show the interpretation string as it arrives
- **Executing** (`event: executing`): "Running query..." with a progress bar animation (indeterminate)

These states replace the static typing animation during their respective SSE events.

### 4.5 Frontend: State Management

**FR-21 — State Management**
Use Zustand for global state. The store must manage:
- `sessions`: list of all sessions
- `activeSessionId`: currently viewed session ID
- `messages`: map of `session_id → message[]`
- `isLoading`: boolean — true while SSE stream is active
- `currentStreamState`: current SSE event type (`thinking` | `interpreting` | `executing` | `done` | null)
- `suggestions`: cached follow-up suggestions from the last response

Do not use Redux or Context for state that crosses components. Zustand only.

**FR-22 — SSE Connection Management**
Use the browser's native `EventSource` API or `fetch` with `ReadableStream` for SSE. Do not use Socket.io. The SSE connection must:
- Open when a query is submitted
- Close automatically when `event: done` is received
- Close on component unmount
- Retry once automatically if the connection drops unexpectedly (not on explicit `done`)
- Respect the `awaiting_confirmation` state — do not auto-close on this state

### 4.6 Frontend: Error Handling

**FR-23 — Error Message Mapping**
Map `error_type` values from Feature 4 to human-readable messages and reformulation suggestions:

| `error_type` | User-facing message | Suggestion |
|---|---|---|
| `validation_failure` | "I couldn't generate a valid query for that." | "Try rephrasing with more specific details about the region, time period, or variable." |
| `generation_failure` | "I had trouble understanding that query after 3 attempts." | "Try breaking the question into smaller parts." |
| `execution_error` | "The query ran but encountered a database error." | "Try again, or narrow your filters." |
| `timeout` | "The query took too long to run." | "Try narrowing your filters — add a smaller region or shorter time range." |
| `configuration_error` | "The AI service is not configured." | "Contact the administrator." |

**FR-24 — Empty Result Guidance**
When `row_count = 0`, display a specific message based on query context:
- If the query contained a radius filter: "No profiles found within that radius. Try expanding the search area."
- If the query contained a time range: "No profiles found for that time period. Try a wider date range."
- Default: "No data matched your query. Try adjusting the filters."

---

## 5. Non-Functional Requirements

### 5.1 Performance
- Initial page load (LCP) must be under 2.5 seconds on a standard broadband connection
- The chat thread must render 100 messages without visible jank
- `ResultTable` must render 100 rows without performance degradation
- SSE connection must not block the main thread

### 5.2 Accessibility
- All interactive elements must have ARIA labels
- Keyboard navigation must work throughout the interface
- Color contrast must meet WCAG AA standards
- Loading states must be announced to screen readers via `aria-live` regions

### 5.3 Responsiveness
- Fully functional at 375px (iPhone SE width) through 2560px (large desktop)
- On mobile, sidebar collapses to hamburger icon
- `ResultTable` is horizontally scrollable on small screens

### 5.4 Browser Support
- Chrome 120+, Firefox 120+, Safari 17+, Edge 120+
- No Internet Explorer support

---

## 6. New Configuration Settings

Add to `Settings` class in `config.py`:
- `CHAT_SUGGESTIONS_CACHE_TTL_SECONDS` — default `3600`
- `CHAT_SUGGESTIONS_COUNT` — default `6`
- `CHAT_MESSAGE_PAGE_SIZE` — default `50`
- `FOLLOW_UP_LLM_TEMPERATURE` — default `0.7`
- `FOLLOW_UP_LLM_MAX_TOKENS` — default `150`

---

## 7. File Structure

```
floatchat/
├── backend/
│   ├── app/
│   │   ├── chat/
│   │   │   ├── __init__.py
│   │   │   ├── suggestions.py        # Load-time suggestion generation
│   │   │   └── follow_ups.py         # Follow-up question generation
│   │   └── api/
│   │       └── v1/
│   │           └── chat.py           # FastAPI router for all chat endpoints
│   ├── alembic/
│   │   └── versions/
│   │       └── 004_chat_interface.py
│   └── tests/
│       ├── test_chat_api.py
│       └── test_suggestions.py
└── frontend/
    ├── app/
    │   ├── layout.tsx               # Root layout with sidebar
    │   ├── page.tsx                 # / redirect
    │   ├── chat/
    │   │   ├── page.tsx             # /chat — creates session, redirects
    │   │   └── [session_id]/
    │   │       └── page.tsx         # /chat/{session_id} — main chat view
    ├── components/
    │   ├── chat/
    │   │   ├── ChatThread.tsx
    │   │   ├── ChatMessage.tsx
    │   │   ├── ChatInput.tsx
    │   │   ├── ResultTable.tsx
    │   │   ├── SuggestedFollowUps.tsx
    │   │   ├── SuggestionsPanel.tsx
    │   │   └── LoadingMessage.tsx
    │   └── layout/
    │       └── SessionSidebar.tsx
    ├── store/
    │   └── chatStore.ts             # Zustand store
    ├── lib/
    │   ├── api.ts                   # API client functions
    │   └── sse.ts                   # SSE connection management
    ├── types/
    │   └── chat.ts                  # TypeScript type definitions
    ├── package.json
    ├── tailwind.config.ts
    └── next.config.ts
```

---

## 8. Frontend Dependencies

| Package | Version | Purpose |
|---|---|---|
| next | 14.x | Framework |
| react | 18.x | UI library |
| react-dom | 18.x | DOM rendering |
| typescript | 5.x | Type safety |
| tailwindcss | 3.x | Styling |
| @shadcn/ui | latest | UI components |
| zustand | 4.x | State management |
| react-markdown | 9.x | Markdown rendering |
| remark-gfm | 4.x | Markdown tables and GFM |
| rehype-highlight | 7.x | Code syntax highlighting |
| rehype-sanitize | 6.x | HTML sanitisation |
| lucide-react | latest | Icons |

Do not add Plotly, Leaflet, or Mapbox — those belong to Features 6 and 7.

---

## 9. Testing Requirements

### 9.1 Backend Tests (`test_chat_api.py`)
- Test `POST /api/v1/chat/sessions` creates a session and returns `session_id`
- Test `GET /api/v1/chat/sessions/{session_id}/messages` returns paginated messages
- Test SSE stream from `/query` emits events in correct sequence: `thinking → interpreting → executing → results → suggestions → done`
- Test SSE stream emits `error` event when Feature 4 returns a validation failure
- Test soft delete sets `is_active = false` without deleting messages
- Test message is persisted to `chat_messages` after a successful query

### 9.2 Suggestions Tests (`test_suggestions.py`)
- Test `GET /api/v1/chat/suggestions` returns 4–6 suggestions
- Test suggestions are cached in Redis and not regenerated within TTL window
- Test fallback suggestions returned when no datasets exist
- Test follow-up suggestions generation returns 2–3 strings
- Test follow-up suggestion failure returns empty array without raising

### 9.3 Frontend Tests
- Test `ChatInput` submits on Enter, inserts newline on Shift+Enter
- Test `ChatInput` is disabled while `isLoading` is true
- Test `SuggestedFollowUps` renders chips from suggestions array
- Test clicking a chip populates and submits the input
- Test `ResultTable` renders correct number of rows
- Test `ResultTable` shows "Truncated" badge when `truncated: true`
- Test empty `ChatThread` renders `SuggestionsPanel`
- Test SSE stream updates loading state through correct sequence

---

## 10. Dependencies & Prerequisites

| Dependency | Reason | Must Be Ready Before |
|---|---|---|
| Feature 4 complete | `POST /api/v1/query` must be live | Day 1 of backend work |
| Feature 2 complete | Database session for `chat_sessions` / `chat_messages` | Day 1 |
| Feature 3 complete | `get_all_summaries()` for load-time suggestions | Before suggestions endpoint |
| Redis running | Suggestions cache | Day 1 |
| Node.js 18+ | Next.js 14 requirement | Before frontend work |

---

## 11. Out of Scope for v1.0

- User authentication (sessions are anonymous in v1)
- Real-time collaborative sessions (multiple users in one session)
- Voice input
- Message editing or deletion
- Session search
- Push notifications
- Dark mode toggle (dark mode is default)

---

## 12. Open Questions

| # | Question | Owner | Due |
|---|---|---|---|
| Q1 | Should the chat interface use SSE (simpler, one-way) or WebSocket (bidirectional, supports future features)? The tasks list mentions both. SSE is sufficient for v1 since the server-to-client direction is the only streaming needed. | Tech Lead | Before FR-06 implementation |
| Q2 | Should sessions be tied to a user identifier? In v1, auth is out of scope, so sessions are browser-local. Should `user_identifier` be a browser-generated UUID stored in localStorage, or left null entirely? | Product | Before FR-01 implementation |
| Q3 | How many sessions should appear in the sidebar? Unlimited list with scroll, or cap at 20 recent sessions? | Product | Before SessionSidebar implementation |
| Q4 | Should the follow-up suggestions be the same LLM provider as Feature 4 (`QUERY_LLM_PROVIDER`), or always GPT-4o for consistency? | Backend | Before FR-07 implementation |
| Q5 | Should the SQL be shown to the user in the chat interface? Feature 4 PRD deferred this to v1. Showing SQL in a collapsible `<details>` block helps researchers learn. | Product | Before ChatMessage implementation |
