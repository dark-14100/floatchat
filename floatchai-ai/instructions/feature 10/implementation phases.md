# FloatChat - Feature 10: Implementation Phases

Current status: ✅ Completed (Phases 1-9 finished)

## Phase 1: Migration
Goal: Create Alembic migration 008 with admin_audit_log table and new columns for datasets and ingestion_jobs.

Files to create:
- backend/alembic/versions/008_dataset_management.py

Tasks:
1. Create admin_audit_log table with indexes.
2. Add datasets columns: description, is_public, tags (JSONB), deleted_at, deleted_by.
3. Add ingestion_jobs.source with server_default 'manual_upload'.
4. Add downgrade logic for full rollback.

PRD fulfilled: FR-01, FR-02, FR-03, FR-04

## Phase 2: ORM Models
Goal: Add ORM support for new schema.

Files to modify:
- backend/app/db/models.py

Tasks:
1. Add AdminAuditLog ORM model.
2. Add new Dataset columns: description, is_public, tags, deleted_at, deleted_by.
3. Add IngestionJob.source column.

PRD fulfilled: FR-01, FR-02, FR-03

## Phase 3: Notification Module
Goal: Implement shared notification infrastructure.

Files to create:
- backend/app/notifications/__init__.py
- backend/app/notifications/email.py
- backend/app/notifications/slack.py
- backend/app/notifications/sender.py

Files to modify:
- backend/app/config.py

Tasks:
1. Add notification settings to Settings.
2. Implement synchronous SMTP email sender via smtplib.
3. Implement Slack webhook sender via httpx.
4. Implement synchronous notify(event, context) dispatcher with safe fallback behavior.

PRD fulfilled: FR-16, FR-17

## Phase 4: Admin API + Admin Tasks
Goal: Build admin backend APIs and Celery task support.

Files to create:
- backend/app/api/v1/admin.py
- backend/app/admin/__init__.py
- backend/app/admin/tasks.py

Files to modify:
- backend/app/main.py
- backend/app/celery_app.py
- backend/app/ingestion/tasks.py

Tasks:
1. Add admin tasks: hard_delete_dataset_task and regenerate_summary_task.
2. Add app.admin.tasks to Celery include list.
3. Implement all admin endpoints in a single admin.py router.
4. Use POST /admin/datasets/{dataset_id}/hard-delete with confirmation body.
5. Return task_id immediately for hard delete and summary regen.
6. Implement ingestion jobs SSE stream via DB polling every 2 seconds with 15-second heartbeat.
7. Add ingestion success/failure notify() calls in ingestion task.
8. Add audit logging helper and write entries transactionally.

PRD fulfilled: FR-05 through FR-15, FR-18

## Phase 5: Soft Delete Enforcement
Goal: Ensure soft-deleted datasets are fully excluded from researcher-facing search/query paths.

Files to modify:
- backend/app/search/search.py
- backend/app/search/discovery.py
- backend/app/query/schema_prompt.py

Tasks:
1. Add deleted_at IS NULL filter in semantic dataset search and summaries.
2. Add deleted_at check in dataset summary retrieval.
3. Update SCHEMA_PROMPT datasets table description and active dataset guidance.

PRD fulfilled: FR-27

## Phase 6: Feature 15 Stub Activation
Goal: Activate anomaly notification stub.

Files to modify:
- backend/app/anomaly/tasks.py

Tasks:
1. Replace _notify_new_anomalies no-op body to call notify('anomalies_detected', context).
2. Keep function signature unchanged.

PRD fulfilled: FR-19

## Phase 7: Frontend Admin Section
Goal: Build complete admin UI under /admin routes.

Files to create:
- frontend/app/admin/layout.tsx
- frontend/app/admin/page.tsx
- frontend/app/admin/datasets/page.tsx
- frontend/app/admin/datasets/[dataset_id]/page.tsx
- frontend/app/admin/ingestion-jobs/page.tsx
- frontend/app/admin/audit-log/page.tsx
- frontend/components/admin/DatasetUploadPanel.tsx
- frontend/components/admin/DatasetListTable.tsx
- frontend/components/admin/DatasetDetailEditor.tsx
- frontend/components/admin/IngestionJobsTable.tsx
- frontend/components/admin/AuditLogTable.tsx
- frontend/components/admin/AdminSidebar.tsx
- frontend/lib/adminQueries.ts

Tasks:
1. Add admin layout with client-side role guard.
2. Build dashboard cards including GDAC placeholder card (Not configured).
3. Build dataset upload panel with upload progress and drag-drop.
4. Build dataset list and detail management views.
5. Build ingestion jobs real-time table with SSE updates.
6. Build audit log table with filters.

PRD fulfilled: FR-20 through FR-26

## Phase 8: Tests
Goal: Add coverage for admin APIs, notifications, and enforcement behavior.

Files to create:
- backend/tests/test_admin_datasets.py
- backend/tests/test_admin_ingestion.py
- backend/tests/test_admin_audit.py
- backend/tests/test_notifications.py

Files to modify:
- backend/tests/conftest.py

Tasks:
1. Add admin_user fixture with real DB user row.
2. Add endpoint tests for admin routes and 403 behavior.
3. Add notification unit tests.
4. Add soft-delete exclusion verification tests.

PRD fulfilled: Validation for all FRs

## Phase 9: Documentation (Mandatory Final Phase)
Goal: Mark feature complete and document behavior/configuration.

Files to modify:
- instructions/features.md
- README.md

Files to create:
- instructions/feature 10/implementation phases.md

Tasks:
1. Update Feature 10 status and summary in features.md.
2. Add admin + notification env var docs to README.md.
3. Final documentation verification.

PRD fulfilled: Hard Rule #12
