# FloatChat — Feature 12: System Monitoring
## Product Requirements Document (PRD)

**Feature Name:** System Monitoring
**Version:** 1.0
**Status:** ⏳ Ready for Development
**Depends On:** Feature 10 (Dataset Management — notification module and admin panel both extended here), Feature 11 (API Layer — `/metrics` and `/api/v1/health` must be excluded from API key rate limiting; Feature 11's middleware must exist first), GDAC Auto-Sync (GDAC sync job metrics appear in the ingestion monitoring dashboard automatically via the `source` column)
**Blocks:** Nothing — Feature 12 is the final feature in the build sequence

---

## 1. Purpose & Background

### 1.1 What Problem Does This Solve?
FloatChat has no operational visibility in production. When something breaks — a slow NL query, a failed ingestion job, an unhandled exception, a Redis connection drop — there is currently no mechanism to detect it, alert on it, or diagnose it after the fact. Structlog is already emitting structured JSON logs throughout the codebase, but those logs go nowhere beyond stdout. There are no metrics, no error tracking, no uptime monitoring, and no alert runbook.

Feature 12 solves this by routing existing logs to a configurable destination, adding Sentry for error tracking on both the backend and frontend, adding Prometheus metrics with a Grafana dashboard, extending Feature 10's admin panel with ingestion aggregate views, and building a health check endpoint with external uptime monitoring. By the end of this feature, a production FloatChat instance is fully observable: errors are captured, performance is measured, ingestion health is visible, and on-call engineers have a runbook for every alert.

### 1.2 What Already Exists
This feature builds on infrastructure already in place — it does not start from scratch:

- `structlog` is configured throughout the backend and already emits structured JSON logs. This feature routes those logs; it does not change how they are generated (only fills any missing fields).
- Feature 10's notification module (`app/notifications/slack.py`, `app/notifications/email.py`, `app/notifications/sender.py`) is already built and handles Slack and email delivery. Feature 12's alerting reuses this module entirely — no new notification infrastructure.
- Feature 10's admin panel already has the ingestion jobs table and per-job tracking. Feature 12 adds aggregate views and trend charts on top of this existing data — it does not rebuild the table.
- Feature 15's anomaly detection nightly task already produces structlog output. The anomaly scan duration metric in Feature 12 instruments this existing task.
- Feature 11's rate limiting middleware is already in place. `GET /api/v1/health` and `GET /metrics` are explicitly excluded from rate limiting in Feature 11.

### 1.3 What This Feature Is
Five operational reliability components added to the existing system:

1. **Logging Pipeline** — routing existing structlog output to a configurable destination (stdout in dev, Loki or CloudWatch in production), and filling any missing structured log fields
2. **Error Tracking** — Sentry on both the FastAPI backend and the Next.js frontend, with custom tags and Slack alerting on new error types and rate spikes
3. **Performance Metrics** — Prometheus instrumentation with custom metrics for LLM latency, DB query time, Redis hit rate, and Celery task duration; Grafana dashboard; Slack alert on p95 latency breach
4. **Ingestion Monitoring Dashboard** — aggregate views and trend charts added to the Feature 10 admin panel; daily digest confirmation
5. **Uptime Monitoring** — a health check endpoint with component checks (DB, Redis, Celery) and external uptime monitoring with Slack alerting on consecutive failures

### 1.4 What This Feature Is Not
- It does not change how structlog generates log entries — only where they go and fills any missing fields
- It does not build a new admin UI — the ingestion monitoring dashboard is an extension of Feature 10's existing admin panel
- It does not implement OpenTelemetry distributed tracing — this is listed as optional and lower priority; it is out of scope for this feature
- It does not implement per-user analytics or business intelligence — metrics are operational (latency, error rate, availability) not product analytics
- It does not build a custom alerting engine — Slack webhook reuses Feature 10's notification module; PagerDuty is out of scope for v1

---

## 2. Goals & Success Criteria

### 2.1 Goals
- Make production FloatChat fully observable: errors captured, performance measured, availability monitored
- Ensure on-call engineers can detect, diagnose, and remediate incidents without SSH-ing into production servers
- Surface ingestion health in the admin panel so admins know the state of data acquisition at a glance
- Keep the monitoring stack lightweight and self-contained — no external services required beyond Sentry (which is optional in dev)

### 2.2 Success Criteria

| Criterion | Target |
|---|---|
| Unhandled backend exception → Sentry | < 5 seconds |
| Unhandled frontend React error → Sentry | < 5 seconds |
| p95 latency breach on `/api/v1/query` → Slack alert | < 2 minutes |
| Health check endpoint response time | < 500ms including DB, Redis, Celery checks |
| Ingestion failure → Slack notification | Already triggered by Feature 10 — confirmed working by this feature |
| All NL query log fields present | 100% of query log entries include `nl_query`, `generated_sql`, `provider`, `execution_time_ms`, `row_count` |
| All ingestion log fields present | 100% of ingestion task log entries include `file_name`, `records_parsed`, `qc_flags_filtered`, `error_count` |
| `/metrics` not accessible via public internet | Confirmed via network configuration in deployment docs |
| Sentry disabled gracefully when DSN absent | No errors, no warnings in dev when `SENTRY_DSN_BACKEND` / `SENTRY_DSN_FRONTEND` not set |

---

## 3. User Stories

### 3.1 On-Call Engineer
- **US-01:** As an on-call engineer, I want to receive a Slack notification when a new unhandled exception type occurs in production, so I can investigate before it affects multiple users.
- **US-02:** As an on-call engineer, I want a Grafana dashboard showing request latency p50/p95/p99 per endpoint, so I can identify which endpoints are slow without reading raw logs.
- **US-03:** As an on-call engineer, I want a Slack alert when p95 latency on the NL query endpoint exceeds 5 seconds, so I know immediately when the core feature is degraded.
- **US-04:** As an on-call engineer, I want an alert runbook document that tells me exactly what to do for every alert that can fire, so I can resolve incidents under pressure without guessing.
- **US-05:** As an on-call engineer, I want `GET /api/v1/health` to tell me whether the database, Redis, and Celery are all healthy, so I can diagnose infrastructure failures quickly.

### 3.2 Admin
- **US-06:** As an admin, I want the ingestion monitoring section of the admin panel to show me a daily summary of profiles ingested, new floats discovered, failed files, and ingestion duration, so I know the state of data acquisition without querying the database.
- **US-07:** As an admin, I want a 7-day trend chart of ingestion volume in the admin panel, so I can spot trends and anomalies in data acquisition.
- **US-08:** As an admin, I want a Slack notification when any ingestion job fails, so I know immediately when data acquisition is broken.
- **US-09:** As an admin, I want a daily digest Slack message summarising ingestion activity, so I have a regular confirmation that data acquisition is running normally.

### 3.3 Developer
- **US-10:** As a developer, I want Sentry error tracking to be disabled gracefully when `SENTRY_DSN_BACKEND` and `SENTRY_DSN_FRONTEND` are not set in the environment, so local development works without a Sentry account.
- **US-11:** As a developer, I want all NL query log entries to include the full set of structured fields (`nl_query`, `generated_sql`, `provider`, `execution_time_ms`, `row_count`), so log analysis tools can query them reliably.

---

## 4. Functional Requirements

### 4.1 Logging Pipeline

**FR-01 — Log Destination Configuration**
Add a `LOG_SINK` environment variable to `config.py` Settings class:
- `stdout` (default) — existing behaviour; logs go to stdout as structured JSON
- `loki` — logs are forwarded to a Loki instance at `LOKI_URL` (new config setting)
- `cloudwatch` — logs are forwarded to AWS CloudWatch using `LOG_GROUP` and `LOG_STREAM` config settings

The `structlog` configuration in `main.py` (or wherever it is initialised) is updated to route to the configured sink. When `LOG_SINK = stdout`, behaviour is unchanged from today. Loki and CloudWatch sinks use the appropriate client libraries and must fail gracefully — a logging sink failure must never crash the application.

**FR-02 — Log Retention Policy**
Add a `LOG_RETENTION_DAYS` environment variable (integer, default 30). This value is passed to the configured log sink as the retention policy. For `stdout`, this setting has no effect. For Loki and CloudWatch, the retention policy is applied at sink initialisation time.

**FR-03 — NL Query Log Field Audit**
Audit the NL query pipeline logging in `backend/app/query/pipeline.py` and related files. Every NL query execution must produce a structured log entry containing all of the following fields:
- `nl_query` — the raw natural language input from the user
- `generated_sql` — the SQL produced by the LLM
- `provider` — the LLM provider used (e.g. `openai`, `anthropic`)
- `execution_time_ms` — total time from NL input to query result in milliseconds
- `row_count` — number of rows returned by the executed SQL

If any field is missing from existing log entries, add it. This is an additive change to the logging calls — no pipeline logic changes.

**FR-04 — Ingestion Log Field Audit**
Audit the ingestion task logging in `backend/app/ingestion/tasks.py` and related files. Every ingestion job completion (success or failure) must produce a structured log entry containing all of the following fields:
- `file_name` — the name of the source file being ingested
- `records_parsed` — total records parsed from the file
- `qc_flags_filtered` — number of records excluded due to QC flags
- `error_count` — number of errors encountered during ingestion

If any field is missing from existing log entries, add it. This is an additive change to the logging calls — no ingestion logic changes.

### 4.2 Error Tracking (Sentry)

**FR-05 — Sentry Backend Configuration**
Install `sentry-sdk[fastapi]` and initialise Sentry in the FastAPI application startup. Configuration:
- DSN sourced from `SENTRY_DSN_BACKEND` env var
- When `SENTRY_DSN_BACKEND` is absent or empty, Sentry is completely disabled — no errors, no warnings, no degraded behaviour
- `environment` tag set from a new `ENVIRONMENT` config setting (values: `development`, `staging`, `production`; default `development`)
- `release` tag set from a new `APP_VERSION` config setting (optional string; default `unknown`)
- `traces_sample_rate` configurable via `SENTRY_TRACES_SAMPLE_RATE` env var (float 0.0–1.0; default `0.1` in production, `0.0` in development)
- Sentry captures: all unhandled exceptions, slow requests (threshold configurable), DB query errors

**FR-06 — Sentry Custom Tags**
Every Sentry event must be enriched with the following custom tags where the data is available in the request context:
- `query_type` — the type of query being performed (e.g. `nl_query`, `dataset_search`, `map_query`)
- `dataset_id` — the UUID of the dataset involved in the request, if applicable
- `float_id` — the WMO float ID, if applicable
- `provider` — the LLM provider used, if applicable
- `user_id` — the authenticated user's UUID (already in structlog context; confirm it can be added to Sentry scope)
- `api_key_request` — boolean, whether the request was authenticated via API key (from Feature 11 context)

Tags are set via Sentry's scope mechanism at the start of each request. Tags that are not applicable to a given request are simply absent — no null/empty tag values.

**FR-07 — Sentry Frontend Configuration**
Install `@sentry/nextjs` and configure it for the Next.js frontend. Configuration:
- DSN sourced from `NEXT_PUBLIC_SENTRY_DSN` environment variable
- When absent or empty, Sentry frontend is completely disabled
- `environment` tag matches the backend `ENVIRONMENT` setting
- `release` tag matches `APP_VERSION`
- Captures: all unhandled React errors, failed API calls (non-2xx responses), and Next.js routing errors
- Does not capture: user input content (PII protection), API response bodies

**FR-08 — Sentry Alert Rules**
Two alert rules configured in the Sentry project (documented in the alert runbook, configured manually in Sentry UI):
- New error type (first occurrence of an exception type not seen before) → immediate Slack notification via Feature 10's notification module
- Error rate spike (error rate exceeds 10x the 5-minute baseline) → immediate Slack notification

These alert rules are configured in Sentry's UI directly — they are not programmatic. The alert runbook must document how to configure and verify them.

### 4.3 Performance Metrics

**FR-09 — Prometheus Auto-Instrumentation**
Install `prometheus-fastapi-instrumentator` and instrument the FastAPI application. Configuration:
- Auto-instruments all FastAPI endpoints: request count, request latency (histogram), request size, response size per endpoint and method
- Exposes `GET /metrics` endpoint returning Prometheus text format
- `GET /metrics` requires no authentication (it is excluded from Feature 11's rate limiter, as confirmed in Feature 11)
- `GET /metrics` must not be accessible via the public internet in production — deployment documentation must note that this endpoint should be bound to an internal network interface or protected by a network rule
- Metrics endpoint is excluded from its own instrumentation (does not appear in request count metrics)

**FR-10 — Custom Metrics: LLM Call Latency**
Add a Prometheus histogram metric `floatchat_llm_call_duration_seconds` with labels `provider` (e.g. `openai`, `anthropic`) and `model` (the specific model name). This metric is recorded in the NL query pipeline wherever LLM API calls are made. The observation is the wall-clock time of the LLM call only — not the full query pipeline time.

**FR-11 — Custom Metrics: DB Query Time**
Add a Prometheus histogram metric `floatchat_db_query_duration_seconds` with label `endpoint` (the FastAPI route path, e.g. `/api/v1/query`). Recorded for every database query executed during a request. SQLAlchemy event listeners are the appropriate instrumentation point — the agent must confirm this is the correct approach after reading the existing SQLAlchemy configuration.

**FR-12 — Custom Metrics: Redis Cache Hit Rate**
Add two Prometheus counter metrics: `floatchat_redis_cache_hits_total` and `floatchat_redis_cache_misses_total`, both with label `operation` (the cache operation type, e.g. `query_embedding`, `session`). These are incremented wherever Redis cache lookups currently occur in the codebase. The agent must identify all Redis cache lookup points during gap analysis.

**FR-13 — Custom Metrics: Celery Task Duration**
Add a Prometheus histogram metric `floatchat_celery_task_duration_seconds` with label `task_name` (the fully qualified Celery task name, e.g. `app.ingestion.tasks.ingest_file_task`). Recorded using Celery task signals (`task_prerun` and `task_postrun`) — not by modifying individual task functions.

**FR-14 — Custom Metrics: Anomaly Scan Duration**
Add a Prometheus gauge metric `floatchat_anomaly_scan_duration_seconds`. Updated at the end of each Feature 15 anomaly detection nightly run. This is an additive change to `backend/app/anomaly/tasks.py` — the metric is set after the scan completes, no scan logic changes.

**FR-15 — Grafana Dashboard**
A Grafana dashboard configuration file (JSON format, importable into Grafana) must be created at `monitoring/grafana/floatchat_dashboard.json`. The dashboard must include the following panels:
- Request latency p50, p95, p99 per endpoint (from `prometheus-fastapi-instrumentator` metrics)
- LLM call latency p50, p95, p99 per provider (from `floatchat_llm_call_duration_seconds`)
- DB query time p50, p95 per endpoint (from `floatchat_db_query_duration_seconds`)
- Redis cache hit rate as a percentage over time (from hit/miss counters)
- Active and queued Celery tasks (from Celery metrics or `flower` if available)
- Ingestion job success rate over time (from `ingestion_jobs` table via a Prometheus exporter or direct DB metric)
- Anomaly scan duration over time (from `floatchat_anomaly_scan_duration_seconds`)

**FR-16 — Prometheus Latency Alert**
A Prometheus alerting rule must be created at `monitoring/prometheus/alerts.yml`. One alert rule: when p95 latency on `POST /api/v1/query` exceeds 5 seconds for more than 2 consecutive minutes, fire an alert. The alert fires to Alertmanager, which calls Feature 10's notification module to send a Slack message. The alert message must include the current p95 value and a link to the Grafana dashboard.

### 4.4 Ingestion Monitoring Dashboard

**FR-17 — Daily Summary Section**
Add a new "Ingestion Health" section to the Feature 10 admin panel (exact placement — new tab, new page, or new section on the existing ingestion jobs page — to be determined during gap analysis based on the existing admin panel structure). This section shows:
- Total profiles ingested today
- New floats discovered today (floats with a `created_at` date of today)
- Failed ingestion jobs today (count and list)
- Average ingestion duration today (mean duration of completed jobs)
- Source breakdown: how many jobs came from `manual_upload` vs `gdac_sync` (using the `source` column from Feature 10)

All values are computed from the existing `ingestion_jobs` and `profiles` tables — no new tables or columns required.

**FR-18 — 7-Day Trend Chart**
A line chart in the "Ingestion Health" section showing ingestion volume over the last 7 days: profiles ingested per day, failed jobs per day. Uses the existing `ingestion_jobs` data. The chart is rendered with the same charting library already in use in the admin frontend (confirm during gap analysis).

**FR-19 — Failed Job Rate Over Time**
A secondary chart showing the failed job rate (failed / total) as a percentage per day over the last 7 days. Calculated from `ingestion_jobs` data.

**FR-20 — Ingestion Failure Slack Alert Confirmation**
Feature 10's notification module already sends a Slack alert on ingestion job failure. This requirement is to confirm that the existing alert is working correctly in the production environment and is documented in the alert runbook. If the alert is not working, fix it as part of this feature. No new notification infrastructure is needed.

**FR-21 — Daily Ingestion Digest**
Add a new Celery beat task `send_ingestion_digest_task` scheduled at 07:00 UTC daily. The task queries `ingestion_jobs` and `profiles` for the previous day's activity and sends a Slack message (via Feature 10's `notify()` function) with: total profiles ingested, new floats discovered, failed jobs count (with names if any failed), and GDAC sync status (completed / failed / not run). This is a new notification event type — `ingestion_daily_digest` — that must be added to the notification module if the module has a fixed event type list.

### 4.5 Health Check and Uptime Monitoring

**FR-22 — `GET /api/v1/health` Endpoint**
Create a new endpoint `GET /api/v1/health` in a new `health.py` router. No authentication required. The endpoint performs the following component checks and returns them individually:

- **`db`**: Execute a minimal query against the database (e.g. `SELECT 1`). Status `ok` if it succeeds within 1 second, `error` with message if it fails or times out.
- **`redis`**: Execute a Redis `PING` command. Status `ok` if it responds within 500ms, `error` with message otherwise.
- **`celery`**: Check whether at least one Celery worker is registered and responsive. Status `ok` if a worker responds to an inspect ping within 2 seconds, `degraded` if no workers respond (tasks will queue but not run), `error` if the Celery broker itself is unreachable.

Response body: `{ "status": "ok" | "degraded" | "error", "db": "ok" | "error", "redis": "ok" | "error", "celery": "ok" | "degraded" | "error", "timestamp": "<ISO8601>", "version": "<APP_VERSION>" }`

Top-level `status` is `ok` only if all components are `ok`. `degraded` if any component is `degraded` but none are `error`. `error` if any component is `error`.

HTTP status code: 200 if top-level `status` is `ok` or `degraded`; 503 if top-level `status` is `error`. This allows uptime monitors to detect failures via HTTP status code without parsing the body.

The endpoint must complete within 3 seconds total — individual component checks have their own sub-timeouts as listed above.

**FR-23 — Health Endpoint Exclusions**
`GET /api/v1/health` is explicitly excluded from:
- Feature 11's API key rate limiting (already handled in Feature 11)
- Prometheus instrumentation (does not appear in latency metrics — health check traffic would skew p95 calculations)
- Sentry request tracing (health checks are high-frequency and would consume Sentry quota)

**FR-24 — External Uptime Monitoring**
The deployment documentation must include instructions for configuring an external uptime monitor (UptimeRobot or Healthchecks.io) to:
- Ping `GET /api/v1/health` every 60 seconds
- Alert via Slack if the endpoint returns non-200 for 3 consecutive checks (3 minutes of downtime)
- The uptime monitor configuration is external to the codebase — the documentation covers what to configure, not automated setup

---

## 5. Non-Functional Requirements

### 5.1 Operational Safety
- A logging sink failure must never crash the application. All log routing code is wrapped in try/except.
- Sentry initialisation failure must never crash the application. Sentry is optional infrastructure.
- Prometheus metric recording failures must never crash the application. Metric updates are wrapped in try/except.
- The health check endpoint must never take more than 3 seconds to respond, regardless of the state of downstream components. Individual component checks use sub-timeouts.

### 5.2 Performance Impact
- Prometheus metric recording adds negligible overhead — histogram observations are in-memory operations
- `last_used_at` updates in Feature 11 are already non-blocking; this feature's metric recording follows the same principle for any operation that could block
- The daily digest Celery task runs at 07:00 UTC — outside of peak research hours

### 5.3 Privacy
- Sentry must never capture user input content (NL query text, uploaded file content, chat messages) — only exception types, stack traces, and the custom tags defined in FR-06
- Prometheus metrics contain no user-identifiable information — only aggregate counts and histograms per endpoint
- Log entries may contain `user_id` (UUID) but must not contain `email`, `name`, or any other PII beyond the opaque identifier

### 5.4 Developer Experience
- All monitoring infrastructure is disabled by default in development when environment variables are absent
- A developer running FloatChat locally with no Sentry DSN, no Loki URL, and no external Prometheus must have an identical experience to today — no errors, no missing functionality, no noisy warnings

---

## 6. File Structure

```
floatchat/
├── monitoring/
│   ├── grafana/
│   │   └── floatchat_dashboard.json           # Grafana dashboard (importable JSON)
│   └── prometheus/
│       └── alerts.yml                         # Prometheus alerting rules
└── backend/
    ├── app/
    │   ├── api/v1/
    │   │   └── health.py                      # New: GET /api/v1/health endpoint
    │   ├── main.py                            # Additive: Sentry init, Prometheus instrumentation, health router
    │   ├── config.py                          # Additive: LOG_SINK, SENTRY_DSN_BACKEND, ENVIRONMENT, APP_VERSION, SENTRY_TRACES_SAMPLE_RATE, LOG_RETENTION_DAYS, LOKI_URL, LOG_GROUP, LOG_STREAM
    │   ├── query/pipeline.py                  # Additive: missing log fields (FR-03), LLM latency metric (FR-10)
    │   ├── ingestion/tasks.py                 # Additive: missing log fields (FR-04), Celery task metric signal (FR-13)
    │   ├── anomaly/tasks.py                   # Additive: anomaly scan duration metric (FR-14)
    │   ├── notifications/sender.py            # Additive: ingestion_daily_digest event type if needed (FR-21)
    │   ├── celery_app.py                      # Additive: send_ingestion_digest_task beat schedule
    │   └── monitoring/
    │       ├── __init__.py
    │       ├── metrics.py                     # New: all custom Prometheus metric definitions
    │       ├── sentry.py                      # New: Sentry initialisation and scope helpers
    │       └── digest.py                      # New: daily ingestion digest task logic
    └── tests/
        ├── test_health_endpoint.py
        ├── test_sentry_init.py
        ├── test_metrics.py
        └── test_ingestion_digest.py

frontend/
    ├── sentry.client.config.ts                # New: Sentry Next.js client config
    ├── sentry.server.config.ts                # New: Sentry Next.js server config
    ├── sentry.edge.config.ts                  # New: Sentry Next.js edge config
    └── app/admin/
        └── ingestion/
            └── page.tsx                       # Additive: Ingestion Health section (FR-17, FR-18, FR-19)
```

---

## 7. Dependencies

| Dependency | Source | Status |
|---|---|---|
| `app/notifications/slack.py` | Feature 10 | ✅ Built |
| `app/notifications/sender.py` (notify() function) | Feature 10 | ✅ Built |
| Feature 10 admin panel | Feature 10 | ✅ Built |
| `ingestion_jobs` table with `source` column | Feature 10 migration 008 | ✅ Built |
| Feature 11 rate limiting middleware | Feature 11 | ✅ Built |
| Feature 15 anomaly task (`app/anomaly/tasks.py`) | Feature 15 | ✅ Built |
| `structlog` | Existing | ✅ Installed |
| Celery + Redis | Feature 1 | ✅ Running |
| `prometheus-fastapi-instrumentator` | New pip dependency | ⏳ To install |
| `sentry-sdk[fastapi]` | New pip dependency | ⏳ To install |
| `@sentry/nextjs` | New npm dependency | ⏳ To install |
| `boto3` (for CloudWatch sink) | Optional pip dependency | ⏳ Only if `LOG_SINK=cloudwatch` |
| `python-logging-loki` (for Loki sink) | Optional pip dependency | ⏳ Only if `LOG_SINK=loki` |

---

## 8. Open Questions

| # | Question | Owner | Due |
|---|---|---|---|
| OQ1 | Where exactly is structlog currently initialised and configured? The agent must find the exact initialisation point before adding log sink routing — if structlog is configured in `main.py`, the routing is added there; if it is in a separate `logging.py` module, it goes there. | Engineering | Before FR-01 implementation |
| OQ2 | Does the existing structlog configuration use `structlog.configure()` with a processor chain, or does it use a different setup? The Loki and CloudWatch sinks need to be added as processors or output handlers depending on the configuration style. | Engineering | Before FR-01 implementation |
| OQ3 | What charting library is currently in use in the admin frontend for any existing charts or data visualisations? The ingestion monitoring trend charts (FR-18, FR-19) must use the same library to maintain visual consistency. If no charts exist yet, a decision is needed on which library to add. | Frontend | Before FR-18 implementation |
| OQ4 | Does Feature 10's admin panel currently have a separate page for ingestion jobs (`/admin/ingestion-jobs`) or is it a tab within the main admin dashboard? The placement of the new "Ingestion Health" section (FR-17) depends on this existing structure. | Frontend | Before FR-17 implementation |
| OQ5 | Does Feature 10's notification module (`sender.py`) have a fixed whitelist of supported event types, or does it accept arbitrary event strings? If fixed, `ingestion_daily_digest` must be explicitly added to the list. | Engineering | Before FR-21 implementation |
| OQ6 | Are there any existing Redis cache lookup points in the codebase that should be instrumented for the cache hit/miss counters (FR-12)? The agent must identify all Redis cache operations during codebase reading. If there are no cache lookups (Redis is used only for Celery and rate limiting), FR-12 may not be applicable and should be flagged. | Engineering | Before FR-12 implementation |
| OQ7 | The Celery task duration metric (FR-13) uses Celery task signals (`task_prerun` and `task_postrun`). Are these signals already used anywhere in the codebase? If so, the new signal handlers must be registered additively without breaking existing signal handlers. | Engineering | Before FR-13 implementation |
| OQ8 | For the `GET /api/v1/health` Celery check — what is the most reliable way to check Celery worker availability given the existing Celery configuration? Options include `celery.control.inspect().ping()`, checking the Celery broker directly, or checking the Redis queue length. The correct approach depends on how Celery is configured. | Engineering | Before FR-22 implementation |
| OQ9 | Should the Grafana dashboard JSON (FR-15) be a static file committed to the repository, or should it be generated programmatically? A static committed JSON file is simpler and sufficient for v1 — but if the Prometheus metric names change, the dashboard needs to be manually updated. Confirm the preferred approach. | Engineering | Before FR-15 implementation |
| OQ10 | The ingestion failure Slack alert (FR-20) is described as already implemented in Feature 10. Before this feature adds the daily digest, the existing alert must be verified working. What is the mechanism to verify this in a test environment — is there a way to trigger a test ingestion failure to confirm the alert fires? | Engineering | Before FR-20 sign-off |
