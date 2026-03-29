# FloatChat Feature 12 Monitoring Deployment Guide

## Goal
Deploy Feature 12 monitoring components safely across environments.

## Components
- Backend metrics endpoint: `GET /metrics`
- Backend health endpoint: `GET /api/v1/health`
- Backend Sentry SDK initialization
- Frontend Sentry (`@sentry/nextjs`)
- Grafana dashboard artifact: `monitoring/grafana/floatchat_dashboard.json`
- Prometheus alert rule artifact: `monitoring/prometheus/alerts.yml`

## Environment Configuration

### Backend
Set these variables as needed:
- `SENTRY_DSN_BACKEND` (preferred)
- `SENTRY_DSN` (legacy fallback)
- `ENVIRONMENT`
- `APP_VERSION`
- `SENTRY_TRACES_SAMPLE_RATE`

### Frontend
Set:
- `SENTRY_DSN_FRONTEND`

If DSN values are absent, Sentry remains disabled without startup failure.

## Network and Security Requirements
1. Do not expose `/metrics` publicly.
2. Restrict `/metrics` to internal network paths (cluster/private subnet/VPN).
3. Keep `/api/v1/health` externally reachable only if uptime monitor requires it.
4. Ensure no sensitive payload data is attached to Sentry tags.

## Prometheus Setup
1. Configure scrape target for backend `/metrics` endpoint.
2. Validate target status is `UP`.
3. Import alert rules from `monitoring/prometheus/alerts.yml`.
4. Confirm expression compatibility with your Prometheus version.

## Grafana Setup
1. Import `monitoring/grafana/floatchat_dashboard.json`.
2. Bind dashboard to Prometheus data source.
3. Validate key panels:
   - endpoint latency (p50/p95/p99)
   - LLM provider latency
   - DB timing
   - Redis hit/miss trends
   - Celery task duration
   - ingestion success/failure rates

## Alerting in v1
- `alerts.yml` is provided as artifact-only in v1.
- Alertmanager receiver routing must be provisioned separately.
- Until receiver setup is complete, rely on:
  - health checks
  - Sentry dashboard notifications
  - ingestion daily digest notifications

## Validation Checklist
1. `GET /api/v1/health` returns `ok` under healthy dependencies.
2. `/metrics` is scrapeable from Prometheus and blocked from public ingress.
3. Grafana dashboard imports successfully and panels populate.
4. Sentry events appear when DSN is configured and remain silent when DSN is absent.
5. Daily ingestion digest triggers on schedule (07:00 UTC) and payload fields are populated.

## Rollback Notes
- Disable Sentry by unsetting DSN variables.
- Remove Prometheus scrape target and alert rule includes if needed.
- Dashboard import is non-destructive and can be removed safely.
- Feature 12 changes are additive and should not require API rollback for core app behavior.
