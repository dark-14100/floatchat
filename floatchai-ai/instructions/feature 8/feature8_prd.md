# FloatChat — Feature 8: Data Export System
## Product Requirements Document (PRD)

**Feature Name:** Data Export System
**Version:** 1.0
**Status:** Ready for Development
**Depends On:** Feature 1 (ingestion pipeline — `xarray` already installed), Feature 2 (database schema — profiles and measurements tables), Feature 4 (NL query engine — query results to export), Feature 5 (chat interface — Export button placement), Feature 13 (Auth — all export endpoints require authentication)
**Blocks:** Nothing — this is a standalone feature

---

## 1. Purpose & Background

### 1.1 What Problem Does This Solve?
FloatChat allows researchers to query and visualise oceanographic data within the chat interface. However, researchers need to take data out of FloatChat for use in their own tools — Python notebooks, MATLAB scripts, QGIS, R, and ocean modelling software. Without export, FloatChat is a discovery tool but not a complete research workflow tool.

Feature 8 gives researchers one-click access to query results in the formats their tools already understand: CSV for spreadsheets and pandas, NetCDF for scientific software, and JSON for programmatic consumers.

### 1.2 What This Feature Is
A backend export pipeline and frontend export UI consisting of:
- Three export format functions: CSV (pandas), NetCDF (xarray), JSON
- A single `POST /api/v1/export` endpoint handling all three formats
- Synchronous streaming for small exports (under 50MB)
- Asynchronous Celery task for large exports (50MB and above) with presigned MinIO/S3 URL delivery
- Redis-based task status tracking for async exports
- An Export button on every query result panel in the chat interface
- A download progress indicator for async exports

### 1.3 What This Feature Is Not
- It does not re-execute queries — it exports data that has already been returned in a chat session
- It does not support bulk export of entire datasets outside the context of a query result
- It does not implement scheduled or recurring exports in v1
- It does not implement export history or a download history page in v1

### 1.4 Relationship to Other Features
- Feature 2's `profiles` and `measurements` tables are the data source for raw profile exports
- Feature 4's query results (stored in `chat_messages.result_metadata`) provide the column list and row data for query result exports
- Feature 5's `ChatMessage` component receives the Export button as an additive UI element
- Feature 13's JWT middleware protects all export endpoints — unauthenticated users cannot export
- Feature 14 (RAG) will eventually store successful export queries in `query_history` — export endpoint calls are treated as successful query completions

---

## 2. Goals & Success Criteria

### 2.1 Goals
- Allow researchers to export any chat query result in one click
- Deliver small exports (under 50MB) immediately as a file download
- Deliver large exports (50MB and above) asynchronously with a progress indicator
- Produce scientifically correct output: ARGO-compliant NetCDF, clean CSV with QC flags, and structured JSON with metadata
- Never re-execute a SQL query for an export — use already-retrieved data

### 2.2 Success Criteria

| Criterion | Target |
|---|---|
| Small export response time (CSV/JSON, < 50MB) | < 5 seconds |
| Large export task queue time | < 2 seconds to acknowledge and return task ID |
| Large export completion time (100MB NetCDF) | < 60 seconds |
| MinIO presigned URL expiry | 1 hour |
| Export file correctness — CSV | Passes pandas `read_csv()` without errors |
| Export file correctness — NetCDF | Passes `xarray.open_dataset()` without errors |
| Export file correctness — JSON | Valid JSON, passes schema validation |
| Async task status polling interval | Every 3 seconds from frontend |

---

## 3. User Stories

### 3.1 Researcher
- **US-01:** As a researcher, I want to export a query result as CSV so that I can open it in Excel or load it into a pandas DataFrame.
- **US-02:** As a researcher, I want to export a query result as NetCDF so that I can analyse it in MATLAB or use it with xarray in a Jupyter notebook.
- **US-03:** As a researcher, I want to export a query result as JSON so that I can consume it programmatically or share it with a colleague who is building a tool.
- **US-04:** As a researcher, I want the export to happen immediately for small results, so that I don't have to wait.
- **US-05:** As a researcher, I want to see a progress indicator for large exports, so that I know the download is being prepared and I can continue using the chat while I wait.
- **US-06:** As a researcher, I want the exported file to include the original query and export timestamp as metadata, so that I can trace where the data came from when I return to it later.
- **US-07:** As a researcher, I want the NetCDF export to preserve ARGO variable names and units, so that it is compatible with existing ARGO processing tools.

---

## 4. Functional Requirements

### 4.1 Backend: Export Endpoint

**FR-01 — `POST /api/v1/export`**
Requires authentication (JWT middleware from Feature 13). Request body:
- `message_id` — UUID string, required. The `chat_messages.message_id` whose result is being exported. Used to retrieve row data and query metadata.
- `format` — string, required. One of: `csv`, `netcdf`, `json`
- `filters` — object, optional. Currently supported filters:
  - `variables` — list of variable column names to include (subset selection). If omitted, all variables included.
  - `min_pressure` — float, optional. Exclude measurements shallower than this value.
  - `max_pressure` — float, optional. Exclude measurements deeper than this value.

Processing logic:
1. Fetch `chat_messages` row by `message_id`. Verify the message belongs to a session owned by the requesting user — return HTTP 403 if not.
2. Read `result_metadata.columns` and `result_metadata.row_count` from the message.
3. Read row data from `resultRows[message_id]` — this is the data already retrieved and stored during the SSE stream. If row data is not available server-side (it is currently stored client-side in the Zustand store), see FR-02 for the resolution.
4. Apply any filters from the request body.
5. Estimate the export file size. If estimated size is under `settings.EXPORT_SYNC_SIZE_LIMIT_MB` (default 50MB): generate synchronously and stream directly as a file download response.
6. If estimated size is at or above the limit: enqueue a Celery task, return HTTP 202 with `task_id` and `status: "queued"`.

**FR-02 — Row Data Source**
The rows exported must be the exact rows that were displayed in the chat result — not a re-execution of the query. There are two options depending on where row data is stored at the time of export:

- **Option A (preferred):** The frontend sends the rows as part of the export request body alongside `message_id` and `format`. This is the simplest approach — the frontend already has the rows in the Zustand `resultRows` store.
- **Option B:** The backend persists rows server-side in a short-lived Redis key (`export_rows:{message_id}`) set during the SSE `results` event handling, with TTL matching the session lifetime. The export endpoint reads from this key.

The decision between Option A and Option B must be made during gap analysis before implementation. Both are valid. Option A keeps the backend simpler but increases request payload size. Option B keeps request payloads small but requires server-side row storage.

**FR-03 — Synchronous Export Response**
For exports under the size limit, the endpoint returns a streaming file response:
- `Content-Type`: `text/csv; charset=utf-8` for CSV, `application/x-netcdf` for NetCDF, `application/json` for JSON
- `Content-Disposition`: `attachment; filename=floatchat_{format}_{timestamp}.{ext}`
- `Content-Encoding`: gzip compression applied for CSV and JSON
- File streamed directly — not stored in MinIO for sync exports

**FR-04 — Asynchronous Export Response (Large Files)**
For exports at or above the size limit:
- Return HTTP 202 immediately with body: `{ "task_id": "uuid", "status": "queued", "poll_url": "/api/v1/export/status/{task_id}" }`
- Enqueue `generate_export_task` Celery task with all required parameters
- Task generates the file, uploads to MinIO, generates a presigned URL with 1-hour expiry
- Task updates Redis key `export_task:{task_id}` with current status (`queued`, `processing`, `complete`, `failed`) and the presigned URL on completion

**FR-05 — `GET /api/v1/export/status/{task_id}`**
Requires authentication. Returns current task status from Redis:
- `status: "queued"` — task is waiting
- `status: "processing"` — task is generating the file
- `status: "complete"` — includes `download_url` (presigned MinIO URL) and `expires_at`
- `status: "failed"` — includes `error` message
Returns HTTP 404 if task ID is unknown.

**FR-06 — Export Size Estimation**
Before choosing sync vs async path, estimate the export size:
- CSV: `row_count * average_bytes_per_row` where average is 150 bytes per row (conservative estimate based on all numeric columns)
- NetCDF: `row_count * num_variables * 8 bytes` (float64 per value) plus a 10% overhead for metadata
- JSON: `row_count * average_bytes_per_row * 1.8` (JSON is verbose relative to CSV)
This is an estimate — the actual file may be smaller. If an estimate is borderline (within 10% of the limit), choose the async path to be safe.

### 4.2 Backend: Export Format Functions

**FR-07 — CSV Export (`app/export/csv_export.py`)**
Accepts a list of row dicts and a column list. Produces a flat CSV with one row per measurement.

Column order: `profile_id`, `float_id`, `platform_number`, `juld_timestamp`, `latitude`, `longitude`, `pressure`, then all variable columns present in the data (temperature, salinity, dissolved_oxygen, chlorophyll, nitrate, ph), then QC flag columns for each present variable (`temp_qc`, `psal_qc`, `doxy_qc`, etc.).

Column name conventions:
- `juld_timestamp` exported as ISO 8601 string
- Numeric values exported at full float precision — no rounding
- Missing values exported as empty string (not `NaN`, not `None`, not `99999`)
- QC flag columns exported as integers (1, 2, 3, 4)

File header (first two rows before column names):
- Row 1: `# FloatChat Export`
- Row 2: `# Query: {original nl_query from chat_message}` 
- Row 3: `# Exported: {ISO 8601 timestamp}`
- Row 4: `# Rows: {row_count}`
Then the column header row, then data rows.

UTF-8 encoded, comma-separated, `\n` line endings.

**FR-08 — NetCDF Export (`app/export/netcdf_export.py`)**
Accepts a list of row dicts, column list, and query metadata. Produces an ARGO-compliant NetCDF file using xarray.

Dataset structure:
- Dimension: `N_LEVELS` — one per measurement row (depth level)
- Variables: one `xarray.Variable` per oceanographic column, with correct ARGO attributes:
  - `long_name` — human-readable name (e.g., "Sea water temperature")
  - `units` — ARGO standard units (temperature: "degree_Celsius", salinity: "psu", pressure: "decibar", dissolved_oxygen: "micromole/kg")
  - `_FillValue` — ARGO standard fill value: `99999.0` for floats, `99999` for integers
  - `valid_min` and `valid_max` where applicable
- Coordinate variables: `LATITUDE`, `LONGITUDE`, `JULD` (Julian date, converted back from ISO timestamp), `PRES` (pressure)
- QC flag variables: `TEMP_QC`, `PSAL_QC`, `DOXY_QC` etc. as byte arrays

Global attributes (CF and ARGO conventions):
- `title`: "FloatChat ARGO Data Export"
- `institution`: "FloatChat"
- `source`: "Argo float"
- `history`: "Exported {ISO timestamp} from FloatChat query: {nl_query}"
- `Conventions`: "Argo-3.1 CF-1.6"
- `floatchat_query`: the original NL query
- `floatchat_export_timestamp`: ISO 8601 timestamp

Output format: NetCDF4 classic model. Compression: `zlib=True`, `complevel=4` on all variables.

**FR-09 — JSON Export (`app/export/json_export.py`)**
Accepts a list of row dicts and query metadata. Produces structured JSON.

Structure:
```
{
  "metadata": {
    "query": "<original nl_query>",
    "generated_at": "<ISO 8601 timestamp>",
    "exported_at": "<ISO 8601 timestamp>",
    "row_count": <integer>,
    "columns": ["col1", "col2", ...]
  },
  "profiles": [
    { "col1": value, "col2": value, ... },
    ...
  ]
}
```

Numeric precision: full float precision (not rounded). Timestamps as ISO 8601 strings. Missing values as `null` (not `NaN` — `NaN` is not valid JSON).

### 4.3 Backend: Celery Task

**FR-10 — `generate_export_task` Celery Task (`app/export/tasks.py`)**
Celery task with `bind=True` for access to `self.update_state()`. Parameters: `task_id`, `rows`, `columns`, `format`, `nl_query`, `user_id`.

Task steps:
1. Update Redis `export_task:{task_id}` to `processing`
2. Call the appropriate format function (CSV, NetCDF, or JSON)
3. Upload the resulting bytes to MinIO at path `exports/{user_id}/{task_id}.{ext}`
4. Generate presigned URL with 1-hour expiry
5. Update Redis key to `complete` with `download_url` and `expires_at`
6. On any exception: update Redis key to `failed` with error message, re-raise

Redis TTL for task status keys: 2 hours (longer than the presigned URL expiry so the status remains queryable until after the URL expires).

**FR-11 — MinIO Export Bucket**
Exports are stored in a dedicated `floatchat-exports` bucket in MinIO/S3. Bucket must be created on startup if it doesn't exist (same pattern as existing MinIO bucket setup). Objects in this bucket have a lifecycle policy: auto-delete after 24 hours. This keeps storage costs low since exports are ephemeral.

### 4.4 Frontend: Export UI

**FR-12 — Export Button on `ChatMessage`**
Add an Export dropdown button to the `SuccessMessage` section of `ChatMessage.tsx`. Appears only when `message.result_metadata` is non-null and `result_metadata.row_count > 0`. Positioned in the top-right corner of the result section, above the `ResultTable`.

The Export button uses a `DropdownMenu` from shadcn/ui with three items:
- "Export as CSV" — `FileText` icon from lucide-react
- "Export as NetCDF" — `Database` icon
- "Export as JSON" — `Braces` icon

Clicking any item triggers the export flow for that format.

**FR-13 — Synchronous Export Flow (Frontend)**
When an export is triggered and the backend returns a file stream (HTTP 200 with `Content-Disposition: attachment`):
1. Create a temporary anchor element with `href` set to a blob URL of the response data
2. Programmatically click the anchor to trigger the browser's native download
3. Revoke the blob URL after the click
4. Show a brief success toast: "Download started"

**FR-14 — Asynchronous Export Flow (Frontend)**
When an export is triggered and the backend returns HTTP 202 with a `task_id`:
1. Show an inline progress indicator below the Export button in the `ChatMessage` component
2. Progress indicator shows: "Preparing export..." with an animated spinner
3. Poll `GET /api/v1/export/status/{task_id}` every 3 seconds
4. On `status: "complete"`: trigger browser download using the `download_url`. Show success toast: "Export ready — downloading."
5. On `status: "failed"`: show inline error: "Export failed. Please try again." with a retry button
6. Maximum poll attempts: 40 (2 minutes total). If exceeded: show error "Export is taking longer than expected. Please try again."
7. The progress indicator is dismissed after success or error
8. The user can continue using the chat while the export is being prepared — the progress indicator is non-blocking

**FR-15 — Export Loading State**
While the synchronous export request is in flight (POST request sent, response not yet received):
- Disable the Export dropdown button
- Show a `Loader2` spinner inside the button
- Re-enable the button after the response is received (success or error)

### 4.5 Backend: Configuration

**FR-16 — New Config Settings**
Add to `Settings` class in `backend/app/config.py`:
- `EXPORT_SYNC_SIZE_LIMIT_MB` — default `50` — exports above this size use async path
- `EXPORT_PRESIGNED_URL_EXPIRY_SECONDS` — default `3600` (1 hour)
- `EXPORT_TASK_STATUS_TTL_SECONDS` — default `7200` (2 hours)
- `EXPORT_BUCKET_NAME` — default `"floatchat-exports"`
- `EXPORT_MAX_POLL_SECONDS` — default `120` (2 minutes — informational, used by frontend)

---

## 5. Non-Functional Requirements

### 5.1 Performance
- Synchronous exports under 50MB must complete in under 5 seconds
- Async task must be acknowledged (HTTP 202 returned) in under 2 seconds
- CSV generation: target 10MB/s throughput using pandas streaming write
- NetCDF generation: target 5MB/s using xarray with compression
- JSON generation: target 15MB/s using Python's built-in json module

### 5.2 Correctness
- CSV output must be parseable by `pandas.read_csv()` without any arguments beyond the filename
- NetCDF output must be openable by `xarray.open_dataset()` without errors
- NetCDF output must pass basic ARGO compliance checks: correct variable names, correct units, valid fill values
- JSON output must be valid JSON — no `NaN` values, no `Infinity`, no Python-specific types

### 5.3 Security
- Every export endpoint requires authentication (Feature 13 JWT middleware)
- Users can only export results from their own chat sessions — `message_id` ownership is verified against `current_user.user_id`
- Presigned MinIO URLs expire after 1 hour — they cannot be shared indefinitely
- Export files stored in MinIO are auto-deleted after 24 hours

### 5.4 Storage
- Sync exports are never stored — they stream directly to the client
- Async exports are stored in MinIO with a 24-hour lifecycle policy
- Redis task status keys expire after 2 hours
- No export history table in v1 — exports are ephemeral

---

## 6. File Structure

```
floatchat/
├── backend/
│   ├── app/
│   │   └── export/
│   │       ├── __init__.py
│   │       ├── csv_export.py
│   │       ├── netcdf_export.py
│   │       ├── json_export.py
│   │       ├── tasks.py
│   │       └── size_estimator.py
│   └── api/
│       └── v1/
│           └── export.py
│   └── tests/
│       └── test_export_api.py
└── frontend/
    └── components/
        └── chat/
            └── ExportButton.tsx
    └── lib/
        └── exportQueries.ts
```

Files to modify (additive only):
- `backend/app/config.py` — add 5 new export settings
- `backend/app/main.py` — register export router
- `backend/app/storage/minio_client.py` (or equivalent) — add export bucket creation on startup
- `frontend/components/chat/ChatMessage.tsx` — add ExportButton component
- `frontend/lib/api.ts` — add export API call functions (or add to new `exportQueries.ts`)

---

## 7. Dependencies

### 7.1 Backend
All required packages are already installed from earlier features:
- `pandas` — Feature 1 ✅
- `xarray` — Feature 1 ✅
- `netCDF4` — Feature 1 ✅
- `celery` — Feature 1 ✅
- `redis` — Feature 1 ✅
- `boto3` or `minio` Python client — Feature 1 ✅ (verify which is in use)

No new backend packages required.

### 7.2 Frontend
No new frontend packages required. Uses:
- `shadcn/ui` `DropdownMenu` — already installed
- `lucide-react` — already installed

---

## 8. Testing Requirements

### 8.1 Backend Tests (`test_export_api.py`)
- `POST /api/v1/export` without auth returns HTTP 401
- `POST /api/v1/export` with another user's `message_id` returns HTTP 403
- `POST /api/v1/export` with unknown `message_id` returns HTTP 404
- `POST /api/v1/export` with `format: "csv"` and small result returns file stream with correct Content-Type
- `POST /api/v1/export` with `format: "netcdf"` and small result returns file stream with correct Content-Type
- `POST /api/v1/export` with `format: "json"` and small result returns file stream with correct Content-Type
- `POST /api/v1/export` with large result returns HTTP 202 with `task_id`
- CSV output passes `pandas.read_csv()` — no errors, correct column names
- NetCDF output passes `xarray.open_dataset()` — no errors
- NetCDF output contains correct ARGO global attributes
- JSON output is valid JSON — no NaN values
- JSON output contains `metadata.query` and `metadata.row_count`
- Variable filter in request body correctly excludes columns from output
- Pressure filter correctly excludes out-of-range measurements
- `GET /export/status/{task_id}` returns correct status progression: queued → processing → complete
- `GET /export/status/{unknown_id}` returns HTTP 404
- Size estimator returns values above threshold for large datasets
- Size estimator returns values below threshold for small datasets

### 8.2 Frontend Tests
- Export button renders only when `result_metadata.row_count > 0`
- Export button does not render when result is empty
- Dropdown shows three format options
- Selecting CSV triggers export API call with `format: "csv"`
- Sync export triggers browser download
- Async export shows progress indicator
- Progress indicator polls status endpoint every 3 seconds
- On complete status: browser download triggered
- On failed status: error message shown with retry button
- Max poll attempts exceeded: timeout error shown

---

## 9. Migration

No new database tables are required for Feature 8. No Alembic migration needed.

The only data persistence is:
- Redis keys for async task status (TTL-managed, no migration)
- MinIO object storage for async export files (lifecycle policy, no migration)

---

## 10. Open Questions

| # | Question | Owner | Due |
|---|---|---|---|
| Q1 | Row data source: Option A (frontend sends rows in request body) or Option B (backend persists rows in Redis during SSE)? Option A is simpler but the request payload for a 10,000-row result could be several MB. Option B is cleaner at the API level but requires a new Redis write on every SSE result event. | Architecture | Before implementation |
| Q2 | Should the Export button appear on the `ResultTable` directly, or above it in the `SuccessMessage` section of `ChatMessage`? The PRD specifies above the table, but placing it on the table header might feel more natural. | Frontend | Before ExportButton implementation |
| Q3 | Should exports include only the columns returned in the chat result, or should the backend optionally re-fetch additional columns (e.g., QC flags) that were not in the original query result? For NetCDF correctness, QC flags are important — but they may not always be in the result set. | Science | Before NetCDF implementation |
| Q4 | For the async export, should the presigned MinIO URL be returned directly to the frontend, or should it be proxied through a FloatChat endpoint to avoid exposing the MinIO URL? Proxying adds a download hop but hides infrastructure details. | Architecture | Before async task implementation |
| Q5 | Should there be a maximum export size limit (e.g., 500MB)? Very large exports could exhaust MinIO storage and Celery worker memory. A hard limit with a clear error message is safer than allowing unbounded exports. | Product | Before implementation |
