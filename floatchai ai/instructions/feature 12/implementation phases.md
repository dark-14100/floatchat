# FloatChat Feature 12 — Implementation Phases

## Scope and Confirmed Decisions

- Feature: System Monitoring (Feature 12)
- Mode: Additive changes only, no regressions to existing features
- Confirmed blocker decisions:
  - Add dedicated admin ingestion aggregate APIs:
    - `GET /api/v1/admin/ingestion/summary`
    - `GET /api/v1/admin/ingestion/trend`
  - Treat `monitoring/prometheus/alerts.yml` as documentation-only in v1
  - Digest window uses previous UTC calendar day
  - `SENTRY_DSN_BACKEND` is canonical; keep `SENTRY_DSN` as fallback alias with deprecation warning
  - Keep existing `/health` unchanged; add new `/api/v1/health`

---

## Phase 1 — Config Additions and Compatibility

### Goal
Add all monitoring configuration fields with safe defaults and Sentry backward compatibility.

### Files to Modify
- `backend/app/config.py` — add monitoring settings and DSN compatibility behavior

### Tasks
1. Add settings:
   - `LOG_SINK`
   - `LOG_RETENTION_DAYS`
   - `LOKI_URL`
   - `LOG_GROUP`
   - `LOG_STREAM`
   - `SENTRY_DSN_BACKEND`
   - `ENVIRONMENT`
   - `APP_VERSION`
   - `SENTRY_TRACES_SAMPLE_RATE`
2. Keep `SENTRY_DSN` as fallback alias for compatibility.
3. Emit a deprecation warning if legacy `SENTRY_DSN` is used without `SENTRY_DSN_BACKEND`.

### PRD Coverage
- FR-01, FR-02, FR-05

### Done When
- App starts with no new env vars.
- Legacy DSN still works.
- Deprecation warning appears only for legacy DSN path.

---

## Phase 2 — Monitoring Package Foundation

### Goal
Create reusable monitoring modules used by later instrumentation phases.

### Files to Create
- `backend/app/monitoring/__init__.py`
- `backend/app/monitoring/metrics.py`
- `backend/app/monitoring/sentry.py`

### Tasks
1. Define Prometheus custom metrics in `metrics.py`:
   - `floatchat_llm_call_duration_seconds`
   - `floatchat_db_query_duration_seconds`
   - `floatchat_redis_cache_hits_total`
   - `floatchat_redis_cache_misses_total`
   - `floatchat_celery_task_duration_seconds`
   - `floatchat_anomaly_scan_duration_seconds`
2. Implement `init_sentry()` in `sentry.py`.
3. Implement `set_sentry_request_tags(...)` helper in `sentry.py`.
4. Ensure helper failures are non-fatal.

### PRD Coverage
- FR-05, FR-06, FR-10, FR-11, FR-12, FR-13, FR-14

### Depends On
- Phase 1

### Done When
- Modules import cleanly.
- Missing optional infra does not crash startup.
- Metric names and labels exactly match PRD.

---

## Phase 3 — Logging Sink Routing

### Goal
Route existing structured logs to `stdout`, `loki`, or `cloudwatch` without changing default behavior.

### Files to Modify
- `backend/app/main.py` — extend logging setup for sink routing

### Tasks
1. Preserve current stdout JSON behavior as default.
2. Add optional Loki and CloudWatch handler routing.
3. Make sink setup best-effort and fall back to stdout on failure.
4. Wire retention settings where applicable.

### PRD Coverage
- FR-01, FR-02

### Depends On
- Phase 1

### Done When
- `LOG_SINK=stdout` preserves output structure.
- Invalid/absent sink dependencies do not crash app.
- Sink routing is additive only.

---

## Phase 4 — Backend Sentry Integration

### Goal
Initialize backend Sentry safely and add request-level tag enrichment.

### Files to Modify
- `backend/app/main.py` — call `init_sentry()` during startup
- `backend/app/api/v1/query.py` — set request tags where available
- `backend/app/api/v1/search.py` — set request tags where available
- `backend/app/api/v1/map.py` — set request tags where available

### Tasks
1. Use `SENTRY_DSN_BACKEND` as canonical source.
2. Use `SENTRY_DSN` fallback and emit deprecation warning.
3. Set only approved tags and avoid user content/PII.
4. Ensure Sentry failures are non-fatal.

### PRD Coverage
- FR-05, FR-06

### Depends On
- Phase 1, Phase 2

### Done When
- No DSN means Sentry fully disabled with clean startup.
- DSN present initializes correctly.
- Tags set only when values are available.

---

## Phase 5 — Structured Log Field Completion

### Goal
Fill missing NL query and ingestion completion fields additively.

### Files to Modify
- `backend/app/query/pipeline.py` — add canonical NL query completion log fields
- `backend/app/ingestion/tasks.py` — add canonical ingestion completion/failure log fields

### Tasks
1. Ensure NL query logs include:
   - `nl_query`
   - `generated_sql`
   - `provider`
   - `execution_time_ms`
   - `row_count`
2. Ensure ingestion completion/failure logs include:
   - `file_name`
   - `records_parsed`
   - `qc_flags_filtered`
   - `error_count`
3. Keep all changes additive (no behavior changes).

### PRD Coverage
- FR-03, FR-04

### Depends On
- Phase 1

### Done When
- Required fields appear in completion lifecycle logs.
- No pipeline/ingestion logic regressions.

---

## Phase 6 — Prometheus Instrumentation and Custom Metrics

### Goal
Expose `/metrics` and wire custom observations safely.

### Files to Modify
- `backend/app/main.py` — instrument app and expose metrics endpoint
- `backend/app/query/pipeline.py` — observe LLM latency
- `backend/app/anomaly/tasks.py` — set anomaly scan duration gauge
- `backend/app/celery_app.py` — add `task_prerun`/`task_postrun` handlers for task duration
- `backend/app/api/v1/map.py` — record Redis hit/miss for map caches
- `backend/app/chat/suggestions.py` — record Redis hit/miss for suggestions cache
- `backend/app/query/context.py` — record Redis hit/miss for context lookups
- `backend/requirements.txt` — add `prometheus-fastapi-instrumentator` and optional Loki package if needed

### Tasks
1. Install and initialize Prometheus instrumentation.
2. Add custom metrics observations with fail-safe wrappers.
3. Ensure endpoint behavior aligns with Feature 11 exclusion rules.

### PRD Coverage
- FR-09, FR-10, FR-11, FR-12, FR-13, FR-14

### Depends On
- Phase 2

### Done When
- `/metrics` returns valid Prometheus payload.
- All custom metric names/labels match PRD.
- Metric failures never crash requests/tasks.

---

## Phase 7 — Health Endpoint

### Goal
Add component-aware health endpoint at `/api/v1/health` while preserving existing `/health`.

### Files to Create
- `backend/app/api/v1/health.py`

### Files to Modify
- `backend/app/main.py` — register health router

### Tasks
1. Implement DB check (`SELECT 1`) with timeout.
2. Implement Redis ping check with timeout.
3. Implement Celery worker responsiveness check with timeout.
4. Return top-level status (`ok`/`degraded`/`error`) and HTTP mapping (200/503).
5. Keep existing `/health` untouched.

### PRD Coverage
- FR-22, FR-23

### Depends On
- Phase 1, Phase 6

### Done When
- `/api/v1/health` respects 3s overall budget.
- Status semantics and HTTP codes match PRD.
- Existing `/health` still works unchanged.

---

## Phase 8 — Ingestion Digest Task and Schedule

### Goal
Build and schedule daily ingestion digest for previous UTC calendar day.

### Files to Create
- `backend/app/monitoring/digest.py`

### Files to Modify
- `backend/app/celery_app.py` — add include entry and beat schedule (07:00 UTC)
- `backend/app/notifications/slack.py` — add digest rendering
- `backend/app/notifications/email.py` — add digest rendering
- `backend/app/notifications/sender.py` — additive update only if needed

### Tasks
1. Implement `build_digest_data(session, target_date)` using previous UTC day boundaries.
2. Implement `send_ingestion_digest_task`.
3. Dispatch via `notify("ingestion_daily_digest", digest_data)`.
4. Add beat schedule for 07:00 UTC.

### PRD Coverage
- FR-21

### Depends On
- Phase 1, Phase 2

### Done When
- Digest task computes expected UTC-day aggregates.
- Beat schedule entry exists and is non-conflicting.
- Digest notification payload includes required sections.

---

## Phase 9 — Admin Ingestion Health APIs

### Goal
Add dedicated ingestion aggregate endpoints (not derived from paged list).

### Files to Modify
- `backend/app/api/v1/admin.py`

### Tasks
1. Add `GET /api/v1/admin/ingestion/summary`.
2. Add `GET /api/v1/admin/ingestion/trend`.
3. Include:
   - daily summary metrics
   - source breakdown (`manual_upload` vs `gdac_sync`)
   - 7-day trend and failed-job-rate data

### PRD Coverage
- FR-17, FR-18, FR-19

### Depends On
- Phase 8

### Done When
- Both endpoints return stable aggregate schemas.
- UTC grouping is correct.
- API is suitable for dashboard rendering.

---

## Phase 10 — Ingestion Monitoring Frontend

### Goal
Extend existing ingestion admin page with Ingestion Health summary and trend charts.

### Files to Modify
- `frontend/app/admin/ingestion-jobs/page.tsx`
- `frontend/components/admin/IngestionJobsTable.tsx`
- `frontend/lib/adminQueries.ts`

### Tasks
1. Add API client types/calls for new summary/trend endpoints.
2. Render summary cards for ingestion health.
3. Render 7-day trend and failed rate charts using existing charting stack.
4. Keep existing ingestion jobs table behavior intact.

### PRD Coverage
- FR-17, FR-18, FR-19

### Depends On
- Phase 9

### Done When
- Ingestion page shows both real-time jobs and aggregate monitoring.
- Charts are responsive and consistent with project style.
- No new chart dependency is introduced.

---

## Phase 11 — Frontend Sentry

### Goal
Add Next.js Sentry configuration with graceful disable behavior.

### Files to Create
- `frontend/sentry.client.config.ts`
- `frontend/sentry.server.config.ts`
- `frontend/sentry.edge.config.ts`

### Files to Modify
- `frontend/next.config.mjs` — wrap config with `withSentryConfig`
- `frontend/package.json` — add `@sentry/nextjs`

### Tasks
1. Add Sentry config files for client/server/edge.
2. Ensure DSN-driven enablement with safe no-op when absent.
3. Preserve existing Next config behavior.

### PRD Coverage
- FR-07

### Depends On
- Phase 4

### Done When
- Frontend runs/builds with or without DSN.
- Sentry wiring is additive and non-breaking.

---

## Phase 12 — Grafana and Prometheus Artifacts

### Goal
Deliver dashboard and alert rule files.

### Files to Create
- `monitoring/grafana/floatchat_dashboard.json`
- `monitoring/prometheus/alerts.yml`

### Tasks
1. Build importable Grafana dashboard JSON against final metric names.
2. Add p95 latency alert rule for `POST /api/v1/query`.
3. Mark alerting receiver as documentation-only for v1 in runbook/docs context.

### PRD Coverage
- FR-15, FR-16

### Depends On
- Phase 6

### Done When
- Dashboard imports successfully.
- Alert rule validates syntactically.
- Documentation-only receiver caveat is explicit.

---

## Phase 13 — Tests and Documentation Finalization (Mandatory Final Phase)

### Goal
Complete validation and final documentation closure.

### Files to Create
- `backend/tests/test_health_endpoint.py`
- `backend/tests/test_sentry_init.py`
- `backend/tests/test_metrics.py`
- `backend/tests/test_ingestion_digest.py`

### Files to Modify
- `instructions/features.md` — update Feature 12 status/progress
- `README.md` — add monitoring setup and operations notes
- Additional docs files for alert runbook and deployment guidance as required

### Tasks
1. Add and run all new Feature 12 tests.
2. Run relevant existing suites to ensure no regressions.
3. Update docs with:
   - monitoring setup
   - `/metrics` network protection requirement
   - `/api/v1/health` usage
   - alert runbook
   - explicit note that `alerts.yml` is documentation-only until receiver exists

### PRD Coverage
- FR-08, FR-20, FR-24 and mandatory documentation completion rule

### Depends On
- All prior phases

### Done When
- New tests pass.
- Existing tests in touched areas pass.
- Documentation updates are complete and reviewed.

---

## Execution Rule

Implement one phase at a time, summarize completion, and wait for explicit confirmation before moving to the next phase.
