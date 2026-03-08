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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.rate_limiter import limiter
from app.storage.s3 import get_s3_client


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
    
    # Set up root logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    
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
    """
    Initialize Sentry error tracking if SENTRY_DSN is configured.
    """
    if settings.SENTRY_DSN:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
            
            sentry_sdk.init(
                dsn=settings.SENTRY_DSN,
                integrations=[
                    FastApiIntegration(transaction_style="endpoint"),
                    SqlalchemyIntegration(),
                ],
                traces_sample_rate=0.1,  # 10% of requests traced
                profiles_sample_rate=0.1,
                environment="development" if settings.DEBUG else "production",
            )
            
            logger = structlog.get_logger()
            logger.info("sentry_initialized", dsn_prefix=settings.SENTRY_DSN[:20] + "...")
        except Exception as e:
            logger = structlog.get_logger()
            logger.warning("sentry_init_failed", error=str(e))


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
    description="Data Ingestion Pipeline for ARGO oceanographic float data",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)


# =============================================================================
# SlowAPI Rate Limiting Middleware (Feature 13)
# =============================================================================
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
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
