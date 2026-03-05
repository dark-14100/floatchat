# FloatChat — Feature 8 Implementation Phases

## Phase 1 — Backend Configuration & Export Module Scaffold
**Goal:** Add all export configuration settings and scaffold the export module package.

**Create**
- `backend/app/export/__init__.py`

**Modify**
- `backend/app/config.py`
  - Add:
    - `EXPORT_SYNC_SIZE_LIMIT_MB = 50`
    - `EXPORT_PRESIGNED_URL_EXPIRY_SECONDS = 3600`
    - `EXPORT_TASK_STATUS_TTL_SECONDS = 7200`
    - `EXPORT_BUCKET_NAME = "floatchat-exports"`
    - `EXPORT_MAX_POLL_SECONDS = 120`
    - `EXPORT_MAX_SIZE_MB = 500`

**Done when**
- Settings import works
- `app.export` is importable
- Existing backend tests still pass

---

## Phase 2 — Backend Pure Export Functions
**Goal:** Implement pure format generators and size estimation utilities.

**Create**
- `backend/app/export/csv_export.py`
- `backend/app/export/netcdf_export.py`
- `backend/app/export/json_export.py`
- `backend/app/export/size_estimator.py`

**Done when**
- CSV generation includes metadata comment headers and proper ordering
- NetCDF generation uses ARGO mappings + NetCDF4 classic
- JSON generation replaces NaN/Infinity with null
- Size estimator formulas and borderline async logic implemented
- Existing backend tests still pass

---

## Phase 3 — Backend Export Router + Async Task
**Goal:** Build authenticated export endpoints and async export generation pipeline.

**Create**
- `backend/app/api/v1/export.py`
- `backend/app/export/tasks.py`

**Modify**
- `backend/app/main.py`
  - Register export router under `/api/v1`

**Key decisions implemented**
- Option A row source: frontend sends rows
- Ownership check via `ChatMessage -> ChatSession` where `ChatSession.user_identifier == str(current_user.user_id)`
- Redis staging key for async rows: `export_rows:{task_id}`
- Redis status key: `export_task:{task_id}`
- Hard cap: 500MB (`EXPORT_MAX_SIZE_MB`) returns HTTP 413

**Done when**
- Sync and async paths both work
- Status endpoint works
- Existing backend tests still pass

---

## Phase 4 — Infrastructure Wiring (Celery + MinIO)
**Goal:** Ensure worker discovers export task and export bucket/lifecycle self-heals.

**Modify**
- `backend/app/celery_app.py`
  - Add `app.export.tasks` include and task route
- `backend/celery_worker.py`
  - Import `app.export.tasks`
- `backend/app/main.py`
  - Startup bucket create + lifecycle apply for `floatchat-exports`
- `docker-compose.yml`
  - `minio-setup` creates export bucket + 1-day lifecycle with mc

**Done when**
- Export task is discoverable by Celery worker
- Export bucket exists automatically
- Lifecycle policy is applied
- Existing backend tests still pass

---

## Phase 5 — Frontend Types & Export API Client
**Goal:** Add strongly typed export contracts and API calls.

**Create**
- `frontend/types/export.ts`
- `frontend/lib/exportQueries.ts`

**Done when**
- Types compile
- Sync blob and async queued responses are both handled
- `tsc --noEmit` passes
- `npm run build` passes

---

## Phase 6 — Frontend ExportButton Component
**Goal:** Build self-contained export UI with inline status/progress and polling.

**Create**
- `frontend/components/chat/ExportButton.tsx`

**Behavior**
- Renders only when `rowCount > 0`
- Dropdown: CSV / NetCDF / JSON
- Sync: blob download flow
- Async: poll every 3s up to 40 attempts
- Inline status text (no global toaster dependency)

**Done when**
- All required states work
- Polling cleanup implemented
- `tsc --noEmit` passes
- `npm run build` passes

---

## Phase 7 — ChatMessage Integration (Single Additive Change)
**Goal:** Add ExportButton render in `SuccessMessage` above `ResultTable`.

**Modify**
- `frontend/components/chat/ChatMessage.tsx`
  - Add only:
    - import for `ExportButton`
    - conditional render block before `ResultTable`

**Placement**
- `<div className="flex justify-end mb-2">` immediately before `ResultTable`

**Done when**
- Button appears only for results with `row_count > 0`
- Existing logic remains unchanged
- `tsc --noEmit` passes
- `npm run build` passes

---

## Phase 8 — Backend Export Tests
**Goal:** Validate export format correctness, endpoint behavior, ownership, size limits, and async status flow.

**Create**
- `backend/tests/test_export_api.py`

**Done when**
- New export tests pass
- Existing backend tests still pass

---

## Phase 9 — Frontend Export Tests
**Goal:** Validate ExportButton behavior, sync/async flows, polling, and edge conditions.

**Create**
- `frontend/tests/ExportButton.test.tsx`

**Done when**
- New frontend tests pass
- `tsc --noEmit` passes
- `npm run build` passes
- Existing frontend tests still pass
