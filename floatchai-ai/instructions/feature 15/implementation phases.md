# FloatChat — Feature 15 Implementation Phases

**Overall Status:** ✅ Complete (Phases 1-9 finished)

## Phase 1 — Alembic Migration ✅ Completed
**Goal:** Create `anomalies` and `anomaly_baselines` tables with rollback support.

**Files to create**
- `backend/alembic/versions/007_anomaly_detection.py`

**Files to modify**
- None

**Tasks**
1. Create migration `007_anomaly_detection.py` with `down_revision = "006"`.
2. Create `anomalies` table with all Feature 15 fields and constraints.
3. Create `anomaly_baselines` table with unique constraint on `(region, variable, month)`.
4. Add required indexes from the PRD.
5. Add conditional readonly grants to `floatchat_readonly` for both new tables.
6. Implement downgrade to drop both tables and all indexes.
7. Validate upgrade and downgrade.

**PRD requirements fulfilled:** FR-01, FR-02, FR-03, FR-04, FR-05
**Depends on:** None

**Done when**
- Migration upgrade succeeds.
- Migration downgrade succeeds.
- Both tables and indexes are created/dropped as expected.
- Existing backend tests still pass.

---

## Phase 2 — ORM Models + Config ✅ Completed
**Goal:** Add anomaly ORM models and configuration settings.

**Files to create**
- `backend/app/anomaly/__init__.py`

**Files to modify**
- `backend/app/db/models.py` — add `Anomaly` and `AnomalyBaseline` models
- `backend/app/config.py` — add anomaly detection settings
- `backend/.env.example` — document anomaly settings

**Tasks**
1. Add `Anomaly` ORM model.
2. Add `AnomalyBaseline` ORM model.
3. Add anomaly settings to `Settings` in `config.py`.
4. Add anomaly env vars to `.env.example`.

**PRD requirements fulfilled:** FR-01, FR-03, FR-07
**Depends on:** Phase 1

**Done when**
- Models map cleanly to migration schema.
- Settings load with defaults.
- Existing backend tests still pass.

---

## Phase 3 — Baseline Computation Module ✅ Completed
**Goal:** Implement baseline computation and make it callable via CLI and admin API.

**Files to create**
- `backend/app/anomaly/baselines.py`
- `backend/scripts/compute_baselines.py`

**Files to modify**
- None

**Tasks**
1. Implement `compute_all_baselines(db)` in `baselines.py`.
2. Compute mean/std/sample_count by `(region, variable, month)`.
3. Exclude `measurements.is_outlier = true` values.
4. Skip entries with `sample_count < 30`.
5. Upsert into `anomaly_baselines`.
6. Add CLI script wrapper to run baseline computation.

**PRD requirements fulfilled:** FR-13
**Depends on:** Phase 2

**Done when**
- Baselines are computed and upserted correctly.
- Low-sample combinations are skipped.
- CLI script runs successfully.
- Existing backend tests still pass.

---

## Phase 4 — Detector Classes ✅ Completed
**Goal:** Build four detector classes that are unit-testable and never raise.

**Files to create**
- `backend/app/anomaly/detectors.py`

**Files to modify**
- None

**Tasks**
1. Implement `SpatialBaselineDetector`.
2. Implement `FloatSelfComparisonDetector` (`timestamp DESC` ordering).
3. Implement `SeasonalBaselineDetector`.
4. Implement `ClusterPatternDetector` (one anomaly per affected float).
5. Enforce minimum sample requirements.
6. Exclude `is_outlier = true` values from all detector computations.
7. Add dedup check for `(profile_id, anomaly_type, variable)` before insert.
8. Ensure each detector catches exceptions and returns `[]` on failure.

**PRD requirements fulfilled:** FR-06, FR-07, FR-08, FR-09, FR-10, FR-11, FR-12
**Depends on:** Phase 2, Phase 3

**Done when**
- All detectors return correct anomaly objects.
- Insufficient-data cases skip gracefully.
- No detector raises exceptions.
- Existing backend tests still pass.

---

## Phase 5 — Celery Task + Beat Schedule ✅ Completed
**Goal:** Implement nightly scan orchestration.

**Files to create**
- `backend/app/anomaly/tasks.py`

**Files to modify**
- `backend/app/celery_app.py` — add include, route, and beat schedule entry

**Tasks**
1. Implement `run_anomaly_scan` Celery task.
2. Query profiles from last 24h using `created_at` proxy.
3. Run spatial, self-comparison, and seasonal detectors.
4. Pass in-memory anomaly lists into cluster detector.
5. Commit once after all detectors complete.
6. Add no-op notification hook stub with `# TODO: Feature 10`.
7. Add beat schedule at `02:00 UTC` via `crontab(hour=2, minute=0)`.

**PRD requirements fulfilled:** FR-14, FR-15
**Depends on:** Phase 4

**Done when**
- Task runs to completion with no crashes.
- Task creates at least one anomaly on test dataset.
- Cold start (no baselines/no anomalies) runs without error.
- Existing backend tests still pass.

---

## Phase 6 — Backend API Endpoints ✅ Completed
**Goal:** Add anomaly API surface and admin baseline trigger.

**Files to create**
- `backend/app/api/v1/anomalies.py`

**Files to modify**
- `backend/app/main.py` — register anomalies router
- `backend/app/query/schema_prompt.py` — add `anomalies` to `ALLOWED_TABLES` and schema prompt

**Tasks**
1. Implement `GET /api/v1/anomalies` with filters and pagination.
2. Implement `GET /api/v1/anomalies/{anomaly_id}` detail endpoint.
3. Implement `PATCH /api/v1/anomalies/{anomaly_id}/review` (no request body).
4. Implement admin endpoint to trigger baseline computation.
5. Require authentication for all anomaly endpoints.
6. Return stored baseline fields only in detail response.
7. Add `anomalies` table to NL query schema allowlist/prompt.

**PRD requirements fulfilled:** FR-16, FR-17, FR-18
**Depends on:** Phase 2, Phase 3, Phase 4

**Done when**
- All three endpoints function as specified.
- Review endpoint correctly sets reviewed fields.
- Admin baseline trigger works with admin auth only.
- Existing backend tests still pass.

---

## Phase 7 — Frontend Integration ✅ Completed
**Goal:** Build anomaly UI surfaces and map overlay.

**Files to create**
- `frontend/types/anomaly.ts`
- `frontend/lib/anomalyQueries.ts`
- `frontend/app/anomalies/page.tsx`
- `frontend/components/anomaly/AnomalyFeedList.tsx`
- `frontend/components/anomaly/AnomalyDetailPanel.tsx`
- `frontend/components/anomaly/AnomalyComparisonChart.tsx`

**Files to modify**
- `frontend/components/layout/SessionSidebar.tsx` — add bell icon + unreviewed count badge
- `frontend/components/map/ExplorationMap.tsx` — add anomaly overlay toggle and markers

**Tasks**
1. Add anomaly types and API query helpers.
2. Build anomaly feed page and list with filters.
3. Build detail panel with severity, metadata, and actions.
4. Build `AnomalyComparisonChart.tsx` for observed vs baseline band.
5. Implement client-side "Investigate in Chat" prefill link.
6. Implement "Mark as Reviewed" UI flow.
7. Add sidebar badge with initial fetch + 5-minute `setInterval` polling.
8. Add map overlay markers (off by default, graceful failure).

**PRD requirements fulfilled:** FR-19, FR-20, FR-21, FR-22
**Depends on:** Phase 6

**Done when**
- Sidebar badge updates correctly.
- Feed renders and filters work.
- Detail panel opens and actions work.
- Map overlay toggles on/off without breaking base map.
- Existing backend tests still pass.

---

## Phase 8 — Test Coverage ✅ Completed
**Goal:** Add full automated tests for anomaly feature.

**Files to create**
- `backend/tests/test_anomaly_detectors.py`
- `backend/tests/test_anomaly_tasks.py`
- `backend/tests/test_anomaly_api.py`

**Files to modify**
- `backend/tests/conftest.py` or `backend/tests/conftest_feature2.py` only if new shared fixtures are needed

**Tasks**
1. Add unit tests for each detector.
2. Add task orchestration and fault-isolation tests.
3. Add API endpoint behavior tests.
4. Cover cold-start behavior and dedup logic.

**PRD requirements fulfilled:** Testing Requirements section
**Depends on:** Phases 4, 5, 6, 7

**Done when**
- New anomaly tests pass.
- Existing backend tests still pass.

---

## Phase 9 — Documentation (Mandatory Final Phase) ✅ Completed
**Goal:** Update all relevant docs after implementation and tests complete.

**Files to modify**
- `instructions/features.md` — mark Feature 15 complete and update tasks
- `README.md` — add Feature 15 implementation details, schema updates, structure updates, test commands
- `instructions/feature 15/feature15_prd.md` — update status to implemented
- `instructions/feature 15/implementation phases.md` — mark phases complete

**Tasks**
1. Update feature status and build table.
2. Update schema docs (`anomalies`, `anomaly_baselines`).
3. Update project structure docs.
4. Update test and configuration documentation.

**PRD requirements fulfilled:** Hard Rule 11
**Depends on:** Phases 1 through 8

**Done when**
- Docs accurately reflect implemented behavior.
- Documentation phase explicitly confirmed complete.

---

## Completion Summary

- Phase 1 complete: migration `007_anomaly_detection.py` created and validated.
- Phase 2 complete: anomaly ORM models and config/env settings added.
- Phase 3 complete: baseline computation module and CLI script implemented.
- Phase 4 complete: all four detectors implemented with dedup and resilience.
- Phase 5 complete: nightly scan task + Celery beat schedule added.
- Phase 6 complete: anomaly API endpoints and admin baseline trigger implemented.
- Phase 7 complete: sidebar badge, anomaly feed/detail, and map overlay integrated.
- Phase 8 complete: detector/task/API test suites added and passing.
- Phase 9 complete: documentation updated across features registry, README, PRD, and phase tracker.
- Existing backend tests still pass.
