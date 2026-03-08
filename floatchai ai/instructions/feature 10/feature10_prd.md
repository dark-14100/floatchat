# FloatChat — Feature 10: Dataset Management
## Product Requirements Document (PRD)

**Feature Name:** Dataset Management
**Version:** 1.0
**Status:** ⏳ Ready for Development
**Depends On:** Feature 1 (Data Ingestion Pipeline — upload triggers the existing ingestion pipeline; `ingestion_jobs` table already populated by Feature 1), Feature 2 (Ocean Database — dataset metadata lives in `datasets` table), Feature 13 (Auth — admin RBAC required throughout), Feature 15 (Anomaly Detection — notification infrastructure stub created in Feature 15's `tasks.py` is activated here)
**Blocks:** Feature 11 (API Layer — external API must respect dataset public/internal visibility set here), Feature 12 (Monitoring — ingestion job health feeds into system monitoring)

---

## 1. Purpose & Background

### 1.1 What Problem Does This Solve?
FloatChat's data layer is only as good as the datasets that have been ingested. Currently, there is no admin-facing interface for any aspect of dataset lifecycle management. Datasets can be uploaded via a raw API call, but there is no way to monitor ingestion progress, recover from failed ingestion jobs, edit dataset metadata, or remove outdated data — all without touching the database directly.

Feature 10 gives the admin a complete dataset lifecycle control panel: upload new data, watch ingestion happen in real time, fix metadata, and retire data that is no longer relevant. It also activates the notification infrastructure stubbed in Feature 15, so admins are alerted when ingestion completes or fails without needing to watch the dashboard.

### 1.2 What This Feature Is
A fully admin-protected section of the FloatChat web application (at `/admin`) that covers four areas of dataset lifecycle management:

1. **Upload** — drag-and-drop `.nc` files and zip archives, with upload progress and auto-triggered ingestion
2. **Ingestion monitoring** — a real-time dashboard of all ingestion jobs with SSE status updates, retry capability, and error log access
3. **Metadata management** — edit dataset name, description, tags, public/internal visibility, and manually trigger LLM summary regeneration
4. **Data retirement** — soft delete (hide from search, preserve data) and hard delete (full removal) with confirmation dialogs and a full audit trail

### 1.3 What This Feature Is Not
- It is not a user-facing feature — all of `/admin` requires the admin role from Feature 13
- It does not change the ingestion pipeline itself (Feature 1) — it only exposes controls over it
- It does not build new ingestion logic — the existing `POST /api/v1/datasets/upload` endpoint already triggers ingestion; this feature builds the UI and monitoring layer on top
- It does not implement the GDAC auto-sync — that is a separate planned feature; this admin panel will eventually show GDAC sync jobs in the same ingestion dashboard, but the sync logic itself is not in scope here
- It does not change how datasets are queried by researchers — the existing search and query endpoints are unmodified

### 1.4 Relationship to Feature 15 (Notification Stub)
Feature 15 created a `_notify_new_anomalies()` stub in `anomaly/tasks.py`. Feature 10 activates the shared notification infrastructure: email via SMTP and Slack via webhook. Once built here, Feature 15's stub can be filled in — but that fill-in is explicitly out of scope for Feature 10. Feature 10's responsibility is building the notification sender functions and triggering them from ingestion completion/failure events.

### 1.5 Relationship to GDAC Auto-Sync
The GDAC auto-sync feature (planned after Feature 9) will create ingestion jobs via the same `ingestion_jobs` table. When GDAC sync is built, its jobs will naturally appear in Feature 10's ingestion dashboard without any schema changes. Feature 10's dashboard must be built with this in mind — it should show all ingestion jobs regardless of source (manual upload or future GDAC sync), with a `source` column visible in the job table.

---

## 2. Goals & Success Criteria

### 2.1 Goals
- Give admins full visibility into the ingestion pipeline without needing database access
- Allow admins to recover from ingestion failures without engineering support
- Allow admins to maintain accurate dataset metadata that researchers see in search
- Allow admins to retire outdated data cleanly with a complete audit trail
- Activate the notification system so admins are informed of ingestion outcomes without watching the dashboard

### 2.2 Success Criteria

| Criterion | Target |
|---|---|
| Ingestion job status visible within 2 seconds of status change | SSE latency < 2s |
| Upload progress visible during file transfer | Progress bar updates at least every 500ms |
| Failed job retry success rate | 100% of retryable failed jobs can be retried via UI |
| Soft delete removes dataset from researcher search results | Immediate, no cache delay |
| Hard delete removes all associated data | Profiles, measurements, and MinIO/S3 files all removed |
| Audit log completeness | Every admin action recorded with user, timestamp, action, and affected entity |
| Notification delivery | Email and/or Slack notification sent within 60 seconds of ingestion completion or failure |
| Admin route protection | All `/admin` routes return 403 for non-admin users |

---

## 3. User Stories

### 3.1 Admin
- **US-01:** As an admin, I want to drag and drop a NetCDF file onto the upload panel and watch it ingest in real time, so I don't need to use the raw API or check the database manually.
- **US-02:** As an admin, I want to see a list of all ingestion jobs with their current status, so I always know whether ingestion is running, queued, completed, or failed.
- **US-03:** As an admin, I want to receive a Slack or email notification when ingestion completes or fails, so I don't need to watch the dashboard.
- **US-04:** As an admin, I want to retry a failed ingestion job with one click, so I don't need engineering support to recover from transient failures.
- **US-05:** As an admin, I want to view the full error log for a failed job, so I can understand what went wrong and whether it is a data problem or an infrastructure problem.
- **US-06:** As an admin, I want to edit a dataset's name, description, and tags, so researcher-facing metadata is accurate and useful.
- **US-07:** As an admin, I want to manually trigger regeneration of a dataset's LLM summary, so I can update the summary if the auto-generated one is poor.
- **US-08:** As an admin, I want to mark a dataset as internal or public, so I can control which datasets are visible to external API consumers (Feature 11).
- **US-09:** As an admin, I want to soft-delete a dataset to remove it from researcher search results without permanently destroying the data, so I can recover it if needed.
- **US-10:** As an admin, I want to hard-delete a dataset with a confirmation dialog showing the impact (profiles, measurements, files affected), so I can cleanly remove data I no longer need with full awareness of what will be destroyed.
- **US-11:** As an admin, I want every action I take in the admin panel to be recorded in an audit log, so there is a complete history of who did what and when.

---

## 4. Functional Requirements

### 4.1 Database Changes

**FR-01 — `admin_audit_log` Table**
Create a new `admin_audit_log` table:
- `log_id` — UUID primary key, default `gen_random_uuid()`
- `admin_user_id` — UUID, not null, foreign key to `users.user_id` ON DELETE SET NULL
- `action` — VARCHAR(100), not null — one of: `dataset_upload_started`, `dataset_soft_deleted`, `dataset_hard_deleted`, `dataset_metadata_updated`, `dataset_summary_regenerated`, `dataset_visibility_changed`, `ingestion_job_retried`
- `entity_type` — VARCHAR(50), not null — one of: `dataset`, `ingestion_job`
- `entity_id` — VARCHAR(100), not null — the ID of the affected dataset or job
- `details` — JSONB, nullable — additional context (e.g. old and new values for metadata updates, number of profiles deleted for hard delete)
- `created_at` — TIMESTAMPTZ, not null, default `now()`

B-tree indexes on: `admin_user_id`, `created_at`, `entity_type + entity_id` composite.

**FR-02 — `datasets` Table Additions**
Add the following columns to the existing `datasets` table via migration:
- `is_public` — BOOLEAN, not null, default `true` — controls visibility to external API (Feature 11)
- `tags` — TEXT[], nullable — array of freeform tag strings for admin organisation
- `deleted_at` — TIMESTAMPTZ, nullable — null means active; non-null means soft-deleted
- `deleted_by` — UUID, nullable, foreign key to `users.user_id` ON DELETE SET NULL

**FR-03 — `ingestion_jobs` Table — `source` Column**
Add a `source` column to the existing `ingestion_jobs` table:
- `source` — VARCHAR(50), not null, default `'manual_upload'` — one of: `manual_upload`, `gdac_sync` (for future GDAC auto-sync jobs)

**FR-04 — Migration**
Alembic migration `008_dataset_management.py` with `down_revision = "007"`. Creates `admin_audit_log`, adds new columns to `datasets` and `ingestion_jobs`, adds all indexes. Down migration cleanly reverts all changes. Includes `GRANT SELECT ON admin_audit_log TO floatchat_readonly` using the conditional `DO $$ IF EXISTS` pattern.

### 4.2 Backend: Admin API Endpoints

All endpoints in this section are mounted at `/api/v1/admin` and require `get_current_admin_user` from Feature 13's auth dependencies. Non-admin requests return 403.

**FR-05 — `GET /api/v1/admin/datasets`**
Returns paginated list of all datasets including soft-deleted ones (admin sees everything). Query parameters: `include_deleted` (bool, default false), `is_public` (bool, optional filter), `tags` (comma-separated string, optional filter), `limit` (default 50, max 200), `offset`. Response includes: all `datasets` fields including `is_public`, `tags`, `deleted_at`, `deleted_by`, plus `profile_count`, `float_count`, `ingestion_job_count`, and `latest_job_status` derived fields.

**FR-06 — `GET /api/v1/admin/datasets/{dataset_id}`**
Full dataset detail for admin. Returns all dataset fields plus: complete ingestion job history for this dataset, full variable list, date range, float count, profile count, measurement count, storage size estimate (from MinIO/S3 object metadata where available).

**FR-07 — `PATCH /api/v1/admin/datasets/{dataset_id}/metadata`**
Update dataset metadata. Accepts: `name` (string), `description` (string), `tags` (string array), `is_public` (bool). All fields optional — only provided fields are updated. Records `dataset_metadata_updated` or `dataset_visibility_changed` action in `admin_audit_log` as appropriate (visibility change gets its own action type for easier audit filtering). Returns updated dataset. 404 if not found.

**FR-08 — `POST /api/v1/admin/datasets/{dataset_id}/regenerate-summary`**
Triggers background regeneration of the dataset's LLM summary via a Celery task. Returns immediately with `{ "task_id": "..." }`. Records `dataset_summary_regenerated` in `admin_audit_log`. 404 if not found.

**FR-09 — `POST /api/v1/admin/datasets/{dataset_id}/soft-delete`**
Marks the dataset as soft-deleted: sets `deleted_at = now()`, `deleted_by = current_admin.user_id`. Does not remove any data. After soft delete, the dataset is excluded from all researcher-facing search and query endpoints (the existing search and dataset listing endpoints must check `deleted_at IS NULL`). Records `dataset_soft_deleted` in `admin_audit_log` with profile count in `details`. Returns updated dataset. 404 if not found. 409 if already soft-deleted.

**FR-10 — `POST /api/v1/admin/datasets/{dataset_id}/restore`**
Restores a soft-deleted dataset: sets `deleted_at = null`, `deleted_by = null`. Records a `dataset_metadata_updated` action with `{ "action": "restore" }` in details. 404 if not found. 409 if not currently soft-deleted.

**FR-11 — `DELETE /api/v1/admin/datasets/{dataset_id}`**
Hard delete. Requires a request body confirmation: `{ "confirm": true, "confirm_dataset_name": "<exact name>" }` — both fields must be present and correct, otherwise 400. On confirmation:
1. Delete all measurements for all profiles in this dataset
2. Delete all profiles for this dataset
3. Delete all anomalies linked to profiles in this dataset
4. Delete raw files from MinIO/S3
5. Delete the dataset row
6. Record `dataset_hard_deleted` in `admin_audit_log` with `{ "profiles_deleted": N, "measurements_deleted": N, "files_deleted": N }` in details

All steps run in a single database transaction (except MinIO/S3 deletion, which happens after the DB commit). If MinIO/S3 deletion fails, log at ERROR level but do not fail the request — the database records are already gone. Returns `{ "deleted": true, "profiles_deleted": N, "measurements_deleted": N }`. 404 if not found.

**FR-12 — `GET /api/v1/admin/ingestion-jobs`**
Returns paginated list of all ingestion jobs across all datasets. Query parameters: `status` (filter), `source` (filter: `manual_upload`, `gdac_sync`), `dataset_id` (filter), `days` (jobs from last N days, default 7), `limit` (default 50, max 200), `offset`. Response includes all `ingestion_jobs` fields including the new `source` column.

**FR-13 — `POST /api/v1/admin/ingestion-jobs/{job_id}/retry`**
Retries a failed ingestion job. Only allowed when job `status = 'failed'`. Re-enqueues the Celery ingestion task for the same dataset and file. Resets job status to `queued`. Records `ingestion_job_retried` in `admin_audit_log`. Returns updated job. 404 if not found. 409 if job is not in `failed` status.

**FR-14 — `GET /api/v1/admin/ingestion-jobs/stream`**
SSE endpoint streaming real-time ingestion job status updates. Follows the same SSE pattern as the existing chat SSE endpoint. Emits events when any job's status changes. Admin authenticated via the same SSE auth mechanism used in the chat endpoint. Streams: `{ "job_id": "...", "status": "...", "progress_pct": N, "profiles_ingested": N, "error_message": "..." }`. Client reconnects automatically on disconnect.

**FR-15 — `GET /api/v1/admin/audit-log`**
Returns paginated audit log. Query parameters: `admin_user_id` (filter), `action` (filter), `entity_type` (filter), `days` (default 30), `limit` (default 100, max 500), `offset`. Requires admin role. Returns full `admin_audit_log` rows with admin user email joined.

### 4.3 Backend: Notification System

**FR-16 — Notification Module (`app/notifications/`)**
Create `app/notifications/` as a new package containing:
- `email.py` — SMTP email sender using Python's `smtplib` or `aiosmtplib`
- `slack.py` — Slack webhook sender using `httpx` (already installed)
- `sender.py` — unified `notify()` function that dispatches to configured channels

**FR-17 — Notification Configuration**
Add to `config.py` Settings:
- `NOTIFICATIONS_ENABLED` — bool, default `False`
- `NOTIFICATION_EMAIL_ENABLED` — bool, default `False`
- `NOTIFICATION_EMAIL_SMTP_HOST` — string, optional
- `NOTIFICATION_EMAIL_SMTP_PORT` — int, default 587
- `NOTIFICATION_EMAIL_SMTP_USER` — string, optional
- `NOTIFICATION_EMAIL_SMTP_PASSWORD` — string, optional
- `NOTIFICATION_EMAIL_FROM` — string, optional
- `NOTIFICATION_EMAIL_TO` — string, optional (comma-separated for multiple recipients)
- `NOTIFICATION_SLACK_ENABLED` — bool, default `False`
- `NOTIFICATION_SLACK_WEBHOOK_URL` — string, optional

**FR-18 — Notification Triggers**
Notifications are sent (when enabled) on:
- Ingestion job completion (`status = 'completed'`) — "Ingestion complete: dataset X, N profiles ingested"
- Ingestion job failure (`status = 'failed'`) — "Ingestion failed: dataset X, error: {error_message}"

Notifications are sent from the Celery ingestion task after status is updated. The notification call is non-blocking — failure to send a notification must never fail the ingestion task.

**FR-19 — Feature 15 Notification Stub Activation**
The `_notify_new_anomalies()` stub in `app/anomaly/tasks.py` is filled in to call `notify()` from the new `app/notifications/sender.py`. This is a small additive change to an existing file and is part of Feature 10's scope.

### 4.4 Frontend: Admin Section

All admin frontend routes are under `/admin`. All pages check the current user's role on mount — if not admin, redirect to `/` with a 403 toast.

**FR-20 — Admin Layout**
Create a persistent admin layout at `frontend/app/admin/layout.tsx` with:
- Admin sidebar navigation: Dashboard (overview), Datasets, Ingestion Jobs, Audit Log
- Admin role guard: check `user.role === 'admin'` on mount; redirect non-admins immediately
- Breadcrumb navigation
- Visual distinction from the main researcher UI (different header colour or "Admin" badge)

**FR-21 — Admin Dashboard Overview Page (`/admin`)**
Summary cards showing:
- Total datasets (active, soft-deleted)
- Ingestion jobs in last 7 days (completed, failed, running)
- Last ingestion completed (timestamp + dataset name)
- Unreviewed anomaly count (linking to the anomaly feed from Feature 15)

**FR-22 — Dataset Upload Panel (`/admin/datasets`)**
The top section of the datasets page contains a `DatasetUploadPanel` component:
- Drag-and-drop zone accepting `.nc` files and `.zip` archives
- Click-to-browse file selection as fallback
- Upload progress bar using `XMLHttpRequest` or `fetch` with streaming progress events
- On upload complete, auto-navigate to the new job in the ingestion jobs table
- Calls the existing `POST /api/v1/datasets/upload` endpoint (unchanged)
- Records upload start in audit log via the new admin endpoints

**FR-23 — Dataset List Table (`/admin/datasets`)**
Below the upload panel, a table of all datasets:
- Columns: name, source, is_public badge, tags, profile count, float count, latest job status, created_at, deleted_at (if soft-deleted, row shown in muted style)
- Toggle to show/hide soft-deleted datasets
- Row click → navigates to dataset detail page
- Sort by: name, created_at, profile count
- Pagination

**FR-24 — Dataset Detail Page (`/admin/datasets/[dataset_id]`)**
Full dataset management page:
- Metadata editor: inline edit for name, description, tags (multi-value input), is_public toggle
- Save button → calls `PATCH /api/v1/admin/datasets/{id}/metadata`
- Dataset statistics: float count, profile count, measurement count, date range, variable list, storage size
- "Regenerate Summary" button → calls `POST /api/v1/admin/datasets/{id}/regenerate-summary`, shows in-progress state
- Current LLM summary displayed read-only
- Soft delete button → confirmation modal with current profile/float count → calls `POST /api/v1/admin/datasets/{id}/soft-delete`
- Hard delete button (red, visually distinct) → confirmation modal requiring user to type the exact dataset name → calls `DELETE /api/v1/admin/datasets/{id}` with confirmation body
- Restore button (shown only for soft-deleted datasets) → calls `POST /api/v1/admin/datasets/{id}/restore`

**FR-25 — Ingestion Jobs Table (`/admin/ingestion-jobs`)**
Real-time table of ingestion jobs:
- Columns: job ID (truncated), dataset name, source badge (`manual_upload` / `gdac_sync`), status badge (colour-coded), progress bar, profiles ingested, duration, created_at, error message (truncated, expands on click)
- SSE connection to `GET /api/v1/admin/ingestion-jobs/stream` — table rows update in real time as job status changes
- "Retry" button on failed job rows → calls `POST /api/v1/admin/ingestion-jobs/{id}/retry` → optimistic UI update to `queued` status
- "View Error Log" → expands inline error log panel for the job row
- Filters: status, source, date range
- Pagination

**FR-26 — Audit Log Page (`/admin/audit-log`)**
Read-only table of all admin actions:
- Columns: timestamp, admin user email, action (human-readable label), entity type, entity ID, details (expandable JSON viewer)
- Filters: action type, admin user, date range
- No edit or delete capability — audit log is append-only
- Pagination

### 4.5 Soft Delete Enforcement

**FR-27 — Search and Query Endpoint Updates**
The following existing endpoints must be updated to exclude soft-deleted datasets:
- `GET /api/v1/search/datasets` — add `WHERE deleted_at IS NULL` filter
- `GET /api/v1/search/datasets/summaries` — same
- All NL query paths that reference `datasets` — the `SCHEMA_PROMPT` description of `datasets` should note that `deleted_at IS NULL` datasets are the active ones, so the NL engine generates correct SQL

These changes are additive — they add a filter condition. The admin endpoints (`/api/v1/admin/datasets`) have their own `include_deleted` parameter and are not affected by this filter.

---

## 5. Non-Functional Requirements

### 5.1 Security
- All `/api/v1/admin/*` endpoints return 403 for any non-admin authenticated user and 401 for unauthenticated requests — no exceptions
- Hard delete requires double confirmation (request body field + exact dataset name match) — a single accidental click cannot destroy data
- Audit log is append-only — no admin can delete or modify audit log entries via the API
- Notification credentials (SMTP password, Slack webhook URL) are stored in environment variables, never in the database or logs

### 5.2 Performance
- The ingestion jobs SSE stream must not create a new database connection per event — use a shared polling approach or database LISTEN/NOTIFY
- The hard delete operation on a large dataset (millions of measurements) may be long-running — it must run in a Celery task, not in the request handler, to avoid HTTP timeout. The endpoint triggers the task and returns immediately with a `task_id`
- The audit log table will grow indefinitely — it must have the `created_at` B-tree index to support time-range queries efficiently

### 5.3 Reliability
- Notification failures must never fail ingestion — all notification calls are wrapped in try/except
- MinIO/S3 deletion failure during hard delete must be logged but not block the response — database records are the source of truth
- If the SSE stream disconnects, the client must reconnect and receive the current state of all active jobs

### 5.4 Audit Completeness
- Every state-changing admin action must write to `admin_audit_log` before returning a response — the write is synchronous, not fire-and-forget
- The audit log entry must be written within the same database transaction as the state change it records

---

## 6. File Structure

```
floatchat/
└── backend/
    ├── alembic/versions/
    │   └── 008_dataset_management.py          # Migration
    ├── app/
    │   ├── api/v1/
    │   │   └── admin.py                       # All admin endpoints
    │   ├── notifications/
    │   │   ├── __init__.py
    │   │   ├── email.py                       # SMTP sender
    │   │   ├── slack.py                       # Slack webhook sender
    │   │   └── sender.py                      # Unified notify() function
    │   ├── anomaly/tasks.py                   # Additive: fill in notification stub
    │   ├── api/v1/search.py                   # Additive: soft-delete filter
    │   ├── config.py                          # Additive: notification settings
    │   ├── db/models.py                       # Additive: AdminAuditLog model, datasets columns
    │   └── main.py                            # Additive: register admin router
    └── tests/
        ├── test_admin_datasets.py
        ├── test_admin_ingestion.py
        ├── test_admin_audit.py
        └── test_notifications.py

frontend/
    ├── app/
    │   └── admin/
    │       ├── layout.tsx                     # Admin layout + role guard
    │       ├── page.tsx                       # Dashboard overview
    │       ├── datasets/
    │       │   ├── page.tsx                   # Upload panel + dataset list
    │       │   └── [dataset_id]/page.tsx      # Dataset detail + metadata editor
    │       ├── ingestion-jobs/
    │       │   └── page.tsx                   # Real-time ingestion jobs table
    │       └── audit-log/
    │           └── page.tsx                   # Audit log table
    ├── components/
    │   └── admin/
    │       ├── DatasetUploadPanel.tsx
    │       ├── DatasetListTable.tsx
    │       ├── DatasetDetailEditor.tsx
    │       ├── IngestionJobsTable.tsx
    │       ├── AuditLogTable.tsx
    │       └── AdminSidebar.tsx
    └── lib/
        └── adminQueries.ts                    # Admin API client functions
```

---

## 7. Dependencies

| Dependency | Source | Status |
|---|---|---|
| `ingestion_jobs` table | Feature 1 | ✅ Built |
| `datasets` table | Feature 2 | ✅ Built |
| `POST /api/v1/datasets/upload` | Feature 1 | ✅ Built |
| `get_current_admin_user` | Feature 13 | ✅ Built |
| Celery + Redis | Feature 1 | ✅ Running |
| MinIO client | Feature 1 | ✅ Configured |
| SSE pattern | Feature 5 | ✅ Built |
| `httpx` | Existing | ✅ Installed |
| Feature 15 notification stub | Feature 15 | ✅ Built (stub only) |
| `anomalies` table (hard delete step 3) | Feature 15 | ✅ Built |
| `aiosmtplib` or `smtplib` | New dependency | ⏳ To confirm |

---

## 8. Open Questions

| # | Question | Owner | Due |
|---|---|---|---|
| OQ1 | Hard delete is potentially long-running on large datasets. The PRD specifies it runs as a Celery task triggered by the DELETE endpoint. What does the frontend do while waiting — poll for task completion, use SSE, or show a fire-and-forget confirmation? The ingestion SSE stream already exists; reusing it for hard delete task progress is one option. | Architecture | Before hard delete implementation |
| OQ2 | The SSE stream for ingestion jobs (`GET /api/v1/admin/ingestion-jobs/stream`) — should it stream all active jobs globally, or per-dataset? A global stream is simpler and appropriate for an admin panel. Confirm. | Architecture | Before FR-14 implementation |
| OQ3 | Email notifications: use `smtplib` (synchronous, simpler) or `aiosmtplib` (async-native, consistent with FastAPI async)? Given that notifications fire from Celery tasks (which are synchronous), `smtplib` may be simpler. | Engineering | Before notifications implementation |
| OQ4 | The summary regeneration endpoint (`POST /admin/datasets/{id}/regenerate-summary`) triggers a Celery task. Does a task already exist in Feature 1 for LLM summary generation that can be re-triggered, or does a new task need to be written? | Architecture | Before FR-08 implementation |
| OQ5 | Audit log retention: should there be any automated cleanup of old audit log entries (e.g. entries older than 1 year), or is the log retained indefinitely? If indefinitely, the `created_at` index is sufficient. If there is a retention policy, a scheduled Celery beat task would be needed. | Product | Before migration |
| OQ6 | The `NOTIFICATION_EMAIL_TO` setting accepts comma-separated recipients. Should there be a maximum recipient count enforced, and should BCC be supported (for privacy between recipients)? | Product | Before email.py implementation |
| OQ7 | For the hard delete confirmation modal, the user must type the exact dataset name. Should this match be case-sensitive or case-insensitive? | Product | Before FR-11 implementation |
| OQ8 | Does the admin dashboard overview page (FR-21) need a "last GDAC sync" card even though GDAC sync is not yet built? Adding a placeholder card now (showing "Not configured") would make the dashboard forward-compatible. | Product | Before dashboard implementation |
