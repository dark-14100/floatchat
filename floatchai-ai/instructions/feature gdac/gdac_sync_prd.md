# FloatChat — GDAC Auto-Sync
## Product Requirements Document (PRD)

**Feature Name:** GDAC Auto-Sync
**Version:** 1.0
**Status:** ⏳ Ready for Development
**Depends On:** Feature 1 (Data Ingestion Pipeline — GDAC sync feeds into the existing ingestion pipeline directly), Feature 10 (Dataset Management — `source = 'gdac_sync'` column already added to `ingestion_jobs` in migration 008; ingestion monitoring dashboard shows GDAC jobs automatically), Feature 13 (Auth — sync jobs are admin-owned operations recorded against a system admin user)
**Blocks:** Feature 11 (API Layer — external consumers expect up-to-date data; GDAC sync is what keeps it current), Feature 12 (System Monitoring — GDAC sync job health is a key operational signal)

---

## 1. Purpose & Background

### 1.1 What Problem Does This Solve?
FloatChat's manual upload endpoint (`POST /api/v1/datasets/upload`) requires an admin to find ARGO NetCDF files, download them, and POST them manually. The ARGO GDAC publishes approximately 400 new float profiles per day across its distributed server network. Without automated sync, the FloatChat database falls behind immediately after the first manual ingestion run and stays behind indefinitely unless someone intervenes.

GDAC Auto-Sync solves this by running a nightly Celery beat task that checks the ARGO GDAC for new and updated profiles since the last successful sync, downloads them, and feeds them into the existing ingestion pipeline. The ingestion pipeline itself (Feature 1) is unchanged — GDAC sync is purely a new data acquisition layer that sits upstream of it.

### 1.2 What the ARGO GDAC Is
The ARGO Global Data Assembly Centre (GDAC) is the authoritative public archive for all ARGO float data. There are two mirror servers:
- `https://data-argo.ifremer.fr` — IFREMER (France), primary
- `https://usgodae.org/ftp/outgoing/argo` — US GODAE, mirror

The GDAC organises data in two directory structures:
- **by-float:** `dac/{dac_name}/{float_id}/` — one directory per float, containing all profiles for that float
- **by-date:** `dac/{dac_name}/{float_id}/profiles/` — individual profile NetCDF files named `{float_id}_{profile_number}.nc`

A key file for sync is the **index file**: `ar_index_global_prof.txt.gz` — a compressed, tab-separated text file updated daily that lists every profile in the GDAC with its file path, date, latitude, longitude, ocean, and profile number. This is the canonical source for determining what is new since the last sync.

The GDAC also publishes `argo_merge-profile_index.txt.gz` which includes BGC (biogeochemical) profiles. Both indexes must be consumed.

### 1.3 What This Feature Is
A nightly automated data acquisition system that:
1. Downloads and parses the GDAC profile index files
2. Identifies profiles that are new or updated since the last successful sync
3. Downloads the corresponding NetCDF files
4. Feeds each file into the existing Feature 1 ingestion pipeline (unchanged)
5. Records all sync activity in a new `gdac_sync_runs` table
6. Surfaces sync status in Feature 10's admin panel via the existing `ingestion_jobs` SSE stream

### 1.4 What This Feature Is Not
- It does not modify the Feature 1 ingestion pipeline — NetCDF files are handed off exactly as if an admin uploaded them manually
- It does not replace the manual upload endpoint — both coexist; manual upload remains useful for one-off datasets and custom data
- It does not implement real-time sync — nightly is sufficient for ARGO data, which is published daily
- It does not download the entire GDAC history on first run — first run is bounded by a configurable lookback window (default: 30 days)
- It does not store raw NetCDF files permanently in MinIO/S3 beyond what the existing ingestion pipeline already does

---

## 2. Goals & Success Criteria

### 2.1 Goals
- Keep FloatChat's database current with the ARGO GDAC without any manual intervention
- Bound the first-run download to a configurable time window to avoid overwhelming the ingestion pipeline
- Make sync activity fully visible in the existing Feature 10 admin panel
- Handle GDAC server failures gracefully — a failed sync night must not corrupt existing data or block future syncs
- Respect GDAC server etiquette — no aggressive parallel downloading that could get FloatChat's IP rate-limited

### 2.2 Success Criteria

| Criterion | Target |
|---|---|
| New profiles available in FloatChat after nightly sync | Within 24 hours of GDAC publication |
| First-run download scope | Bounded by `GDAC_LOOKBACK_DAYS` (default 30) |
| GDAC index parse time | < 2 minutes for full index (~4M rows) |
| Concurrent download workers | Configurable, default 4 (respects GDAC etiquette) |
| Failed sync leaves DB in clean state | No partial profile records; existing data untouched |
| Sync jobs visible in Feature 10 admin panel | Immediately, via existing `source = 'gdac_sync'` column |
| Retry after failure | Next nightly run picks up where last successful sync left off |

---

## 3. User Stories

### 3.1 Admin
- **US-01:** As an admin, I want FloatChat's database to stay current with the ARGO GDAC automatically every night, so I don't have to manually download and upload NetCDF files.
- **US-02:** As an admin, I want to see GDAC sync jobs in the same ingestion dashboard as manual uploads, so I have a single view of all data acquisition activity.
- **US-03:** As an admin, I want to receive a Slack/email notification when a nightly GDAC sync completes or fails, so I know whether data is current without checking the dashboard.
- **US-04:** As an admin, I want to manually trigger a GDAC sync at any time (not just wait for the nightly run), so I can pull fresh data immediately after a known GDAC update.
- **US-05:** As an admin, I want to configure the lookback window for the first sync run, so I control how much historical data is pulled on initial setup.
- **US-06:** As an admin, I want the sync to resume from where it left off if a nightly run fails, so no profiles are skipped silently.

### 3.2 Researcher
- **US-07:** As a researcher, I want FloatChat's data to reflect the latest ARGO observations without asking an admin to upload anything, so I can analyse recent oceanographic events.

---

## 4. Functional Requirements

### 4.1 Database

**FR-01 — `gdac_sync_runs` Table**
Create a new `gdac_sync_runs` table to track every sync run:
- `run_id` — UUID primary key, default `gen_random_uuid()`
- `started_at` — TIMESTAMPTZ not null, default `now()`
- `completed_at` — TIMESTAMPTZ nullable — null while running
- `status` — VARCHAR(20) not null — one of: `running`, `completed`, `failed`, `partial`
- `index_profiles_found` — INTEGER nullable — total new profiles identified in index
- `profiles_downloaded` — INTEGER nullable — profiles successfully downloaded
- `profiles_ingested` — INTEGER nullable — profiles successfully ingested (may differ from downloaded if ingestion fails)
- `profiles_skipped` — INTEGER nullable — profiles already in DB (deduplication)
- `error_message` — TEXT nullable — top-level error if status is `failed`
- `gdac_mirror` — VARCHAR(100) not null — which GDAC mirror was used
- `lookback_days` — INTEGER not null — lookback window used for this run
- `triggered_by` — VARCHAR(20) not null — one of: `scheduled`, `manual`

B-tree indexes on: `started_at`, `status`.

**FR-02 — `gdac_sync_state` Table**
Create a small key-value state table to track the last successful sync checkpoint:
- `key` — VARCHAR(100) primary key
- `value` — TEXT not null
- `updated_at` — TIMESTAMPTZ not null, default `now()`

Initial rows (inserted by migration): `last_sync_index_date` (the date of the last successfully processed GDAC index), `last_sync_completed_at` (ISO timestamp of last completed sync run).

This table allows the sync task to resume from a known good checkpoint rather than re-downloading everything after a failure.

**FR-03 — Migration**
Alembic migration `010_gdac_sync.py` with `down_revision = "009"`. Creates both tables and all indexes. Down migration drops both tables cleanly. Includes `GRANT SELECT ON gdac_sync_runs TO floatchat_readonly` using the conditional `DO $$ IF EXISTS` pattern. Does not grant on `gdac_sync_state` (internal operational table, not for NL queries).

### 4.2 Backend: GDAC Sync Module (`app/gdac/`)

**FR-04 — Module Structure**
Create `app/gdac/` as a new package containing:
- `index.py` — GDAC index file download, decompression, and parsing
- `downloader.py` — NetCDF file download with concurrency control and retry
- `sync.py` — orchestration: calls index, downloader, and ingestion pipeline
- `tasks.py` — Celery beat task wrapping the sync orchestration

**FR-05 — Index Parsing (`index.py`)**
`download_and_parse_index(mirror_url: str) -> list[GDACProfileEntry]`

Downloads `ar_index_global_prof.txt.gz` from the configured GDAC mirror, decompresses it in memory (do not write to disk), parses the tab-separated content, and returns a list of `GDACProfileEntry` objects. Each entry contains: `file_path` (relative path within the GDAC, e.g. `dac/aoml/1234567/profiles/R1234567_001.nc`), `date` (profile observation date), `latitude`, `longitude`, `ocean` (single-letter ocean code), `profiler_type`, `institution`, `date_update` (last modification date on GDAC).

Also downloads and parses `argo_merge-profile_index.txt.gz` for BGC profiles. Deduplicates entries from both indexes by `file_path`.

The index file is large (~50MB compressed, ~400MB uncompressed, ~4M rows). Parsing must use a streaming/line-by-line approach — do not load the entire decompressed content into memory at once.

**FR-06 — New Profile Identification**
After parsing the index, filter to only profiles that are new or updated since the last sync:
- New: `file_path` not present in `profiles` table (check via `profiles.source_file` or equivalent identifier)
- Updated: `date_update` in the index is more recent than the profile's `created_at` in the DB

For the first run (no prior sync checkpoint), filter to profiles where `date` is within the last `GDAC_LOOKBACK_DAYS` days. This bounds the first-run download.

Profiles already in the DB with a matching `source_file` and `date_update` not newer than their `created_at` are skipped (counted as `profiles_skipped`).

**FR-07 — NetCDF Download (`downloader.py`)**
`download_profile_files(entries: list[GDACProfileEntry], mirror_url: str, max_workers: int) -> list[DownloadResult]`

Downloads NetCDF files from the GDAC mirror with controlled concurrency:
- Uses `concurrent.futures.ThreadPoolExecutor` with `max_workers = GDAC_MAX_CONCURRENT_DOWNLOADS` (default 4)
- Each download uses `httpx` with a per-file timeout of `GDAC_DOWNLOAD_TIMEOUT_SECONDS` (default 30)
- Retry logic: up to 3 attempts per file with exponential backoff (1s, 2s, 4s) on network errors
- Downloaded files are held in memory as `bytes` objects — not written to disk
- Returns a list of `DownloadResult` objects: `entry`, `content` (bytes or None), `success` (bool), `error` (str or None)
- Files that fail all 3 attempts are logged at WARNING level and excluded from ingestion; they will be retried on the next nightly run

**FR-08 — Ingestion Pipeline Handoff (`sync.py`)**
For each successfully downloaded NetCDF file:
1. Call the existing `ingest_netcdf_file(file_content: bytes, filename: str, dataset_id: str, job_id: str)` function from Feature 1's ingestion module (or equivalent — exact function name to be confirmed during gap analysis)
2. Pass `source='gdac_sync'` so the resulting `IngestionJob` record has the correct source value (migration 008 already added this column)
3. The ingestion function handles all parsing, QC flagging, database insertion, and LLM summary generation — GDAC sync does not duplicate any of this logic

**FR-09 — Sync Orchestration (`sync.py`)**
`run_gdac_sync(triggered_by: str = 'scheduled', lookback_days: int = None) -> GDACSyncResult`

The main orchestration function:
1. Create a `gdac_sync_runs` row with `status = 'running'`
2. Read `last_sync_index_date` from `gdac_sync_state`
3. Download and parse GDAC index files (FR-05)
4. Filter to new/updated profiles (FR-06)
5. Download NetCDF files with concurrency control (FR-07)
6. Hand off each file to the ingestion pipeline (FR-08)
7. Update `gdac_sync_state` checkpoint to today's date
8. Update `gdac_sync_runs` row: `status = 'completed'` (or `'partial'` if some downloads failed), counts
9. Call `notify('gdac_sync_completed', {...})` or `notify('gdac_sync_failed', {...})` from Feature 10's notification module

If any unhandled exception escapes steps 1–8, catch it, set `status = 'failed'`, log at ERROR level, call notify, and return without updating the checkpoint (so the next run retries from the same point).

**FR-10 — GDAC Mirror Failover**
If the primary GDAC mirror (`GDAC_PRIMARY_MIRROR`) fails to respond within `GDAC_MIRROR_TIMEOUT_SECONDS` (default 10) on index download, automatically retry with the secondary mirror (`GDAC_SECONDARY_MIRROR`). Log the failover at WARNING level. If both mirrors fail, the sync run status is set to `failed` and the checkpoint is not updated.

**FR-11 — Celery Beat Task (`tasks.py`)**
`run_gdac_sync_task` — a Celery task scheduled nightly at 01:00 UTC (one hour before the anomaly detection scan at 02:00, so new profiles are available for anomaly detection on the same night):
- Calls `run_gdac_sync(triggered_by='scheduled')`
- Never raises — top-level exception handler catches everything, logs at ERROR
- Registered in `celery_app.py` beat schedule with `crontab(hour=1, minute=0)`

**FR-12 — Manual Trigger Endpoint**
`POST /api/v1/admin/gdac-sync/trigger` — admin-only endpoint (requires `get_current_admin_user`) that immediately enqueues `run_gdac_sync_task` as a one-off Celery task with `triggered_by='manual'`. Returns `{ "run_id": "...", "status": "queued" }`. Rate-limited to one manual trigger per 10 minutes to prevent accidental repeated triggers.

**FR-13 — Sync Status Endpoint**
`GET /api/v1/admin/gdac-sync/runs` — admin-only endpoint returning paginated list of `gdac_sync_runs` rows ordered by `started_at DESC`. Query parameters: `status` (filter), `days` (default 30), `limit` (default 50), `offset`. Returns all columns.

`GET /api/v1/admin/gdac-sync/runs/{run_id}` — full detail for a single run.

### 4.3 Configuration

**FR-14 — New Config Settings**
Add to `config.py` Settings class:
- `GDAC_SYNC_ENABLED` — bool, default `False` — master switch; sync does not run if false
- `GDAC_PRIMARY_MIRROR` — str, default `'https://data-argo.ifremer.fr'`
- `GDAC_SECONDARY_MIRROR` — str, default `'https://usgodae.org/ftp/outgoing/argo'`
- `GDAC_LOOKBACK_DAYS` — int, default `30` — lookback window for first run
- `GDAC_MAX_CONCURRENT_DOWNLOADS` — int, default `4`
- `GDAC_DOWNLOAD_TIMEOUT_SECONDS` — int, default `30`
- `GDAC_MIRROR_TIMEOUT_SECONDS` — int, default `10`
- `GDAC_INDEX_BATCH_SIZE` — int, default `1000` — number of profiles to process per ingestion batch

### 4.4 Frontend: Admin Panel Extension

**FR-15 — GDAC Sync Section in Feature 10 Admin Panel**
The Feature 10 admin dashboard overview page already has a placeholder "GDAC Sync — Not configured" card (added per OQ8 decision). This feature replaces that placeholder with live data:
- Card shows: last sync timestamp, status badge, profiles ingested in last run, next scheduled run time
- "Trigger Sync Now" button → calls `POST /api/v1/admin/gdac-sync/trigger`
- Link to full sync run history

**FR-16 — Sync Run History Page**
New admin page at `/admin/gdac-sync`:
- Table of sync runs: started_at, status badge, profiles found/downloaded/ingested/skipped, duration, triggered_by, mirror used
- Row click → run detail (error message if failed, full counts)
- "Trigger Sync Now" button at top of page
- GDAC sync jobs also appear in the existing `/admin/ingestion-jobs` page (automatically, via `source = 'gdac_sync'` — no code change needed there)

---

## 5. Non-Functional Requirements

### 5.1 Performance
- Index file parsing must use streaming — never load the full decompressed index into memory
- Default concurrency of 4 downloads respects GDAC server etiquette; configurable up to 10
- Ingestion pipeline handoff is sequential per file (the ingestion pipeline has its own Celery concurrency); GDAC sync does not need to parallelise ingestion
- Full nightly sync (index parse + ~400 new profiles downloaded + ingested) should complete within 2 hours

### 5.2 Reliability
- Checkpoint-based resumption: a failed sync run does not lose progress; the next run retries from the last successful checkpoint
- Individual file download failures are non-fatal: the sync continues with remaining files and records partial completion
- GDAC mirror failover: primary → secondary automatically on failure
- `GDAC_SYNC_ENABLED = False` by default: sync does not run until explicitly enabled, preventing accidental bandwidth usage in development

### 5.3 GDAC Etiquette
- Maximum 4 concurrent connections to the GDAC mirror (configurable)
- Exponential backoff on download failures — no aggressive retry hammering
- The GDAC index is downloaded once per sync run, not once per profile
- User-agent header on all GDAC HTTP requests: `FloatChat/1.0 (oceanographic research platform; contact: {ADMIN_EMAIL})`

### 5.4 Idempotency
- Running the sync task twice in a row produces no duplicate records — the deduplication check in FR-06 prevents re-ingesting profiles already in the database
- The checkpoint is only updated after a fully successful or partial-success run — a failed run leaves the checkpoint unchanged so the same profiles are retried

---

## 6. File Structure

```
floatchat/
└── backend/
    ├── alembic/versions/
    │   └── 010_gdac_sync.py                    # New migration
    ├── app/
    │   ├── gdac/
    │   │   ├── __init__.py
    │   │   ├── index.py                        # Index download + parse
    │   │   ├── downloader.py                   # NetCDF download with concurrency
    │   │   ├── sync.py                         # Orchestration
    │   │   └── tasks.py                        # Celery beat task
    │   ├── api/v1/
    │   │   └── admin.py                        # Additive: gdac-sync endpoints (FR-12, FR-13)
    │   ├── celery_app.py                       # Additive: beat schedule + include
    │   ├── config.py                           # Additive: GDAC config settings
    │   └── db/models.py                        # Additive: GDACSyncRun + GDACSyncState ORM models
    └── tests/
        ├── test_gdac_index.py
        ├── test_gdac_downloader.py
        └── test_gdac_sync.py

frontend/
    ├── app/admin/
    │   ├── page.tsx                            # Additive: replace GDAC placeholder card
    │   └── gdac-sync/
    │       └── page.tsx                        # New sync run history page
    └── components/admin/
        └── GDACSyncPanel.tsx                   # Sync status card + trigger button
```

---

## 7. Dependencies

| Dependency | Source | Status |
|---|---|---|
| Feature 1 ingestion pipeline | Feature 1 | ✅ Built |
| `ingestion_jobs.source` column | Feature 10 migration 008 | ✅ Built |
| Feature 10 admin panel | Feature 10 | ✅ Built |
| `app/notifications/sender.py` | Feature 10 | ✅ Built |
| `get_current_admin_user` | Feature 13 | ✅ Built |
| Celery + Redis | Feature 1 | ✅ Running |
| `httpx` | Existing | ✅ Installed |
| `concurrent.futures` | Python stdlib | ✅ Available |
| `gzip` / `io` for decompression | Python stdlib | ✅ Available |
| Migration 009 (API Layer) | Feature 11 | ⏳ Must be built first |

---

## 8. Open Questions

| # | Question | Owner | Due |
|---|---|---|---|
| OQ1 | What is the exact function signature for handing off a NetCDF file to the Feature 1 ingestion pipeline? The PRD assumes a function like `ingest_netcdf_file(file_content, filename, dataset_id, job_id)` but the actual interface must be confirmed by reading `backend/app/ingestion/` before implementation. | Architecture | Before sync.py implementation |
| OQ2 | The `profiles` table needs a `source_file` or equivalent column to support deduplication (FR-06). Does this column currently exist? If not, migration 010 must add it. The column would store the GDAC relative file path (e.g. `dac/aoml/1234567/profiles/R1234567_001.nc`) and would be indexed for fast lookup. | Architecture | Before migration |
| OQ3 | On the very first run, `GDAC_LOOKBACK_DAYS` bounds the download. But the existing database may already have manually-uploaded profiles that overlap with this window. Should the deduplication check match by `source_file` path (requires OQ2 resolved), by `(float_id, profile_number)`, or by a hash of the profile content? | Architecture | Before FR-06 implementation |
| OQ4 | The GDAC index file has ~4 million rows. Parsing it line-by-line in Python will take some time. Should the index parsing run in the Celery task directly, or should it run in a thread pool executor to avoid blocking the Celery worker's event loop? Note: Celery tasks are synchronous by default, so blocking is expected — but very long blocking (>5 minutes) can cause Celery worker health check failures. | Engineering | Before index.py implementation |
| OQ5 | Should `gdac_sync_runs` be added to `ALLOWED_TABLES` in `schema_prompt.py` so admins can NL-query sync history ("how many profiles were ingested in the last GDAC sync")? Unlike `admin_audit_log`, sync run data is operationally useful for researchers as evidence of data currency. | Product | Before migration |
| OQ6 | The manual trigger endpoint (FR-12) is rate-limited to one trigger per 10 minutes. Should this be enforced server-side (Redis-based rate limit) or is a frontend UI disable-for-10-minutes after trigger sufficient? | Engineering | Before FR-12 implementation |
| OQ7 | GDAC profile files exist in two modes: `R` (real-time, may be updated later) and `D` (delayed-mode, QC'd, final). The `date_update` field in the index captures updates. Should FloatChat re-ingest a profile if its `R` file is replaced by a `D` file (same float, same profile number, different data quality)? This is scientifically important but adds complexity. | Product | Before FR-06 implementation |
| OQ8 | What `ADMIN_EMAIL` value should be used in the User-Agent header for GDAC requests? Should this be a new config setting (`GDAC_CONTACT_EMAIL`) or reuse an existing admin email setting? | Engineering | Before downloader.py implementation |
