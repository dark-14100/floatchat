# FloatChat — Feature 15: Anomaly Detection
## Product Requirements Document (PRD)

**Feature Name:** Anomaly Detection
**Version:** 1.1
**Status:** ✅ Implemented
**Depends On:** Feature 1 (Data Ingestion — profiles are the input), Feature 2 (Ocean Database — spatial queries underpin all four detectors), Feature 7 (Geospatial Map — anomaly overlay extends the existing ExplorationMap), Feature 13 (Auth — `reviewed_by` FK and admin-only review action), Feature 14 (RAG Pipeline — anomaly investigation flow benefits from RAG being live, "Investigate in Chat" deep link hands off to the RAG-enhanced query engine)
**Blocks:** Feature 10 (Dataset Management — shares notification infrastructure), Feature 12 (Monitoring — anomaly scan job health is a key operational signal)

---

## 1. Purpose & Background

### 1.1 What Problem Does This Solve?
Feature 1's ingestion-time QC flagging catches physically impossible values — temperatures above 40°C, negative salinity — at the moment a profile enters the database. These are hard physical violations and are handled at the data layer.

Feature 15 addresses a different and more scientifically interesting class of problem: values that are physically valid but contextually unusual. A temperature of 28°C in the Arabian Sea is not physically impossible, but if every other float within 200km is reading 24°C, that 28°C reading is anomalous and scientifically significant. Feature 1 would never flag it. Feature 15 will.

This distinction matters for researchers. Anomalies in this sense are often the most valuable signals in oceanographic data — they may indicate upwelling events, cyclone mixing, freshwater intrusions, instrument drift, or genuinely novel oceanographic conditions. Without automated detection, researchers would have to notice these patterns manually by querying the database — which almost never happens in practice.

### 1.2 What This Feature Is
A nightly automated scanning system that runs four independent statistical detectors against profiles ingested in the last 24 hours, stores detected anomalies in a dedicated table, and surfaces them to researchers through a notification badge, a detail panel, and a map overlay. Researchers can investigate any anomaly directly in the chat interface via a deep link that pre-fills a query. Anomalies can be marked reviewed by authenticated users.

### 1.3 What This Feature Is Not
- It does not replace Feature 1's ingestion-time QC flagging — the two systems are complementary and non-overlapping
- It does not use machine learning models — all four detectors are statistical (standard deviation thresholds against computed baselines)
- It does not run in real-time — detection is nightly, not triggered per ingestion
- It does not automatically suppress or hide flagged profiles from query results — anomalous profiles remain fully queryable
- It does not send notifications in v1 (Slack webhook / email infrastructure is shared with Feature 10 and will be activated when Feature 10 is built)

### 1.4 Why Build It Now
Feature 14 (RAG Pipeline) is live. The "Investigate in Chat" deep link — the primary researcher action on an anomaly — is significantly more useful now that the query engine improves with usage. Anomaly detection without a strong query engine is a dead end; anomaly detection with RAG is a workflow. The sequencing is intentional.

---

## 2. Goals & Success Criteria

### 2.1 Goals
- Automatically surface contextually unusual oceanographic readings that researchers would otherwise miss
- Give researchers a one-click path from anomaly discovery to investigation
- Provide a reviewed/unreviewed workflow so anomalies don't pile up unacknowledged
- Extend the geospatial map with anomaly context without degrading map performance

### 2.2 Success Criteria

| Criterion | Target |
|---|---|
| Nightly scan completion time (full global dataset) | < 30 minutes |
| False positive rate (researcher marks "not anomalous") | < 20% over first 30 days |
| Anomaly detail panel load time | < 1 second |
| Map overlay render time with anomaly markers | No regression vs baseline map load |
| Detector coverage | All four detectors run every night without failure |
| Cold start (no baselines yet) | Spatial and float self-comparison detectors run; seasonal detector skips gracefully |

---

## 3. User Stories

### 3.1 Researcher
- **US-01:** As a researcher, I want to be notified when FloatChat detects something unusual in the ocean data, so I don't have to manually hunt for anomalies.
- **US-02:** As a researcher, I want to see flagged profiles plotted against their regional baseline on a chart, so I can quickly assess whether an anomaly is scientifically interesting.
- **US-03:** As a researcher, I want to click "Investigate in Chat" on an anomaly and have FloatChat pre-fill a relevant query, so I can go from anomaly to analysis in one click.
- **US-04:** As a researcher, I want to see anomalous floats highlighted on the map, so I can understand the spatial context of a detected anomaly.
- **US-05:** As a researcher, I want to mark an anomaly as reviewed, so the badge count stays meaningful and I know what I've already looked at.

### 3.2 Admin
- **US-06:** As an admin, I want the nightly scan to run automatically without manual intervention, so anomaly detection is reliable and doesn't require operational overhead.
- **US-07:** As an admin, I want to see when the last scan ran and whether it completed successfully, so I can monitor the health of the detection system.

---

## 4. Functional Requirements

### 4.1 Database: `anomalies` Table

**FR-01 — Table Definition**
Create an `anomalies` table with the following columns:
- `anomaly_id` — UUID primary key, server-generated via `gen_random_uuid()`
- `float_id` — INTEGER, not null, foreign key to `floats.float_id` ON DELETE CASCADE
- `profile_id` — BIGINT, not null, foreign key to `profiles.profile_id` ON DELETE CASCADE
- `anomaly_type` — VARCHAR(50), not null — one of: `spatial_baseline`, `float_self_comparison`, `cluster_pattern`, `seasonal_baseline`
- `severity` — VARCHAR(10), not null — one of: `low`, `medium`, `high`
- `variable` — VARCHAR(50), not null — the oceanographic variable that triggered the anomaly (e.g. `temperature`, `salinity`, `dissolved_oxygen`)
- `baseline_value` — FLOAT, not null — the expected value from the relevant baseline computation
- `observed_value` — FLOAT, not null — the actual value from the flagged profile
- `deviation_percent` — FLOAT, not null — percentage deviation from baseline
- `description` — TEXT, not null — human-readable explanation of the anomaly, generated by the detector
- `detected_at` — TIMESTAMP WITH TIME ZONE, not null, default `now()`
- `region` — VARCHAR(100), nullable — name of the nearest ocean region if resolvable
- `is_reviewed` — BOOLEAN, not null, default `false`
- `reviewed_by` — UUID, nullable, foreign key to `users.user_id` ON DELETE SET NULL
- `reviewed_at` — TIMESTAMP WITH TIME ZONE, nullable

**FR-02 — Indexes on `anomalies`**
- B-tree index on `detected_at` — for time-ordered listing and nightly deduplication checks
- B-tree index on `float_id` — for float-scoped anomaly lookups
- B-tree index on `(is_reviewed, detected_at)` — for the unreviewed badge count query
- B-tree index on `severity` — for severity-filtered listing

### 4.2 Database: `anomaly_baselines` Table

**FR-03 — Table Definition**
Create an `anomaly_baselines` table with the following columns:
- `baseline_id` — SERIAL primary key
- `region` — VARCHAR(100), not null — ocean region name matching `ocean_regions.name`
- `variable` — VARCHAR(50), not null — oceanographic variable
- `month` — INTEGER, not null — calendar month (1–12)
- `mean_value` — FLOAT, not null — climatological monthly mean for this region/variable/month
- `std_dev` — FLOAT, not null — standard deviation
- `sample_count` — INTEGER, not null — number of profiles used to compute this baseline
- `computed_at` — TIMESTAMP WITH TIME ZONE, not null, default `now()`

**FR-04 — Unique Constraint and Index on `anomaly_baselines`**
- Unique constraint on `(region, variable, month)` — one baseline row per region/variable/month combination
- B-tree index on `(region, variable, month)` — for fast seasonal detector lookups

**FR-05 — Migration**
Alembic migration file `007_anomaly_detection.py` with `down_revision = "006"`. Down migration drops both tables and all indexes cleanly.

### 4.3 Backend: Detection Module (`app/anomaly/`)

**FR-06 — Module Structure**
Create `app/anomaly/` as a new package containing:
- `detectors.py` — the four detector classes
- `tasks.py` — the Celery beat task that orchestrates nightly scanning
- `baselines.py` — functions for computing and refreshing `anomaly_baselines`

**FR-07 — Severity Classification**
All four detectors use the same severity scale based on deviation from baseline:
- `low` — deviation between 1.5 and 2.0 standard deviations (float self-comparison detector uses 1.5 as its threshold, so its minimum is `low`)
- `medium` — deviation between 2.0 and 3.0 standard deviations
- `high` — deviation greater than 3.0 standard deviations

**FR-08 — Spatial Baseline Detector**
For each profile ingested in the last 24 hours, and for each measured variable:
1. Query all profiles from the same calendar month (any year) with a position within 200km, using `ST_DWithin` on `profiles.geom`
2. Compute mean and standard deviation of the variable across those profiles
3. If the current profile's value deviates by more than 2 standard deviations from the regional mean, create an anomaly record
4. Minimum sample requirement: at least 10 comparison profiles must exist before flagging. If fewer than 10 exist, skip without flagging.
5. Description format: `"[Variable] reading of [observed]°C/PSU is [deviation]% above/below the regional mean of [baseline]°C/PSU for [month] (based on [N] nearby profiles)"`

**FR-09 — Float Self-Comparison Detector**
For each profile ingested in the last 24 hours, and for each measured variable:
1. Query the float's own last 10 profiles ordered by `timestamp DESC`
2. Compute mean and standard deviation of the variable across those 10 profiles
3. If the current profile's value deviates by more than 1.5 standard deviations from the float's own recent mean, create an anomaly record
4. Minimum sample requirement: at least 5 historical profiles from the same float must exist. If fewer than 5 exist, skip.
5. This detector catches both instrument drift (gradual sustained shift) and sudden real events at a float level
6. Description format: `"[Variable] reading of [observed] is [deviation]% above/below this float's recent mean of [baseline] (based on last [N] profiles)"`

**FR-10 — Cluster Pattern Detector**
Run once per nightly scan, not per-profile:
1. Find all anomalies detected by the Spatial Baseline Detector and Float Self-Comparison Detector in the current scan run
2. For each unique variable, find groups of 3 or more anomalous floats within 500km of each other with `detected_at` within a 7-day window
3. For each qualifying cluster, create one additional anomaly record of type `cluster_pattern` with `severity = high`
4. The cluster anomaly record uses the centroid of the cluster as its spatial reference and the mean observed value as `observed_value`
5. Description format: `"Cluster of [N] floats within [radius]km all showing anomalous [variable] readings within 7 days — possible regional event"`
6. This detector depends on the other two detectors having already run in the same scan cycle

**FR-11 — Seasonal Baseline Detector**
For each profile ingested in the last 24 hours, and for each measured variable:
1. Look up the pre-computed baseline in `anomaly_baselines` for the profile's nearest ocean region, the current calendar month, and the variable
2. If no baseline row exists for this region/variable/month, skip without flagging (cold start behaviour)
3. If a baseline row exists but `sample_count < 30`, skip without flagging (insufficient baseline quality)
4. If the observed value deviates by more than 2 standard deviations from the baseline mean, create an anomaly record
5. Description format: `"[Variable] reading of [observed] is [deviation]% outside the climatological [month] baseline of [baseline] ± [std_dev] for the [region] region"`

**FR-12 — Deduplication**
Before inserting any anomaly record, check whether an anomaly with the same `(profile_id, anomaly_type, variable)` already exists in `anomalies`. If it does, skip the insert. This prevents re-flagging the same profile on subsequent scan runs.

**FR-13 — Baseline Computation (`baselines.py`)**
`compute_all_baselines(db)`:
- Iterates over all combinations of ocean region × oceanographic variable × calendar month
- For each combination, queries all measurements from profiles whose `geom` falls within the region polygon, grouped by calendar month
- Computes mean and standard deviation
- Upserts into `anomaly_baselines` using the unique constraint on `(region, variable, month)`
- Minimum sample requirement: at least 30 measurements. Combinations with fewer than 30 are not written.
- This function is called once as a one-time setup script after the first ingestion run and is also callable manually by an admin

### 4.4 Backend: Celery Beat Scheduler

**FR-14 — Nightly Scan Task**
A Celery beat task `run_anomaly_scan` scheduled at 02:00 UTC nightly:
1. Open a read-write database session
2. Run Spatial Baseline Detector on profiles selected by the configured recency window (`created_at` proxy in current implementation)
3. Run Float Self-Comparison Detector on the same profile set
4. Run Seasonal Baseline Detector on the same profile set
5. Run Cluster Pattern Detector using the anomalies created in steps 2–4
6. Log total anomalies created, broken down by detector and severity, via structlog
7. On any unhandled exception: log at ERROR level, do not re-raise — the task must not crash the Celery worker

**FR-15 — Celery Beat Configuration**
Add `run_anomaly_scan` to the Celery beat schedule in `celery_app.py` using `crontab(hour=2, minute=0)`.

### 4.5 Backend: API Endpoints

**FR-16 — `GET /api/v1/anomalies`**
Returns a paginated list of anomalies. Query parameters:
- `severity` — filter by severity (`low`, `medium`, `high`)
- `anomaly_type` — filter by detector type
- `variable` — filter by variable
- `is_reviewed` — filter by reviewed status (`true`/`false`)
- `days` — only return anomalies detected in the last N days (default: 7)
- `limit` — page size (default: 50, max: 200)
- `offset` — pagination offset

Response includes: all `anomalies` fields plus float `platform_number` and latest position coordinates for map rendering.

Requires authentication. All authenticated users can list anomalies.

**FR-17 — `GET /api/v1/anomalies/{anomaly_id}`**
Returns full anomaly detail including:
- All `anomalies` table fields
- Float metadata (platform_number, float_type, deployment info)
- The flagged profile's full measurement data
- The baseline comparison data used to flag it (for chart rendering)
- Fields required for client-side construction of an "Investigate in Chat" deep link

Requires authentication.

**FR-18 — `PATCH /api/v1/anomalies/{anomaly_id}/review`**
Marks an anomaly as reviewed. Sets `is_reviewed = true`, `reviewed_by = current_user.user_id`, `reviewed_at = now()`. Returns the updated anomaly record. Requires authentication — any authenticated user can mark anomalies reviewed (not admin-only).

### 4.6 Frontend

**FR-19 — Unreviewed Badge in SessionSidebar**
Add a bell icon to the `SessionSidebar` component. The icon displays a badge with the count of unreviewed anomalies detected in the last 7 days. The count is fetched on page load and refreshed every 5 minutes. Clicking the bell navigates to an anomaly feed view. If the count is zero, the bell is shown without a badge.

**FR-20 — Anomaly Feed View**
A scrollable list of recent anomalies accessible from the sidebar bell icon. Each list item shows: severity indicator (colour-coded), float platform number, variable, brief description, detected_at timestamp, and reviewed status. Supports the same filters as the `GET /api/v1/anomalies` endpoint. Clicking a list item opens the anomaly detail panel.

**FR-21 — Anomaly Detail Panel**
A side panel (or modal) showing full anomaly detail:
- Severity badge and anomaly type label
- Float metadata and profile timestamp
- A chart showing the flagged profile's variable plotted against the baseline (mean ± 2 std dev band)
- The anomaly description text
- "Investigate in Chat" button — deep links to the chat interface with a pre-filled query referencing the float platform number, variable, and date
- "Mark as Reviewed" button — calls `PATCH /api/v1/anomalies/{id}/review` and updates the UI immediately

**FR-22 — Anomaly Map Overlay**
Extend Feature 7's `ExplorationMap` with an optional anomaly overlay toggle. When enabled:
- Floats with unreviewed anomalies detected in the last 7 days are shown with a warning marker overlaid on their position marker
- Warning markers are colour-coded by highest severity for that float (red = high, amber = medium, yellow = low)
- Clicking a warning marker opens the anomaly detail panel for the most recent anomaly for that float
- The overlay is off by default and toggled via a control in the map UI

---

## 5. Non-Functional Requirements

### 5.1 Performance
- The nightly scan must complete within 30 minutes for the full global ARGO dataset (~2 million profiles)
- Spatial queries in the detectors must use the existing GiST index on `profiles.geom` — no sequential scans
- The `anomaly_baselines` table is small (bounded by regions × variables × 12 months) and can be fully cached in memory during a scan run
- The unreviewed badge count query must be fast — it runs on every page load. The composite index on `(is_reviewed, detected_at)` must be used

### 5.2 Reliability
- The nightly scan task must never crash the Celery worker on unhandled exceptions
- If one detector fails, the other three must still run — each detector's execution is independently wrapped in try/except
- Cold start (no baselines computed yet) must not cause errors — the seasonal detector skips gracefully, the other three run normally
- Re-running the scan on the same data must be idempotent — deduplication (FR-12) prevents duplicate anomaly records

### 5.3 Data Quality
- Anomalies are only created when minimum sample requirements are met (FR-08, FR-09, FR-11) — the system must not flag anomalies based on insufficient comparison data
- Baseline computation (FR-13) requires at least 30 samples — baselines built on fewer measurements are not stored
- The `description` field must always be human-readable and specific enough that a researcher can understand the anomaly without looking at the raw data

---

## 6. Relationship to Feature 1 QC Flagging

| Aspect | Feature 1 QC Flagging | Feature 15 Anomaly Detection |
|---|---|---|
| When it runs | At ingestion time, per profile | Nightly, batch |
| What it catches | Physically impossible values | Contextually unusual values |
| Examples | Temperature > 40°C, salinity < 0 | Temperature 4°C above regional mean |
| Storage | `measurements.is_outlier` flag | `anomalies` table |
| Researcher visibility | Filtered out of results by default | Surfaced proactively via feed and map |
| Complementary | Yes — non-overlapping | Yes — non-overlapping |

---

## 7. File Structure

```
floatchat/
└── backend/
    ├── alembic/
    │   └── versions/
    │       └── 007_anomaly_detection.py     # New migration
    ├── app/
    │   ├── anomaly/
    │   │   ├── __init__.py
    │   │   ├── detectors.py                 # Four detector classes
    │   │   ├── baselines.py                 # Baseline computation functions
    │   │   └── tasks.py                     # Celery beat scan task
    │   ├── api/v1/
    │   │   └── anomalies.py                 # Three API endpoints
    │   ├── db/
    │   │   └── models.py                    # Anomaly + AnomalyBaseline ORM models (additive)
    │   ├── celery_app.py                    # Additive: beat schedule entry
    │   └── config.py                        # Additive: any new anomaly config settings
    └── tests/
        ├── test_anomaly_detectors.py        # Detector unit tests
        ├── test_anomaly_tasks.py            # Task orchestration tests
        └── test_anomaly_api.py              # API endpoint tests
frontend/
    ├── app/
    │   └── anomalies/                       # Anomaly feed page
    ├── components/
    │   ├── anomaly/
    │   │   ├── AnomalyFeedList.tsx
    │   │   ├── AnomalyDetailPanel.tsx
    │   │   └── AnomalyComparisonChart.tsx
    │   ├── layout/
    │   │   └── SessionSidebar.tsx           # Additive: bell icon + badge
    │   └── map/
    │       └── ExplorationMap.tsx           # Additive: anomaly overlay toggle
    └── lib/
        └── anomalyQueries.ts                # Anomaly endpoint client
```

---

## 8. Dependencies

| Dependency | Source | Status |
|---|---|---|
| `profiles.geom` GiST index | Feature 2 migration | ✅ In use |
| `ST_DWithin` spatial queries | Feature 2 / PostGIS | ✅ In use |
| `ocean_regions` table | Feature 2 | ✅ Seeded |
| Celery + Redis | Feature 1 | ✅ Running |
| Celery beat | Feature 1 | ✅ Configured |
| `users.user_id` | Feature 13 | ✅ Built |
| `get_current_user` dependency | Feature 13 | ✅ Built |
| RAG-enhanced chat query engine | Feature 14 | ✅ Built |
| ExplorationMap component | Feature 7 | ✅ Built |
| SessionSidebar component | Feature 5 | ✅ Built |

No new packages required beyond what is already installed.

---

## 9. Testing Requirements

### 9.1 Backend Tests

Implemented test modules:
- `backend/tests/test_anomaly_detectors.py`
- `backend/tests/test_anomaly_tasks.py`
- `backend/tests/test_anomaly_api.py`

**Migration tests:**
- `anomalies` table exists after `alembic upgrade head`
- `anomaly_baselines` table exists
- All indexes exist
- Down migration drops both tables cleanly

**Spatial Baseline Detector tests:**
- Flags profile when deviation > 2 std dev with sufficient comparison profiles
- Does not flag when deviation < 2 std dev
- Does not flag when fewer than 10 comparison profiles exist
- Deduplication: does not create duplicate anomaly for same `(profile_id, anomaly_type, variable)`
- Correct severity classification for low/medium/high deviations

**Float Self-Comparison Detector tests:**
- Flags profile when deviation > 1.5 std dev with sufficient history
- Does not flag when fewer than 5 historical profiles exist
- Does not flag on first 5 profiles from a new float

**Cluster Pattern Detector tests:**
- Creates cluster anomaly when 3+ floats within 500km with anomalies in 7-day window
- Does not create cluster anomaly for fewer than 3 floats
- Does not create cluster anomaly when floats are more than 500km apart

**Seasonal Baseline Detector tests:**
- Flags profile when deviation > 2 std dev from baseline
- Skips gracefully when no baseline row exists for region/variable/month
- Skips gracefully when baseline `sample_count < 30`

**API tests:**
- `GET /api/v1/anomalies` returns paginated results with correct filters applied
- `GET /api/v1/anomalies/{id}` returns full detail including baseline comparison data
- `PATCH /api/v1/anomalies/{id}/review` sets reviewed fields correctly
- All endpoints require authentication — unauthenticated requests return 401

**Celery task tests:**
- `run_anomaly_scan` completes without raising on a healthy dataset
- `run_anomaly_scan` does not raise when all four detectors encounter errors (resilience test)

---

## 10. Resolved Decisions

| # | Decision | Implemented Behavior |
|---|---|---|
| D1 | Recency window basis | Nightly scan uses profile recency window configured by `ANOMALY_SCAN_WINDOW_HOURS` with `profiles.created_at` as ingestion-time proxy; no new `ingested_at` migration column was introduced. |
| D2 | Cluster anomaly granularity | Cluster detector emits one high-severity `cluster_pattern` anomaly per affected float in a qualifying cluster. |
| D3 | Investigate-in-chat query source | Frontend constructs the prefill query from anomaly detail fields and routes to chat using client-side deep link parameters. |
| D4 | Map overlay default state | Anomaly map overlay is off by default and enabled explicitly via toolbar toggle. |
| D5 | Baseline compute trigger surface | Both pathways were implemented: admin API trigger and CLI script (`scripts/compute_baselines.py`). |
| D6 | Notification coupling | Feature 15 ships with no-op notification stubs; notification delivery remains deferred to Feature 10 infrastructure. |
