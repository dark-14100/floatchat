import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN || process.env.SENTRY_DSN_FRONTEND;
const enabled = Boolean(dsn);

const environment =
  process.env.NEXT_PUBLIC_ENVIRONMENT ||
  process.env.ENVIRONMENT ||
  process.env.NODE_ENV ||
  "development";

const release =
  process.env.NEXT_PUBLIC_APP_VERSION ||
  process.env.APP_VERSION ||
  "unknown";

Sentry.init({
  dsn,
  enabled,
  environment,
  release,
  tracesSampleRate: 0.1,
  // Never attach request payloads or response bodies to avoid accidental PII capture.
  sendDefaultPii: false,
  beforeSend(event) {
    if (!enabled) {
      return null;
    }
    if (event.request) {
      delete event.request.data;
      delete event.request.cookies;
      delete event.request.headers;
    }
    return event;
  },
});
