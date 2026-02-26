"""
FloatChat Backend API

FastAPI application entry point for the Data Ingestion Pipeline.
"""

import logging
import sys
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import settings


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

app.include_router(ingestion_router, prefix="/api/v1")
