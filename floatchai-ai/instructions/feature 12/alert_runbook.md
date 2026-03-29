# FloatChat Feature 12 Alert Runbook

## Scope
This runbook covers Feature 12 monitoring signals:
- `GET /api/v1/health` component status
- Prometheus metrics and alert rule artifacts
- Ingestion daily digest notifications
- Sentry error monitoring

## v1 Caveat
`monitoring/prometheus/alerts.yml` is documentation-only in v1.
Until an Alertmanager receiver route is provisioned, alerts are not auto-routed.

## Alert Inventory

### 1. Query Latency p95 Breach
- Signal: p95 latency on `POST /api/v1/query` exceeds threshold in alert rule.
- Source: Prometheus rule in `monitoring/prometheus/alerts.yml`.
- Initial checks:
  1. Confirm backend process health via `GET /api/v1/health`.
  2. Inspect `/metrics` for request latency histogram increase.
  3. Check Redis connectivity and cache hit/miss rates.
  4. Check DB saturation and slow query logs.
- Common remediation:
  1. Reduce expensive query load and retry.
  2. Scale API/Celery workers if saturation is confirmed.
  3. Investigate recent deploy changes and roll back if regression is clear.

### 2. Ingestion Failure Spike
- Signal: failed ingestion count or failed-rate trend increases.
- Source: admin ingestion trend endpoint and daily digest payload.
- Initial checks:
  1. Open admin ingestion monitoring page.
  2. Filter failed jobs by source (`manual_upload` vs `gdac_sync`).
  3. Inspect latest failed job errors in backend logs.
- Common remediation:
  1. Retry failed jobs from admin endpoint.
  2. Validate source data integrity and parsing compatibility.
  3. For GDAC failures, verify mirror availability and timeout behavior.

### 3. Health Endpoint Degraded/Error
- Signal: `GET /api/v1/health` returns `degraded` or `error`.
- Component fields: `db`, `redis`, `celery`.
- Initial checks:
  1. Identify failing component from payload.
  2. Verify service connectivity from backend runtime.
  3. Review recent infrastructure restarts or network changes.
- Common remediation:
  1. Restart unhealthy dependency (if self-hosted).
  2. Recycle backend workers after dependency recovery.
  3. Confirm health endpoint returns `ok` for two consecutive checks.

### 4. Sentry Error Burst
- Signal: elevated unhandled exceptions in Sentry project.
- Initial checks:
  1. Confirm DSN is set for environment where errors are reported.
  2. Group by release/environment to isolate blast radius.
  3. Identify top failing endpoint and stack trace.
- Common remediation:
  1. Apply hotfix for deterministic exception path.
  2. Temporarily reduce risky traffic if needed.
  3. Validate with smoke test and monitor event decay.

## Escalation
- Severity high: health endpoint `error`, sustained query latency breach, or widespread ingestion failures.
- Escalate to backend + infra owners with:
  - incident start time (UTC)
  - impacted components/endpoints
  - top error traces or metric snapshots
  - mitigation performed

## Post-Incident Checklist
1. Capture root cause and timeline.
2. Add or refine alert threshold if noisy/missed.
3. Add regression test when bug is application-level.
4. Update this runbook with any new learned remediation step.
