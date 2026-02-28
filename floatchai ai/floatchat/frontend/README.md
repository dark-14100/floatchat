# FloatChat Frontend

A Next.js 14 conversational chat interface for querying ocean data. This is Feature 5 of FloatChat — the front door that wraps the NL query engine (Feature 4) in a familiar chat UI.

---

## Tech Stack

| Package | Version | Purpose |
|---|---|---|
| Next.js | 14.x | App Router framework |
| React | 18.x | UI library |
| TypeScript | 5.x | Type safety |
| Tailwind CSS | 3.x | Styling |
| shadcn/ui | latest | UI components (New York style, neutral) |
| Zustand | 4.x | State management |
| react-markdown | 9.x | Markdown rendering |
| remark-gfm | 4.x | GFM tables/lists |
| rehype-highlight | 7.x | Code highlighting |
| rehype-sanitize | 6.x | HTML sanitisation |
| lucide-react | latest | Icons |
| Vitest | latest | Testing |
| React Testing Library | latest | Component testing |

---

## Getting Started

### Prerequisites

- Node.js 18+
- Backend running at `http://localhost:8000` (see `../backend/README.md`)

### Setup

```bash
cd frontend
npm install
cp .env.local.example .env.local   # Edit NEXT_PUBLIC_API_URL if needed
npm run dev                         # Starts at http://localhost:3000
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend API base URL |

### Scripts

| Command | Description |
|---|---|
| `npm run dev` | Start dev server (hot reload) |
| `npm run build` | Production build |
| `npm run start` | Serve production build |
| `npm run lint` | Next.js lint |
| `npm test` | Run Vitest tests |
| `npm run test:watch` | Run tests in watch mode |

---

## Architecture

```
frontend/
├── app/                          # Next.js App Router pages
│   ├── layout.tsx                # Root layout (dark mode, fonts)
│   ├── layout-shell.tsx          # Client shell (sidebar + main panel)
│   ├── page.tsx                  # / → redirects to /chat
│   └── chat/
│       ├── page.tsx              # /chat → creates session, redirects to /chat/{id}
│       └── [session_id]/
│           └── page.tsx          # Main chat view — composes all components
├── components/
│   ├── chat/                     # Chat UI components
│   │   ├── ChatThread.tsx        # Scrollable message area + pagination
│   │   ├── ChatMessage.tsx       # Discriminated message display
│   │   ├── ChatInput.tsx         # <textarea> with auto-resize
│   │   ├── ResultTable.tsx       # Inline data table with sort
│   │   ├── SuggestedFollowUps.tsx # Follow-up suggestion chips
│   │   ├── SuggestionsPanel.tsx  # Load-time suggestion cards
│   │   └── LoadingMessage.tsx    # SSE stream state indicator
│   ├── layout/
│   │   └── SessionSidebar.tsx    # Session list sidebar
│   └── ui/                       # shadcn/ui primitives
├── store/
│   └── chatStore.ts              # Zustand global store
├── lib/
│   ├── api.ts                    # Typed API client functions
│   ├── sse.ts                    # SSE stream client (fetch + ReadableStream)
│   └── utils.ts                  # cn() utility
├── types/
│   └── chat.ts                   # All TypeScript interfaces
└── tests/                        # Vitest + RTL tests
    ├── setup.ts
    ├── ChatInput.test.tsx
    ├── SuggestedFollowUps.test.tsx
    ├── ResultTable.test.tsx
    ├── LoadingMessage.test.tsx
    └── chatStore.test.ts
```

---

## Component Map

### Layout

| Component | Path | Description |
|---|---|---|
| `LayoutShell` | `app/layout-shell.tsx` | Two-panel layout: sidebar + main. Hamburger toggle on mobile (<768px). Generates anonymous UUID on first visit. |
| `SessionSidebar` | `components/layout/SessionSidebar.tsx` | "FloatChat" branding, "New Conversation" button, scrollable session list ordered by last_active_at desc, rename/delete via dropdown menu. |

### Chat Components

| Component | Path | Props | Description |
|---|---|---|---|
| `ChatThread` | `components/chat/ChatThread.tsx` | `sessionId`, `streamState`, `pendingInterpretation`, callbacks | Scrollable area. Loads 50 messages on mount. Auto-scroll. Infinite scroll upward. Empty → SuggestionsPanel. |
| `ChatMessage` | `components/chat/ChatMessage.tsx` | `message`, `streamState?`, `chartComponent?`, `mapComponent?`, callbacks | Discriminated rendering: user (right-aligned), assistant success (Markdown + SQL + ResultTable + slots), awaiting_confirmation, error (FR-23 mapping), loading. |
| `ChatInput` | `components/chat/ChatInput.tsx` | `onSubmit`, `isLoading`, `placeholder?` | `<textarea>` with auto-resize (6 lines max). Enter submits, Shift+Enter newline. Character count >450. Exposes `ref`. |
| `ResultTable` | `components/chat/ResultTable.tsx` | `columns`, `rows`, `rowCount`, `truncated` | HTML table with sort, 100 rows + "Show more", `toFixed(4)`, timestamp formatting, amber outlier highlight. |
| `SuggestedFollowUps` | `components/chat/SuggestedFollowUps.tsx` | `suggestions`, `onSelect` | Clickable chips. Renders nothing if empty. |
| `SuggestionsPanel` | `components/chat/SuggestionsPanel.tsx` | `onSelect` | Grid of suggestion cards from API. 4 hardcoded fallbacks on failure. |
| `LoadingMessage` | `components/chat/LoadingMessage.tsx` | `streamState`, `interpretation?` | Animated dots (thinking), text (interpreting), progress bar (executing). |

### Extension Slots

`ChatMessage` accepts `chartComponent` and `mapComponent` React node props for Features 6 and 7. These are empty in Feature 5.

---

## State Management

Zustand store at `store/chatStore.ts`:

| State | Type | Description |
|---|---|---|
| `sessions` | `ChatSession[]` | All sessions for user |
| `activeSessionId` | `string \| null` | Current session |
| `messages` | `Record<string, ChatMessage[]>` | Messages keyed by session ID |
| `isLoading` | `boolean` | True while SSE stream active |
| `streamState` | `StreamState` | Current SSE event phase |
| `pendingInterpretation` | `string \| null` | Text from interpreting event |
| `loadTimeSuggestions` | `Suggestion[]` | Cached load-time suggestions |

No async logic in the store. Components call `lib/api.ts` and dispatch actions.

---

## SSE Flow

1. User types query → `ChatInput.onSubmit` → `submitQuery()` in page
2. User message appended to store
3. `createQueryStream()` opens POST SSE connection
4. Events dispatched to store: `thinking` → `interpreting` → `executing` → `results` → `suggestions` → `done`
5. Assistant message built from `results` event, updated with `suggestions`
6. `onDone` resets loading state, re-focuses input

### Confirmation Flow
- `awaiting_confirmation` event → show "Run this query" / "Cancel" buttons
- "Run this query" → `createConfirmStream()` → `executing` → `results` → `done`

---

## Tests

45 tests across 5 test files:

| File | Tests | What's Covered |
|---|---|---|
| `ChatInput.test.tsx` | 9 | Enter submits, Shift+Enter newline, disabled when loading, textarea element, char count |
| `SuggestedFollowUps.test.tsx` | 6 | Renders chips, click callback, empty rendering, accessibility |
| `ResultTable.test.tsx` | 11 | Row count, truncated badge, sorting, show more, null formatting, number formatting |
| `LoadingMessage.test.tsx` | 6 | All stream states, null/done returns nothing, accessibility |
| `chatStore.test.ts` | 13 | Session CRUD, message append/update, stream state sequence, suggestions |

Run: `npm test`

---

## Hard Rules

1. **SSE only** — no WebSocket
2. **No Plotly/Leaflet/Mapbox** — chart/map slots are empty until Features 6/7
3. **No `any` types** — every prop and response is typed
4. **`<textarea>` not `<input>`** — multi-line ocean data queries
5. **Store context after execution only** — only completed queries get assistant messages
6. **All SSE events are valid JSON** — frontend parser expects JSON on every `data:` line
7. **Do not modify Feature 1–4 files** except `config.py`, `main.py`, `models.py`
