"""
FloatChat Backend API

FastAPI application entry point for the Data Ingestion Pipeline.
"""

import logging
import socket
import sys
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

import structlog
from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.monitoring.metrics import reset_current_endpoint, set_current_endpoint
from app.monitoring.sentry import init_sentry
from app.rate_limiter import limiter
from app.storage.s3 import get_s3_client

try:
    from prometheus_fastapi_instrumentator import Instrumentator
except Exception:
    Instrumentator = None  # type: ignore[assignment]


class CloudWatchLogsHandler(logging.Handler):
    """Best-effort CloudWatch Logs handler for structured log messages."""

    def __init__(self, *, log_group: str, log_stream: str, region_name: str | None = None) -> None:
        super().__init__()
        import boto3

        self.client = boto3.client("logs", region_name=region_name)
        self.log_group = log_group
        self.log_stream = log_stream
        self._sequence_token: str | None = None
        self._ensure_stream()

    def _ensure_stream(self) -> None:
        try:
            self.client.create_log_group(logGroupName=self.log_group)
        except Exception:
            pass

        try:
            self.client.create_log_stream(
                logGroupName=self.log_group,
                logStreamName=self.log_stream,
            )
        except Exception:
            pass

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            kwargs: dict[str, Any] = {
                "logGroupName": self.log_group,
                "logStreamName": self.log_stream,
                "logEvents": [
                    {
                        "timestamp": int(record.created * 1000),
                        "message": msg,
                    }
                ],
            }
            if self._sequence_token:
                kwargs["sequenceToken"] = self._sequence_token

            response = self.client.put_log_events(**kwargs)
            self._sequence_token = response.get("nextSequenceToken")
        except Exception:
            self.handleError(record)


def _build_logging_handler(formatter: logging.Formatter) -> logging.Handler:
    """Build sink-specific log handler; fallback to stdout on any sink failure."""
    sink = (settings.LOG_SINK or "stdout").strip().lower()

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)

    if sink == "stdout":
        return stdout_handler

    if sink == "loki":
        if not settings.LOKI_URL:
            stdout_handler.handle(
                logging.makeLogRecord(
                    {
                        "levelno": logging.WARNING,
                        "levelname": "WARNING",
                        "msg": "loki_sink_missing_url_fallback_stdout",
                        "name": __name__,
                    }
                )
            )
            return stdout_handler

        try:
            import logging_loki  # type: ignore[import-not-found]

            loki_handler = logging_loki.LokiHandler(
                url=settings.LOKI_URL,
                tags={"application": "floatchat", "environment": settings.ENVIRONMENT},
                version="1",
            )
            loki_handler.setFormatter(formatter)
            return loki_handler
        except Exception:
            stdout_handler.handle(
                logging.makeLogRecord(
                    {
                        "levelno": logging.WARNING,
                        "levelname": "WARNING",
                        "msg": "loki_sink_init_failed_fallback_stdout",
                        "name": __name__,
                    }
                )
            )
            return stdout_handler

    if sink == "cloudwatch":
        if not settings.LOG_GROUP or not settings.LOG_STREAM:
            stdout_handler.handle(
                logging.makeLogRecord(
                    {
                        "levelno": logging.WARNING,
                        "levelname": "WARNING",
                        "msg": "cloudwatch_sink_missing_group_or_stream_fallback_stdout",
                        "name": __name__,
                    }
                )
            )
            return stdout_handler

        try:
            cw_handler = CloudWatchLogsHandler(
                log_group=settings.LOG_GROUP,
                log_stream=settings.LOG_STREAM,
                region_name=settings.S3_REGION,
            )
            cw_handler.setFormatter(formatter)
            return cw_handler
        except Exception:
            stdout_handler.handle(
                logging.makeLogRecord(
                    {
                        "levelno": logging.WARNING,
                        "levelname": "WARNING",
                        "msg": "cloudwatch_sink_init_failed_fallback_stdout",
                        "name": __name__,
                    }
                )
            )
            return stdout_handler

    stdout_handler.handle(
        logging.makeLogRecord(
            {
                "levelno": logging.WARNING,
                "levelname": "WARNING",
                "msg": "unknown_log_sink_fallback_stdout",
                "name": __name__,
            }
        )
    )
    return stdout_handler


# =============================================================================
# Structlog Configuration
# =============================================================================
def configure_logging() -> None:
    """
    Configure structlog for JSON logging with ISO timestamps.
    
    All logs are output as JSON with consistent fields:
    - timestamp: ISO 8601 format
    - level: log level (info, warning, error, etc.)
    - event: log message
    - Additional context fields (job_id, etc.)
    """
    # Shared processors for all loggers
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.ExtraAdder(),
    ]
    
    # Configure structlog
    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Configure stdlib logging to use structlog formatter
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    
    # Set up root logger with sink routing.
    handler = _build_logging_handler(formatter)
    
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(settings.LOG_LEVEL.upper())
    
    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


# =============================================================================
# Sentry Configuration
# =============================================================================
def configure_sentry() -> None:
    """Initialize Sentry error tracking through Feature 12 monitoring helper."""
    init_sentry()


def ensure_export_bucket(logger: structlog.stdlib.BoundLogger) -> None:
    """Ensure export bucket exists and has a 24-hour lifecycle policy."""
    endpoint = settings.S3_ENDPOINT_URL
    if endpoint:
        parsed = urlparse(endpoint)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        if host:
            try:
                with socket.create_connection((host, port), timeout=0.5):
                    pass
            except OSError:
                logger.warning(
                    "export_bucket_endpoint_unreachable",
                    endpoint=endpoint,
                )
                return

    try:
        client = get_s3_client()
    except Exception as exc:
        logger.warning("export_bucket_client_init_failed", error=str(exc))
        return

    create_kwargs: dict[str, Any] = {"Bucket": settings.EXPORT_BUCKET_NAME}
    if settings.S3_REGION and settings.S3_REGION != "us-east-1":
        create_kwargs["CreateBucketConfiguration"] = {
            "LocationConstraint": settings.S3_REGION,
        }

    try:
        client.create_bucket(**create_kwargs)
        logger.info("export_bucket_created", bucket=settings.EXPORT_BUCKET_NAME)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
            logger.warning(
                "export_bucket_create_failed",
                bucket=settings.EXPORT_BUCKET_NAME,
                error_code=code,
                error=str(exc),
            )
            return
    except Exception as exc:
        logger.warning(
            "export_bucket_create_unavailable",
            bucket=settings.EXPORT_BUCKET_NAME,
            error=str(exc),
        )
        return

    lifecycle_config = {
        "Rules": [
            {
                "ID": "expire-exports-1d",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},
                "Expiration": {"Days": 1},
            }
        ]
    }

    try:
        client.put_bucket_lifecycle_configuration(
            Bucket=settings.EXPORT_BUCKET_NAME,
            LifecycleConfiguration=lifecycle_config,
        )
        logger.info(
            "export_bucket_lifecycle_applied",
            bucket=settings.EXPORT_BUCKET_NAME,
            expiration_days=1,
        )
    except ClientError as exc:
        logger.warning(
            "export_bucket_lifecycle_failed",
            bucket=settings.EXPORT_BUCKET_NAME,
            error=str(exc),
        )
    except Exception as exc:
        logger.warning(
            "export_bucket_lifecycle_unavailable",
            bucket=settings.EXPORT_BUCKET_NAME,
            error=str(exc),
        )


# =============================================================================
# Application Lifespan
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler for startup and shutdown events.
    """
    # Startup
    configure_logging()
    configure_sentry()
    
    logger = structlog.get_logger()
    logger.info(
        "application_startup",
        app_name="FloatChat Ingestion API",
        debug=settings.DEBUG,
    )
    ensure_export_bucket(logger)
    
    yield
    
    # Shutdown
    logger.info("application_shutdown")


# =============================================================================
# FastAPI Application
# =============================================================================
app = FastAPI(
    title="FloatChat Ingestion API",
    description=(
        "FloatChat API for ARGO oceanographic data. Supports JWT bearer tokens and "
        "X-API-Key authentication for public API access."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# =============================================================================
# SlowAPI Rate Limiting Middleware (Feature 13)
# =============================================================================
def _rate_limit_exceeded_json_handler(request, exc: RateLimitExceeded):
    retry_after = 60
    headers = getattr(exc, "headers", None) or {}
    if "Retry-After" in headers:
        try:
            retry_after = int(headers["Retry-After"])
        except (TypeError, ValueError):
            retry_after = 60
    response = JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded", "retry_after": retry_after},
    )
    response.headers["Retry-After"] = str(retry_after)
    return response


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_json_handler)
app.add_middleware(SlowAPIMiddleware)


# =============================================================================
# CORS Middleware (Feature 5)
# =============================================================================
_cors_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _bind_endpoint_for_metrics(request: Request, call_next):
    token = set_current_endpoint(request.url.path)
    try:
        return await call_next(request)
    finally:
        reset_current_endpoint(token)


def _configure_prometheus_metrics() -> None:
    """Best-effort Prometheus instrumentation; never crash startup."""
    logger = structlog.get_logger()
    if Instrumentator is None:
        logger.warning("prometheus_instrumentator_unavailable")
        return

    try:
        instrumentator = Instrumentator(
            should_group_status_codes=False,
            should_ignore_untemplated=True,
            excluded_handlers=[
                "/health",
                "/api/v1/health",
                "/metrics",
            ],
        )
        instrumentator.instrument(app).expose(app, include_in_schema=False)
        logger.info("prometheus_metrics_configured", endpoint="/metrics")
    except Exception as exc:
        logger.warning("prometheus_metrics_config_failed", error=str(exc))


# =============================================================================
# Health Check Endpoint
# =============================================================================
@app.get("/health", tags=["Health"])
async def health_check() -> JSONResponse:
    """
    Health check endpoint for load balancers and monitoring.
    
    Returns:
        JSON response with status "ok"
    """
    return JSONResponse(
        content={"status": "ok"},
        status_code=200,
    )


# =============================================================================
# API Routers
# =============================================================================
from app.api.v1.ingestion import router as ingestion_router
from app.api.v1.search import router as search_router
from app.api.v1.query import router as query_router
from app.api.v1.chat import router as chat_router
from app.api.v1.map import router as map_router
from app.api.v1.auth import router as auth_router
from app.api.v1.export import router as export_router
from app.api.v1.anomalies import router as anomalies_router
from app.api.v1.clarification import router as clarification_router
from app.api.v1.admin import router as admin_router
from app.api.v1.health import router as health_router

app.include_router(ingestion_router, prefix="/api/v1")
app.include_router(search_router, prefix="/api/v1/search")
app.include_router(query_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(map_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(export_router, prefix="/api/v1")
app.include_router(anomalies_router, prefix="/api/v1")
app.include_router(clarification_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(health_router, prefix="/api/v1")

_configure_prometheus_metrics()


def custom_openapi():
    """Inject API key and bearer auth schemes into OpenAPI schema."""
    if app.openapi_schema:
        return app.openapi_schema

    from fastapi.openapi.utils import get_openapi

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    components = openapi_schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
    security_schemes["ApiKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
