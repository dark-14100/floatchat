# FloatChat — Feature 9: Guided Query Assistant
## Product Requirements Document (PRD)

**Feature Name:** Guided Query Assistant
**Version:** 1.0
**Status:** ✅ Implemented (2026-03-08)
**Depends On:** Feature 4 (NL Query Engine — clarification LLM calls use the same multi-provider setup), Feature 5 (Chat Interface — all components live inside ChatInput and the chat empty state), Feature 13 (Auth — personalization requires user identity), Feature 14 (RAG Pipeline — autocomplete sources from `query_history`), Feature 15 (Anomaly Detection — anomaly deep links enter the chat via this feature's prefill mechanism)
**Blocks:** Feature 10 (Dataset Management — template gallery refreshes based on newly ingested datasets, which Feature 10 manages)

---

## 1. Purpose & Background

### 1.1 What Problem Does This Solve?
FloatChat's core value proposition is natural language querying of ARGO data. But new users face a blank input box with no guidance on what to ask, what variables exist, what regions are available, or how specific they need to be. The result is either underspecified queries ("show me ocean data") that return confusing results, or no queries at all because the user doesn't know where to start.

Even experienced users benefit from autocomplete — typing "show me temperature" and seeing relevant completions sourced from their own past successful queries reduces friction and increases query quality.

Feature 9 solves the cold-start and discoverability problem at the query input level. It does not change the underlying query engine — it improves the quality and specificity of what reaches the engine.

### 1.2 What This Feature Is
Three complementary components that together guide a user from uncertainty to a well-formed query:

1. **Suggested Query Gallery** — shown on the chat empty state, categorized templates that get the user started immediately
2. **Typeahead Autocomplete** — sources completions from the template library, the user's own past successful queries, and a curated list of oceanographic terms; powered by Fuse.js for fuzzy matching
3. **Clarification Prompts** — detects underspecified queries before they reach the NL engine, asks targeted chip-based follow-up questions, and assembles a complete query from the user's responses

### 1.3 What This Feature Is Not
- It does not change how queries are executed — Feature 4's NL engine is unchanged
- It does not replace the free-text input — users can always type freely and bypass all guidance
- It does not require a new database table in v1 (clarification flows are logged via structlog, not persisted — persistence is a v2 consideration)
- It adds two lightweight API endpoints for implementation safety and performance: `GET /api/v1/chat/query-history` and `POST /api/v1/clarification/detect`
- It does not add new LLM providers — the clarification detection LLM uses the same multi-provider setup as Feature 4

### 1.4 Relationship to Feature 14 (RAG)
The autocomplete component queries `query_history` for each user's past successful queries. This is the primary value of having RAG live before building this feature — autocomplete sourced from the user's own history is personalized and improves with usage, which compounds the switching cost that RAG creates.

### 1.5 Relationship to Feature 15 (Anomaly Detection)
The "Investigate in Chat" deep link from the anomaly detail panel uses the chat prefill mechanism. The prefill parameter is handled by the same ChatInput component that Feature 9 extends. Feature 9 must not break the prefill flow — when a prefill parameter is present, the suggested query gallery must not render, and autocomplete must not interfere with the pre-filled text.

---

## 2. Goals & Success Criteria

### 2.1 Goals
- Reduce the number of underspecified queries that reach the NL engine
- Give new users a path to their first successful query within 30 seconds of opening the app
- Improve query quality over time by surfacing the user's own past successful queries as autocomplete suggestions
- Catch "show me ocean data"-class queries before they hit the LLM and guide the user toward specificity

### 2.2 Success Criteria

| Criterion | Target |
|---|---|
| Time to first successful query for new users | < 30 seconds using gallery templates |
| Autocomplete suggestion relevance | ≥ 80% of shown suggestions are relevant to the partial input |
| Clarification detection accuracy | ≥ 90% of genuinely underspecified queries trigger clarification |
| False positive clarification rate | < 10% of well-formed queries incorrectly trigger clarification |
| Template gallery coverage | 30+ templates across at least 5 categories |
| Autocomplete response time | < 100ms from keystroke to suggestions visible |
| Prefill flow unaffected | Anomaly deep links always bypass gallery and load prefill text correctly |

---

## 3. User Stories

### 3.1 New User (no query history)
- **US-01:** As a new user with an empty chat, I want to see example queries I can click to start immediately, so I don't have to know the right vocabulary on my first session.
- **US-02:** As a new user, I want the example queries organized by category (temperature, BGC floats, regions, etc.) so I can find something relevant to my research interest quickly.
- **US-03:** As a new user who typed something vague like "show me data from the Atlantic," I want FloatChat to ask me what variable, time period, and depth I'm interested in before running the query, so I get useful results.

### 3.2 Returning User (with query history)
- **US-04:** As a returning user, I want to see my own past successful queries surfaced as autocomplete suggestions when I start typing, so I can rerun or adapt previous analyses quickly.
- **US-05:** As a returning user, I want autocomplete to show me suggestions that match what I'm typing anywhere in the phrase (not just the prefix), so fuzzy matching works for partial recollections.
- **US-06:** As a returning user, I want the gallery to show me queries relevant to datasets that were recently ingested, so I know what new data is available to explore.

### 3.3 Researcher (experienced)
- **US-07:** As an experienced researcher, I want to be able to ignore all suggestions and type my query freely with no friction, so the guidance layer never slows me down.
- **US-08:** As a researcher investigating an anomaly, I want the "Investigate in Chat" deep link to load my query pre-filled without the gallery interfering, so the anomaly investigation flow is seamless.

---

## 4. Functional Requirements

### 4.1 Query Template Library

**FR-01 — Template Library File**
Create a JSON file at `frontend/lib/queryTemplates.json` containing 30 or more query templates. Each template has the following fields:
- `id` — unique string identifier (e.g. `"temp_surface_atlantic"`)
- `category` — one of: `"Temperature"`, `"Salinity"`, `"BGC Floats"`, `"Regional Comparison"`, `"Time Series"`, `"Float Tracking"`, `"Depth Analysis"`, `"Anomalies"`
- `label` — short display label shown in the gallery card (e.g. `"Surface temperature — North Atlantic"`)
- `query` — the full natural language query string that gets submitted to the chat input
- `description` — one sentence describing what this template returns, shown as a tooltip or card subtitle
- `variables` — array of oceanographic variables referenced (e.g. `["temperature"]`)
- `requiresAuth` — boolean, false for all v1 templates (personalization is auth-aware but all templates are visible to all users)

**FR-02 — Template Coverage**
Templates must cover all eight categories with at least 3 templates per category. The `"Anomalies"` category templates must reference the `anomalies` table and produce queries about anomaly detection results.

**FR-03 — Template Immutability**
The template library JSON is static in v1. It is not editable via admin UI. It is bundled with the frontend at build time. Updating templates requires a code deploy.

### 4.2 Suggested Query Gallery

**FR-04 — Empty State Rendering**
The `SuggestedQueryGallery` component renders in the main chat area when:
- The current session has zero messages (empty state), AND
- No `prefill` query parameter is present in the URL

It must not render in any other condition. If a prefill parameter is present (anomaly deep link, Feature 15), the gallery must not appear.

**FR-05 — Gallery Layout**
The gallery renders as a categorized grid of template cards. Categories are displayed as horizontal tabs or filter chips above the card grid. The default selected category on load is `"Temperature"`. Users can switch categories without any API call — all templates are loaded client-side from the static JSON.

**FR-06 — Template Card**
Each card displays: the template label (bold), the description (subtitle), and the variable tags. Clicking a card inserts the template's `query` string into the chat input and immediately submits it — the user does not need to press Enter. The gallery disappears as soon as the first message is sent.

**FR-07 — Personalized Gallery (authenticated users)**
For authenticated users with at least 5 entries in `query_history`, the first category tab in the gallery is `"For You"` — a dynamically generated set of up to 6 suggestions derived from the user's most queried variables and regions. These are fetched from `GET /api/v1/rag/suggestions` (existing RAG endpoint) or by querying `query_history` directly via the existing RAG API. The `"For You"` tab is not shown for users with fewer than 5 history entries or for unauthenticated sessions.

**FR-08 — Recently Ingested Datasets**
A `"Recently Added"` label or badge appears on template cards whose `variables` array intersects with variables present in datasets ingested in the last 7 days. This is a cosmetic indicator only — it does not change the template content. In v1, this intersection check uses the existing dataset metadata available from the datasets API. If the datasets API call fails, the badge is silently omitted — no error state.

### 4.3 Typeahead Autocomplete

**FR-09 — Autocomplete Sources**
The autocomplete system combines three sources into a single ranked suggestion list:
1. **Query templates** — the full set of 30+ templates from `queryTemplates.json`, matched by `label` and `query` fields
2. **User's past successful queries** — fetched once on component mount from `GET /api/v1/rag/history` (the existing RAG retrieval endpoint, filtered to the current user), cached in component state for the session. Only available for authenticated users. Maximum 200 entries loaded.
3. **Oceanographic term list** — a static curated list of variable names, ocean basin names, depth ranges, and ARGO-specific terminology (float types, QC flags, etc.) bundled as a JSON file at `frontend/lib/oceanTerms.json`

**FR-10 — Fuse.js Configuration**
Autocomplete uses Fuse.js for fuzzy matching across all three sources. Configuration:
- `threshold: 0.4` — moderate fuzzy tolerance
- `includeMatches: true` — enables character highlighting
- `keys` for templates: `["label", "query", "description"]` with weights 0.5, 0.3, 0.2
- `keys` for history entries: `["nl_query"]`
- `keys` for ocean terms: `["term", "aliases"]`
- `minMatchCharLength: 2` — no suggestions until at least 2 characters typed
- `distance: 100` — match anywhere in the string, not just prefix

**FR-11 — Suggestion Ranking**
Results from all three sources are merged and ranked in this priority order:
1. User's past successful queries (highest priority — personalized)
2. Query templates (second priority — curated)
3. Oceanographic terms (lowest priority — vocabulary help)

Maximum 8 suggestions shown at any time. Within each source tier, Fuse.js score determines ordering (lower score = better match).

**FR-12 — Suggestion Display**
Each suggestion in the dropdown shows:
- The matched text with matched characters highlighted (bold or color-coded)
- A source tag: `"Past query"`, `"Template"`, or `"Term"`
- For past queries: the date last used (from `query_history.created_at`)

**FR-13 — Keyboard Navigation**
- `ArrowDown` / `ArrowUp` — navigate suggestions
- `Tab` or `Enter` on a highlighted suggestion — select and insert into input
- `Escape` — dismiss suggestions
- Clicking a suggestion — select and insert

**FR-14 — Autocomplete Trigger and Dismissal**
Autocomplete activates after the user types 2 or more characters. It dismisses when: the input is cleared, the user presses Escape, or the user clicks outside the input area. It does not activate when a prefill parameter populated the input (the user hasn't typed yet).

**FR-15 — Performance Requirement**
All Fuse.js matching runs client-side. The time from keystroke to visible suggestions must be under 100ms. Fuse.js indexes for all three sources are built once on component mount, not on every keystroke.

### 4.4 Clarification Prompts

**FR-16 — Underspecified Query Detection**
Before a user's free-text query is submitted to the NL engine (Feature 4), it passes through a lightweight LLM call that determines whether the query is underspecified. A query is considered underspecified if it is missing two or more of: variable, region, time period. Single-variable queries like "show me temperature profiles" are not underspecified — the NL engine can handle them. The detection call uses the same multi-provider LLM setup as Feature 4.

**FR-17 — Detection LLM Call**
The detection call uses structured output (JSON mode). The prompt asks the LLM to return a JSON object with:
- `is_underspecified` — boolean
- `missing_dimensions` — array of strings, subset of `["variable", "region", "time_period", "depth"]`
- `clarification_questions` — array of objects, one per missing dimension, each with `dimension`, `question_text`, and `options` (array of 3–5 suggested values relevant to that dimension)

The call uses `max_tokens: 300`. If the call fails or times out (using the existing `LLM_TIMEOUT_SECONDS` setting), the query proceeds to the NL engine without clarification — fail open, never block the user.

**FR-18 — Clarification Widget**
When `is_underspecified` is true, the `ClarificationWidget` component renders below the chat input (above the message list). It shows:
- A brief message: "Your query needs a bit more detail — answer a few questions to get the best results"
- One chip group per missing dimension, each showing the `question_text` as a label and the `options` as selectable chips
- A "Skip and run anyway" link that dismisses the widget and submits the original query unchanged
- A "Run query" button that activates once at least one chip per dimension is selected

**FR-19 — Query Assembly**
When the user clicks "Run query" in the clarification widget, the selected chip values are appended to the original query text to form a complete query. Assembly format:
`{original_query}, specifically {dimension_1}: {selected_value_1}, {dimension_2}: {selected_value_2}`
Example: `"show me ocean data, specifically variable: temperature, region: Arabian Sea, time_period: last 6 months"`
The assembled query is submitted to the NL engine. The original partial query and the assembled query are both shown in the chat message list (original as the user message, assembled as a visible annotation beneath it).

**FR-20 — Clarification Flow Logging**
Each clarification flow is logged via structlog with the following keys:
- `event: "clarification_flow"`
- `user_id` — current user ID
- `original_query` — the underspecified query text
- `missing_dimensions` — array from detection response
- `chips_selected` — dict of dimension → selected value
- `outcome` — one of `"ran_assembled"`, `"skipped"`, `"abandoned"` (widget dismissed without action)
- `assembled_query` — the final assembled query if outcome is `"ran_assembled"`

This log data is the foundation for v2 template improvement (most common missing dimensions → add more specific templates for those gaps).

**FR-21 — Clarification Bypass**
The clarification check is bypassed when:
- The query comes from a template card click (already well-formed)
- The query comes from an autocomplete selection (already a complete past query or template)
- The query comes from a prefill parameter (anomaly deep link — user explicitly constructed this query)
- The user has previously selected "Skip and run anyway" for a query with identical text in the same session

---

## 5. Non-Functional Requirements

### 5.1 Performance
- Fuse.js indexes built once on mount — sub-100ms suggestion latency at all times
- Template library and ocean terms are bundled at build time — no network request for static data
- User query history fetched once on mount (max 200 entries) — no per-keystroke network calls
- Clarification detection LLM call must not block the UI — show a loading indicator in the ClarificationWidget while the call is in flight; if the call takes more than 3 seconds, proceed without clarification

### 5.2 Accessibility
- All autocomplete interactions must be keyboard-navigable (FR-13)
- Chip selection in the ClarificationWidget must work with keyboard (Space to toggle, Tab to move between chips)
- The "Skip and run anyway" option must always be reachable without mouse interaction

### 5.3 Resilience
- If the `query_history` fetch fails, autocomplete works with templates and ocean terms only — no error shown to user
- If the clarification detection LLM call fails, the query proceeds to the NL engine immediately — never block the user
- If the datasets API fails during gallery "Recently Added" badge computation, the badge is silently omitted

### 5.4 Non-Interference
- The entire guided query layer is additive — users who type directly and submit bypass all of it without friction
- Prefill parameters (from anomaly deep links) always bypass the gallery and clarification detection
- No changes to Feature 4's NL engine, Feature 5's chat message rendering, or Feature 14's RAG pipeline

---

## 6. File Structure

```
floatchat/
└── frontend/
    ├── lib/
    │   ├── queryTemplates.json          # 30+ templates (FR-01)
    │   └── oceanTerms.json              # Curated oceanographic term list (FR-09)
    ├── components/
    │   └── chat/
    │       ├── SuggestedQueryGallery.tsx  # Empty state gallery (FR-04 to FR-08)
    │       ├── AutocompleteInput.tsx      # Typeahead input wrapper (FR-09 to FR-15)
    │       └── ClarificationWidget.tsx    # Chip-based clarification UI (FR-18 to FR-21)
    └── app/
        └── chat/
            └── [sessionId]/
                └── page.tsx              # Additive: mount gallery + clarification logic
```

Existing files modified (additive changes only):
- `frontend/components/chat/ChatInput.tsx` — wrap with `AutocompleteInput`, mount `ClarificationWidget` below, pass prefill-awareness
- `frontend/app/chat/[sessionId]/page.tsx` — render `SuggestedQueryGallery` in empty state, suppress when prefill present

---

## 7. Dependencies

| Dependency | Source | Status |
|---|---|---|
| Fuse.js | npm | ⏳ To be installed |
| `query_history` table | Feature 14 | ✅ Built |
| RAG history/suggestions API | Feature 14 | ✅ Built |
| Multi-provider LLM setup | Feature 4 | ✅ Built |
| `LLM_TIMEOUT_SECONDS` config | Feature 4 | ✅ Built |
| `ChatInput` component | Feature 5 | ✅ Built |
| Chat session page | Feature 5 | ✅ Built |
| Prefill URL parameter handling | Feature 15 | ✅ Built |
| `anomalies` table | Feature 15 | ✅ Built |
| Datasets API (for "Recently Added" badges) | Feature 1 | ✅ Built |

No new backend endpoints required. No new database tables required.

---

## 8. Template Library Specification

The 30+ templates must cover the following categories with at least the example queries listed. These are minimum requirements — the developer may add more.

**Temperature (min 4 templates)**
- Surface temperature anomalies in the North Atlantic this year
- Temperature profiles at depth > 500m in the Indian Ocean
- Temperature trends for a specific float over its lifetime
- Seasonal temperature changes in the Arabian Sea by month

**Salinity (min 4 templates)**
- Surface salinity in the Mediterranean this year
- Salinity at thermocline depth in the Pacific
- Floats showing salinity > 38 PSU in any region
- Salinity vs depth profiles for BGC floats in the Southern Ocean

**BGC Floats (min 4 templates)**
- All BGC floats currently active in the Atlantic
- Dissolved oxygen measurements below 200m depth
- Chlorophyll concentration in the North Pacific spring bloom region
- Nitrate levels in upwelling zones off the coast of Peru

**Regional Comparison (min 4 templates)**
- Compare surface temperature between Arabian Sea and Bay of Bengal this month
- Salinity differences between North Atlantic and North Pacific at 100m depth
- Which ocean region has the highest average temperature this year
- Float density comparison between southern hemisphere basins

**Time Series (min 3 templates)**
- Monthly average temperature in the Southern Ocean over the last 2 years
- How has dissolved oxygen changed in the North Pacific over the last 5 years
- Seasonal cycle of salinity in the Arctic over the past decade

**Float Tracking (min 3 templates)**
- Show the trajectory of float [platform_number] over its lifetime
- Which floats have been active for more than 5 years
- Floats deployed in the last 30 days and their current positions

**Depth Analysis (min 4 templates)**
- Temperature gradient from surface to 2000m in the Indian Ocean
- Oxygen minimum zone depth in the Arabian Sea
- Mixed layer depth estimates from recent profiles
- Deepest profiles available in the Atlantic basin

**Anomalies (min 4 templates)**
- Show all high-severity anomalies detected in the last 7 days
- Which floats have unreviewed temperature anomalies this month
- Anomalies detected in the Arabian Sea in the last 30 days
- Compare anomaly frequency between the Atlantic and Pacific this year

---

## 9. Clarification Detection — Prompt Specification

The clarification detection LLM call uses the following system prompt (exact wording to be implemented):

The system prompt instructs the model to act as an oceanographic query analyst. It receives a user's natural language query and must determine whether the query is specific enough for the ARGO database query engine to return useful results. A query is underspecified if it lacks two or more of: the variable being measured (temperature, salinity, dissolved oxygen, chlorophyll, nitrate, pH), the geographic region or float identifier, the time period of interest, and the depth range. The model returns only a JSON object — no preamble, no explanation.

The `options` arrays in the `clarification_questions` field must contain oceanographically plausible values. For variable chips: temperature, salinity, dissolved oxygen, chlorophyll, nitrate, pH. For region chips: North Atlantic, South Atlantic, North Pacific, South Pacific, Indian Ocean, Southern Ocean, Arctic Ocean, Arabian Sea, Mediterranean Sea. For time period chips: last 30 days, last 6 months, last year, last 5 years, all time. For depth chips: surface (0–10m), shallow (10–200m), intermediate (200–1000m), deep (1000m+).

---

## 10. Resolved Decisions

| # | Decision | Final Resolution |
|---|---|---|
| OQ1 | Personalized "For You" source | Implemented using `GET /api/v1/chat/query-history` with client-side derivation (no new RAG suggestions endpoint) |
| OQ2 | Clarification detection location | Implemented server-side via `POST /api/v1/clarification/detect` (no client-side LLM calls) |
| OQ3 | Clarification submission behavior | Implemented as assembled-query submission when chips are selected; skip path submits original query unchanged |
| OQ4 | Recently-added variable source | Implemented with `GET /api/v1/search/datasets/summaries` and 7-day variable intersection logic |
| OQ5 | Fuzzy matching library choice | Implemented with Fuse.js (`fuse.js` dependency added to frontend) |
