# GDAC Auto-Sync - Implementation Phases

## Phase 1 - Migration
Goal: Create GDAC sync tables and required CHECK constraint updates.

Files to create:
- backend/alembic/versions/010_gdac_sync.py

Files to modify:
- none

Tasks:
1. Create migration with `revision = "010"` and `down_revision = "008"`.
2. Create `gdac_sync_runs` table with all PRD columns and status/triggered_by checks.
3. Create indexes on `gdac_sync_runs.started_at` and `gdac_sync_runs.status`.
4. Create `gdac_sync_state` key-value table.
5. Seed `gdac_sync_state` with `last_sync_index_date` and `last_sync_completed_at`.
6. Add conditional `GRANT SELECT ON gdac_sync_runs TO floatchat_readonly` using the existing `DO $$ IF EXISTS` pattern.
7. Update `admin_audit_log.action` CHECK to include `gdac_sync_triggered`.
8. Update `admin_audit_log.entity_type` CHECK to include `gdac_sync_run`.
9. Add downgrade logic for both new tables and CHECK constraints.

PRD requirements fulfilled:
- FR-01, FR-02, FR-03

Depends on:
- none

Done when:
- Migration upgrades and downgrades cleanly.
- New tables and indexes are present.
- Existing backend tests pass.

---

## Phase 2 - ORM Models and Config
Goal: Add ORM support and GDAC settings needed by runtime modules.

Files to create:
- backend/app/gdac/__init__.py

Files to modify:
- backend/app/db/models.py
- backend/app/config.py
- backend/app/query/schema_prompt.py

Tasks:
1. Add `GDACSyncRun` and `GDACSyncState` ORM models to `models.py`.
2. Add GDAC settings to `Settings`:
   - `GDAC_SYNC_ENABLED`
   - `GDAC_PRIMARY_MIRROR`
   - `GDAC_SECONDARY_MIRROR`
   - `GDAC_LOOKBACK_DAYS`
   - `GDAC_MAX_CONCURRENT_DOWNLOADS`
   - `GDAC_DOWNLOAD_TIMEOUT_SECONDS`
   - `GDAC_MIRROR_TIMEOUT_SECONDS`
   - `GDAC_INDEX_BATCH_SIZE`
   - `GDAC_CONTACT_EMAIL`
3. Add `gdac_sync_runs` to `ALLOWED_TABLES` and schema prompt guidance.

PRD requirements fulfilled:
- FR-14, plus ORM backing for FR-01 and FR-02

Depends on:
- Phase 1

Done when:
- Models import correctly.
- New settings load with defaults and no validation issues.
- `gdac_sync_runs` is available in `ALLOWED_TABLES`.
- Existing backend tests pass.

---

## Phase 3 - GDAC Index Parser
Goal: Implement mirror-aware, streaming parse of GDAC index files.

Files to create:
- backend/app/gdac/index.py

Files to modify:
- none

Tasks:
1. Add `GDACProfileEntry` dataclass.
2. Implement `download_and_parse_index(...)` for `ar_index_global_prof.txt.gz`.
3. Also parse `argo_merge-profile_index.txt.gz`.
4. Skip comment/header lines and parse rows line-by-line with gzip streaming.
5. Deduplicate merged entries by `file_path`.
6. Implement primary->secondary mirror failover.
7. Set required User-Agent header with contact-email fallback.

PRD requirements fulfilled:
- FR-05, FR-10

Depends on:
- Phase 2

Done when:
- Parser returns valid entries from fixture/mocked index content.
- Failover path works.
- Existing backend tests pass.

---

## Phase 4 - NetCDF Downloader
Goal: Download profile files concurrently with bounded retries and disk temp files.

Files to create:
- backend/app/gdac/downloader.py

Files to modify:
- none

Tasks:
1. Add `DownloadResult` dataclass.
2. Implement `download_profile_files(...)` with `ThreadPoolExecutor` and max concurrency setting.
3. Use `httpx` timeout per file and retry with backoff (1s, 2s, 4s).
4. Persist successful downloads to temp `.nc` files (not in-memory bytes).
5. Return structured success/failure results without failing the full run.
6. Ensure User-Agent header is always set.

PRD requirements fulfilled:
- FR-07

Depends on:
- Phase 3

Done when:
- Successful downloads create temp files.
- Retry/failure behavior matches spec.
- Existing backend tests pass.

---

## Phase 5 - Sync Orchestration
Goal: Orchestrate index->dedup->download->ingest dispatch with checkpointing.

Files to create:
- backend/app/gdac/sync.py

Files to modify:
- none

Tasks:
1. Add `GDACSyncResult` dataclass.
2. Implement `run_gdac_sync(triggered_by='scheduled', lookback_days=None)`.
3. Create `gdac_sync_runs` row with `running` at start.
4. Read checkpoint state from `gdac_sync_state`.
5. Parse index and filter candidates by lookback/checkpoint window.
6. Deduplicate by parsed `(platform_number, cycle_number)` against `profiles` unique key.
7. Allow R->D re-ingestion for updates.
8. Download in batches using `GDAC_INDEX_BATCH_SIZE`.
9. Create one dataset per run named `GDAC Sync YYYY-MM-DD`.
10. Create `IngestionJob` rows directly with `source='gdac_sync'`.
11. Dispatch `ingest_file_task.delay(...)` with temp file paths.
12. Use `profiles_downloaded` as proxy count for `profiles_ingested`.
13. Update checkpoint only on completed/partial runs.
14. Send `gdac_sync_completed` and `gdac_sync_failed` notifications (non-fatal).
15. Clean up temp files after dispatch in `finally`.

PRD requirements fulfilled:
- FR-06, FR-08, FR-09

Depends on:
- Phase 2, Phase 3, Phase 4

Done when:
- End-to-end orchestration test dispatches at least one ingestion call.
- Run status and counts are persisted correctly.
- Checkpoint behavior matches success/failure rules.
- Existing backend tests pass.

---

## Phase 6 - Celery Task and Beat Wiring
Goal: Register scheduled nightly GDAC sync task at 01:00 UTC.

Files to create:
- backend/app/gdac/tasks.py

Files to modify:
- backend/app/celery_app.py

Tasks:
1. Implement `run_gdac_sync_task` Celery task wrapper.
2. Ensure wrapper never raises and logs top-level failures.
3. Add `app.gdac.tasks` to Celery include list.
4. Add beat schedule entry at `crontab(hour=1, minute=0)`.
5. Add task routing for the GDAC task.

PRD requirements fulfilled:
- FR-11

Depends on:
- Phase 5

Done when:
- Beat config includes GDAC task at 01:00 UTC.
- Existing backend tests pass.

---

## Phase 7 - Admin API Endpoints
Goal: Add manual trigger and sync run status endpoints.

Files to create:
- none

Files to modify:
- backend/app/api/v1/admin.py

Tasks:
1. Add `POST /api/v1/admin/gdac-sync/trigger`.
2. Enforce server-side SlowAPI limit (shared 10-minute window).
3. Queue sync task with `triggered_by='manual'`.
4. Audit log action `gdac_sync_triggered` with entity type `gdac_sync_run`.
5. Add `GET /api/v1/admin/gdac-sync/runs` with filters and pagination.
6. Add `GET /api/v1/admin/gdac-sync/runs/{run_id}` detail endpoint.

PRD requirements fulfilled:
- FR-12, FR-13

Depends on:
- Phase 2, Phase 6

Done when:
- Trigger endpoint queues task and returns queued response.
- Runs list/detail endpoints return expected data.
- Existing backend tests pass.

---

## Phase 8 - Frontend Admin UX
Goal: Replace placeholder card with live GDAC panel and add history page.

Files to create:
- frontend/components/admin/GDACSyncPanel.tsx
- frontend/app/admin/gdac-sync/page.tsx

Files to modify:
- frontend/app/admin/page.tsx
- frontend/lib/adminQueries.ts

Tasks:
1. Add admin query types and functions for GDAC sync APIs.
2. Build `GDACSyncPanel` showing latest run status, timestamp, counts, next run time.
3. Add `Trigger Sync Now` button with loading/error handling.
4. Replace placeholder GDAC card in admin overview page with live panel.
5. Implement `/admin/gdac-sync` history table and detail view behavior.

PRD requirements fulfilled:
- FR-15, FR-16

Depends on:
- Phase 7

Done when:
- Admin overview shows live GDAC status.
- Trigger button works with API feedback.
- History page renders and paginates sync runs.
- Frontend checks pass.

---

## Phase 9 - Tests
Goal: Add dedicated backend tests for parser, downloader, and orchestration.

Files to create:
- backend/tests/test_gdac_index.py
- backend/tests/test_gdac_downloader.py
- backend/tests/test_gdac_sync.py

Files to modify:
- backend/requirements.txt (if `respx` is required and absent)

Tasks:
1. Add parser tests for streaming parse, header skipping, dedup, failover.
2. Add downloader tests for success, retry, and partial failure behavior.
3. Add sync tests for dedup, R->D behavior, checkpoint update rules, and temp cleanup.
4. Mock GDAC HTTP with test-safe infrastructure (respx or patching).

PRD requirements fulfilled:
- Verification for FR-05 through FR-13

Depends on:
- Phase 1 through Phase 8

Done when:
- New GDAC tests pass.
- Full backend test suite passes with no regressions.

---

## Phase 10 - Documentation (Mandatory Final)
Goal: Document completed GDAC Auto-Sync feature and operational usage.

Files to create:
- none

Files to modify:
- instructions/features.md
- README.md
- instructions/feature gdac/implementation phases.md

Tasks:
1. Add GDAC Auto-Sync section to `features.md` and mark complete.
2. Update README with:
   - GDAC endpoints
   - GDAC config variables
   - new DB tables
   - Celery schedule details
   - notes on `profiles_downloaded` proxy counting
3. Mark all phases complete in this file.

PRD requirements fulfilled:
- Hard Rule 12

Depends on:
- Phase 1 through Phase 9

Done when:
- Documentation reflects final implementation accurately.
- User confirms documentation phase complete.
